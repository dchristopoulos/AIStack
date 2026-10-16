"""ADR-0025: a local mode Library is the replay of its log, on any computer, in one order."""

import base64
import contextlib
import random
import uuid

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from sqlalchemy import select

from aistack.bootstrap.configuration.settings.settings_config import LocalSettings
from aistack.bootstrap.context import application_context
from aistack.commons.exceptions import AIStackError
from aistack.db.engine import build_engine, build_session_factory
from aistack.db.models.harness import Harness
from aistack.db.models.library_event import LibraryEvent
from aistack.db.models.machine import Machine
from aistack.db.models.machine_harness import MachineHarness
from aistack.db.models.machine_project import MachineProject
from aistack.db.models.machine_project_skill import MachineProjectSkill
from aistack.db.models.machine_skill import MachineSkill
from aistack.db.models.project import Project
from aistack.db.models.skill import Skill
from aistack.db.models.skill_version import SkillVersion
from aistack.db.models.user import User
from aistack.db.schema import migrate_schema
from aistack.mcp import local_dashboard
from aistack.mcp.local import local_mcp
from aistack.services import (
    dashboard_service,
    library_log,
    local_identity,
    onboarding_service,
    skill_service,
    sync_service,
)
from tests.archives import skill_archive

pytestmark = pytest.mark.anyio

NAMES = ["wizard", "review", "notes"]


@pytest.fixture(name="anyio_backend")
def anyio_backend_fixture():
    return "asyncio"


@pytest.fixture(name="computer")
def computer_fixture(tmp_path, monkeypatch):
    @contextlib.asynccontextmanager
    async def computer(name: str, arrived: list[library_log.Event] = ()):
        """A computer with its own copy of the Library, which first catches up on `arrived`."""
        home = tmp_path / name
        home.mkdir(exist_ok=True)
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setenv("USERPROFILE", str(home))
        url = f"sqlite:///{home / 'copy.db'}"
        if arrived:
            engine = build_engine(url)
            migrate_schema(engine)
            with build_session_factory(engine).begin() as session:
                library_log.catch_up(session, list(arrived))
            engine.dispose()
        application_context.build_local_context(LocalSettings(
            aistack_home=home / ".aistack", aistack_database_url=url, aistack_username="maria"))
        try:
            async with Client(local_mcp) as client:
                yield client, home
        finally:
            local_dashboard.stop_dashboard()
            application_context.dispose_application_context()

    return computer


def _write(home, name, body):
    folder = home / ".claude" / "skills" / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {name} things.\n---\n\n"
                                     f"{body}\n")


def _events(session) -> list[library_log.Event]:
    return [library_log.Event.from_json(body)
            for body in session.scalars(select(LibraryEvent.body).order_by(LibraryEvent.sort_key))]


def _snapshot(session) -> dict:
    """The Library as a person sees it, in terms every computer agrees on."""
    skill_names = dict(session.execute(select(Skill.skill_id, Skill.name)).all())
    project_keys = dict(session.execute(select(Project.project_id, Project.key)).all())
    project_folders = {
        folder_id: (machine_id, project_keys[project_id], harness.value)
        for folder_id, machine_id, project_id, harness in session.execute(select(
            MachineProject.machine_project_id,
            MachineProject.machine_id,
            MachineProject.project_id,
            MachineProject.harness,
        ))
    }
    return {
        "users": sorted(session.execute(select(User.user_id, User.username)).all()),
        "machines": sorted(session.execute(select(Machine.machine_id, Machine.name)).all()),
        "skills": sorted(session.execute(select(Skill.name, Skill.archived, Skill.description)
                                         ).all()),
        "revisions": sorted(
            (skill_names[skill_id], revision, content_hash)
            for skill_id, revision, content_hash in session.execute(
                select(SkillVersion.skill_id, SkillVersion.revision,
                       SkillVersion.content_hash)).all()),
        "placements": sorted(
            (machine_id, harness.value, skill_names[skill_id], enabled, revision or 0)
            for machine_id, harness, skill_id, enabled, revision in session.execute(
                select(MachineSkill.machine_id, MachineSkill.harness, MachineSkill.skill_id,
                       MachineSkill.enabled, MachineSkill.revision)).all()),
        "folders": sorted((machine_id, harness.value) for machine_id, harness in session.execute(
            select(MachineHarness.machine_id, MachineHarness.harness)).all()),
        "projects": sorted(session.execute(select(
            Project.user_id,
            Project.key,
            Project.name,
        )).all()),
        "project_folders": sorted(
            (*project_folders[folder_id], path)
            for folder_id, path in session.execute(select(
                MachineProject.machine_project_id,
                MachineProject.path,
            ))
        ),
        "project_placements": sorted(
            (*project_folders[folder_id], skill_names[skill_id], enabled, revision or 0)
            for folder_id, skill_id, enabled, revision in session.execute(select(
                MachineProjectSkill.machine_project_id,
                MachineProjectSkill.skill_id,
                MachineProjectSkill.enabled,
                MachineProjectSkill.revision,
            ))
        ),
    }


def _replayed(tmp_path, events) -> dict:
    engine = build_engine(f"sqlite:///{tmp_path / 'replayed.db'}")
    migrate_schema(engine)
    try:
        prepared = library_log.prepared(events)
        with build_session_factory(engine).begin() as session:
            library_log.rebuild(session, events, validated=prepared)
            return _snapshot(session)
    finally:
        engine.dispose()


async def _call(client, tool, **arguments):
    return (await client.call_tool(tool, arguments)).structured_content


async def _random_changes(client, home, seed: int, steps: int = 25) -> None:
    """What a person does over weeks, in a random order: back up, edit, install, remove."""
    chance = random.Random(seed)
    for step in range(steps):
        name = chance.choice(NAMES)
        action = chance.choice(["push", "push", "get", "disable", "sync", "remove", "place",
                                "rename", "retire"])
        try:
            if action == "push":
                _write(home, name, f"revision written at step {step}")
                await _call(client, "push_skill", name=name,
                            harness=chance.choice(["claude_code", "agents"]))
            elif action == "get":
                await _call(client, "get_skill", name=name,
                            harness=chance.choice(["claude_code", "agents"]))
            elif action == "disable":
                await _call(client, "disable_skill", name=name)
            elif action == "sync":
                await _call(client, "sync", harness=chance.choice(["claude_code", "agents"]))
            else:
                caller = application_context.get_local_principal()
                with application_context.get_session_factory().begin() as session:
                    if action == "rename":
                        new_name = onboarding_service.rename_machine(
                            session, caller.user_id, str(caller.machine_id),
                            chance.choice(["laptop", "work laptop"]))
                        library_log.record(session, library_log.renamed(
                            session, caller.machine_id, caller.machine_id, new_name))
                    elif action == "retire":
                        # Another computer comes and goes: added, used, then removed here.
                        other = local_identity.local_machine(
                            session, uuid.uuid4(), "maria", f"old pc {step}", "WINDOWS")
                        library_log.record(session, library_log.new_event(
                            session, other.machine_id, library_log.FOLDER_SYNCED,
                            harness="claude_code"))
                        sync_service.record_sync(session, other.machine_id, Harness.CLAUDE_CODE)
                        library_log.record(session, library_log.removed(
                            session, caller.machine_id, other))
                        onboarding_service.remove_machine(session, caller.user_id,
                                                          str(other.machine_id))
                    elif action == "remove":
                        removed = skill_service.remove_from_my_skills(session, caller.user_id,
                                                                      name)
                        library_log.record(session, library_log.new_event(
                            session, caller.machine_id, library_log.SKILL_REMOVED,
                            name=removed))
                    else:
                        placed = dashboard_service.set_on_machine(
                            session, caller.user_id, name, str(caller.machine_id),
                            chance.random() < 0.5, "agents")
                        library_log.record(session, library_log.new_event(
                            session, caller.machine_id, library_log.SKILL_PLACED,
                            name=placed.name, harness=placed.harness, enabled=placed.enabled,
                            target_machine_id=str(placed.machine_id)))
        except (ToolError, AIStackError):
            # A refusal (no such skill yet, nothing to disable) changes nothing and logs nothing.
            pass


@pytest.mark.parametrize("seed", range(6))
async def test_replaying_a_librarys_log_builds_the_same_library(computer, tmp_path, seed):
    async with computer("laptop") as (laptop, home):
        await _random_changes(laptop, home, seed)
        with application_context.get_session_factory().begin() as session:
            built, events = _snapshot(session), _events(session)

    assert events[0].kind == library_log.MACHINE_ADDED
    assert _replayed(tmp_path, events) == built


async def test_two_computers_that_changed_one_skill_offline_end_up_the_same(computer):
    async with computer("laptop") as (laptop, home):
        _write(home, "wizard", "first")
        await _call(laptop, "push_skill", name="wizard")
        with application_context.get_session_factory().begin() as session:
            shared = _events(session)

    # The desktop joins from the laptop's log, then both edit the skill without talking.
    async with computer("desktop", shared) as (desktop, home):
        _write(home, "wizard", "edited on the desktop")
        await _call(desktop, "push_skill", name="wizard")
        with application_context.get_session_factory().begin() as session:
            from_desktop = _events(session)
    async with computer("laptop") as (laptop, home):
        _write(home, "wizard", "edited on the laptop")
        await _call(laptop, "push_skill", name="wizard")
        with application_context.get_session_factory().begin() as session:
            from_laptop = _events(session)

    # Each catches up on the other's log: one appends, the other has to rebuild.
    async with computer("laptop", from_desktop):
        with application_context.get_session_factory().begin() as session:
            laptop_sees = _snapshot(session)
    async with computer("desktop", from_laptop):
        with application_context.get_session_factory().begin() as session:
            desktop_sees = _snapshot(session)

    assert laptop_sees == desktop_sees
    assert [revision for name, revision, _ in laptop_sees["revisions"]] == [1, 2, 3]
    assert len(laptop_sees["machines"]) == 2 and len(laptop_sees["users"]) == 1


def test_two_new_computers_that_each_made_the_person_become_one_person(tmp_path):
    """Both started before either had pushed, so each logged a new user; the first one wins."""
    first, second = (
        library_log.Event(uuid.uuid4(), at, uuid.uuid4(), library_log.MACHINE_ADDED,
                          {"user_id": str(uuid.uuid4()), "username": "maria",
                           "machine_name": "laptop", "os": "MACOS"})
        for at in ("2026-10-15T09:00:00.000000Z", "2026-10-15T09:00:01.000000Z"))

    replayed = _replayed(tmp_path, [second, first])

    assert [username for _, username in replayed["users"]] == ["maria"]
    assert sorted(name for _, name in replayed["machines"]) == ["laptop", "laptop-2"]


async def test_a_call_that_changes_nothing_adds_nothing_to_the_log(computer):
    """DB-11: the log is never trimmed and every rebuild replays it, so a push of unchanged
    files and an install of what is installed record nothing."""
    def kinds():
        with application_context.get_session_factory().begin() as session:
            return [event.kind for event in _events(session)]

    async with computer("laptop") as (laptop, home):
        _write(home, "wizard", "first")
        await _call(laptop, "push_skill", name="wizard")
        logged = kinds()
        for _ in range(3):
            assert (await _call(laptop, "push_skill", name="wizard"))["unchanged"]
            await _call(laptop, "get_skill", name="wizard")
        assert kinds() == logged

        # Unchanged files, but a folder that did not have the skill: that is shared.
        (home / ".agents" / "skills").mkdir(parents=True)
        await _call(laptop, "get_skill", name="wizard", harness="agents")
        await _call(laptop, "disable_skill", name="wizard")
        await _call(laptop, "push_skill", name="wizard", harness="agents")
        _write(home, "wizard", "first")
        await _call(laptop, "push_skill", name="wizard")
        assert kinds() == [*logged, library_log.SKILL_PLACED, library_log.SKILL_PLACED,
                           library_log.SKILL_PLACED]
        with application_context.get_session_factory().begin() as session:
            built = _snapshot(session)
            events = _events(session)
    assert _replayed(home.parent, events) == built


async def test_a_rename_on_one_computer_reaches_a_second(computer):
    async with computer("laptop") as (laptop, _):
        laptop_id = application_context.get_local_principal().machine_id
        with application_context.get_session_factory().begin() as session:
            shared = _events(session)

    async with computer("desktop", shared) as (desktop, _):
        caller = application_context.get_local_principal()
        with application_context.get_session_factory().begin() as session:
            onboarding_service.rename_machine(session, caller.user_id, str(laptop_id),
                                              "old laptop")
            library_log.record(session, library_log.renamed(session, caller.machine_id,
                                                            laptop_id, "old laptop"))
            from_desktop = _events(session)

    async with computer("laptop", from_desktop):
        with application_context.get_session_factory().begin() as session:
            assert session.get(Machine, laptop_id).name == "old laptop"


LAPTOP, DESKTOP, STRANGER = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
MARIA = str(uuid.uuid4())


def _event(second: int, machine_id, kind: str, **data) -> library_log.Event:
    return library_log.Event(uuid.uuid4(), f"2026-10-15T09:00:{second:02d}.000000Z",
                             machine_id, kind, data)


def _added(second: int, machine_id, name: str) -> library_log.Event:
    return _event(second, machine_id, library_log.MACHINE_ADDED, user_id=MARIA,
                  username="maria", machine_name=name, os="LINUX")


def _removes(second: int, by, target, name: str) -> library_log.Event:
    return _event(second, by, library_log.MACHINE_REMOVED, target_machine_id=str(target),
                  name=name, os="LINUX")


def _renames(second: int, by, target, name: str) -> library_log.Event:
    return _event(second, by, library_log.MACHINE_RENAMED, target_machine_id=str(target),
                  name=name)


def _synced(second: int, machine_id) -> library_log.Event:
    return _event(second, machine_id, library_log.FOLDER_SYNCED, harness="claude_code")


def _machines(replayed: dict) -> dict:
    return {machine_id: name for machine_id, name in replayed["machines"]}


def test_a_removed_computer_that_was_still_in_use_comes_back(tmp_path):
    """ADR-0033: it was offline when the desktop removed it, then synced."""
    replayed = _replayed(tmp_path, [
        _added(1, LAPTOP, "laptop"), _synced(2, LAPTOP), _added(3, DESKTOP, "desktop"),
        _removes(4, DESKTOP, LAPTOP, "laptop"),
        # A new computer took the name while the laptop was away.
        _added(5, STRANGER, "laptop"),
        _synced(6, LAPTOP),
    ])

    assert _machines(replayed) == {LAPTOP: "laptop-2", DESKTOP: "desktop", STRANGER: "laptop"}
    # What it had before it was removed went with it; the sync after is its own.
    assert replayed["folders"] == [(LAPTOP, "claude_code")]


def test_a_removed_computer_stays_removed_until_it_changes_something(tmp_path):
    replayed = _replayed(tmp_path, [
        _added(1, LAPTOP, "laptop"), _added(2, DESKTOP, "desktop"), _synced(3, LAPTOP),
        _removes(4, DESKTOP, LAPTOP, "laptop"),
        # Placed on it by a computer that had not seen the removal: nothing to place on.
        _event(5, DESKTOP, library_log.SKILL_PLACED, name="wizard", harness="agents",
               enabled=True, target_machine_id=str(LAPTOP)),
        _renames(6, DESKTOP, LAPTOP, "old laptop"),
        _removes(7, DESKTOP, LAPTOP, "laptop"),
    ])

    assert _machines(replayed) == {DESKTOP: "desktop"}
    assert replayed["folders"] == []


def test_two_computers_that_removed_each_other_offline_keep_one(tmp_path):
    replayed = _replayed(tmp_path, [
        _added(1, LAPTOP, "laptop"), _added(2, DESKTOP, "desktop"),
        _removes(3, DESKTOP, LAPTOP, "laptop"),
        # The laptop had not seen that. Its change brings it back, and the last one stays.
        _removes(4, LAPTOP, DESKTOP, "desktop"),
        _removes(5, LAPTOP, LAPTOP, "laptop"),
    ])

    assert _machines(replayed) == {LAPTOP: "laptop"}


def test_two_computers_renamed_to_one_name_offline_both_keep_a_name(tmp_path):
    replayed = _replayed(tmp_path, [
        _added(1, LAPTOP, "laptop"), _added(2, DESKTOP, "desktop"),
        _renames(3, LAPTOP, LAPTOP, "home"), _renames(4, DESKTOP, DESKTOP, "home"),
        _renames(5, DESKTOP, DESKTOP, "home"),
    ])

    assert _machines(replayed) == {LAPTOP: "home", DESKTOP: "home-2"}


def test_a_change_from_a_computer_that_was_never_added_is_still_refused(tmp_path):
    with pytest.raises(AIStackError, match="before that computer was added"):
        _replayed(tmp_path, [_added(1, LAPTOP, "laptop"), _synced(2, STRANGER)])


PROJECT_KEY = "github.com/acme/billing"


def _project_changes():
    def pushed(second, machine_id, name, harness, description, project=False):
        return _event(
            second,
            machine_id,
            library_log.SKILL_PUSHED_TO_PROJECT if project else library_log.SKILL_PUSHED,
            name=name,
            harness=harness,
            origin=None,
            archive=base64.b64encode(skill_archive(name, description=description)).decode(),
            **({"project": PROJECT_KEY, "project_name": "billing"} if project else {}),
        )

    def folder(second, by, harness, path=None, target=None):
        return _event(
            second,
            by,
            library_log.PROJECT_FOLDER_ADDED,
            project=PROJECT_KEY,
            project_name="billing",
            harness=harness,
            path=path,
            target_machine_id=None if target is None else str(target),
        )

    baseline = [
        _added(1, LAPTOP, "laptop"),
        _added(2, DESKTOP, "desktop"),
        pushed(3, LAPTOP, "wizard", "claude_code", "Global skill."),
    ]
    changes = [
        folder(4, LAPTOP, "claude_code", "/work/billing"),
        pushed(5, LAPTOP, "project-note", "claude_code", "First project edit.", True),
        folder(6, LAPTOP, "agents", target=DESKTOP),
        _event(
            7,
            DESKTOP,
            library_log.SKILL_PLACED_IN_PROJECT,
            project=PROJECT_KEY,
            name="wizard",
            harness="agents",
            enabled=True,
            revision=1,
        ),
        _event(
            8,
            LAPTOP,
            library_log.PROJECT_FOLDER_REMOVED,
            project=PROJECT_KEY,
            harness="claude_code",
        ),
        folder(9, LAPTOP, "claude_code", "/work/clones/billing"),
        _event(
            10,
            LAPTOP,
            library_log.SKILL_PLACED_IN_PROJECT,
            project=PROJECT_KEY,
            name="wizard",
            harness="claude_code",
            enabled=False,
            revision=1,
        ),
        pushed(11, DESKTOP, "project-note", "agents", "Second project edit.", True),
        _event(12, LAPTOP, library_log.SKILL_REMOVED, name="wizard"),
        _event(
            13,
            DESKTOP,
            library_log.SKILL_PLACED_IN_PROJECT,
            project=PROJECT_KEY,
            name="wizard",
            harness="agents",
            enabled=True,
            revision=1,
        ),
        folder(14, LAPTOP, "agents"),
        _event(
            15,
            LAPTOP,
            library_log.PROJECT_FOLDER_REMOVED,
            project=PROJECT_KEY,
            harness=None,
        ),
    ]
    return baseline, changes


@pytest.mark.parametrize("seed", range(5))
def test_project_events_converge_when_appended_or_rebuilt(
    portable_engine, tmp_path, monkeypatch, seed,
):
    baseline, changes = _project_changes()
    expected = _replayed(tmp_path, [*baseline, *changes])
    assert expected["projects"] == [(uuid.UUID(MARIA), PROJECT_KEY, "billing")]
    assert expected["project_folders"] == [(DESKTOP, PROJECT_KEY, "agents", None)]
    assert expected["project_placements"] == [
        (DESKTOP, PROJECT_KEY, "agents", "project-note", True, 2),
        (DESKTOP, PROJECT_KEY, "agents", "wizard", True, 1),
    ]
    assert all(row[2] != "project-note" for row in expected["placements"])

    def unexpected_archive_read(*args, **kwargs):
        raise AssertionError("Replay must use archives prepared before its transaction.")

    monkeypatch.setattr(skill_service, "read_archive", unexpected_archive_read)
    session_factory = build_session_factory(portable_engine)
    arrived = list(baseline)
    prepared = library_log.prepared(arrived)
    with session_factory.begin() as session:
        assert library_log.append(session, arrived, prepared)
    random.Random(seed).shuffle(changes)
    for event in changes:
        arrived.append(event)
        prepared = library_log.prepared(arrived)
        with session_factory.begin() as session:
            new = library_log.arrivals(session, arrived)
            if not library_log.append(session, new, prepared):
                library_log.rebuild(session, arrived, validated=prepared)
    with session_factory() as session:
        assert _snapshot(session) == expected


@pytest.mark.parametrize("kind", sorted(library_log._PROJECT_KINDS))
def test_this_release_cannot_record_a_project_event(session_factory, kind):
    event = _event(1, LAPTOP, kind)
    with pytest.raises(AssertionError, match="replays.*records none"):
        with session_factory.begin() as session:
            library_log.record(session, event)


def test_project_events_still_replay_after_a_later_release_enables_writing(tmp_path, monkeypatch):
    baseline, changes = _project_changes()
    monkeypatch.setattr(library_log, "_REPLAY_ONLY", set())
    assert len(_replayed(tmp_path, [*baseline, *changes])["project_placements"]) == 2


@pytest.mark.parametrize("key", [
    "github.com/user@token/repo",
    "github.com/acme/\nrepo",
    "x/" + "r" * 254,
])
def test_a_forged_project_key_is_refused_with_its_log_file(tmp_path, key):
    event = _event(
        2,
        LAPTOP,
        library_log.PROJECT_FOLDER_ADDED,
        project=key,
        project_name="billing",
        harness="agents",
        path="/work/billing",
    )
    with pytest.raises(AIStackError) as refused:
        _replayed(tmp_path, [_added(1, LAPTOP, "laptop"), event])
    assert f"log/{event.path}" in str(refused.value)
    assert "token" not in str(refused.value)


@pytest.mark.parametrize("invalid", [
    {"project_name": "x" * 65},
    {"project_name": "name\nforged"},
    {"harness": "unknown"},
    {"path": "~"},
    {"path": "/" + "x" * 1024},
])
def test_project_replay_checks_names_harnesses_and_paths(tmp_path, invalid):
    data = {"project": PROJECT_KEY, "project_name": "billing", "harness": "agents",
            "path": "/work/billing"}
    event = _event(2, LAPTOP, library_log.PROJECT_FOLDER_ADDED, **(data | invalid))
    with pytest.raises(AIStackError) as refused:
        _replayed(tmp_path, [_added(1, LAPTOP, "laptop"), event])
    assert f"log/{event.path}" in str(refused.value)
