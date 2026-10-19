"""ADR-0025: a local mode Library is the replay of its log, on any computer, in one order."""

import base64
import contextlib
import random
import uuid

import httpx
import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from sqlalchemy import select
from starlette.applications import Starlette

from aistack.api import dashboard
from aistack.api.dashboard import REQUEST_HEADER
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
from aistack.mcp.server_url import DASHBOARD_LOGIN_PATH
from aistack.services import (
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


@contextlib.asynccontextmanager
async def _dashboard():
    """The localhost dashboard's own routes, signed in, in this process and this context: its
    writes go through the real route, which must record its event (IMP-03)."""
    app = Starlette(routes=dashboard.LOCAL_ROUTES)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://127.0.0.1:8765") as browser:
        holder = application_context.get_local_principal().dashboard_holder()
        ticket = application_context.get_ticket_signer().sign_dashboard_link(holder)
        assert (await browser.get(f"{DASHBOARD_LOGIN_PATH}/{ticket}")).status_code == 303
        yield browser


async def _post(browser, path: str, **body) -> httpx.Response:
    return await browser.post(path, json=body, headers={REQUEST_HEADER: "1"})


async def _random_changes(client, home, seed: int, steps: int = 25) -> None:
    """What a person does over weeks, in a random order: back up, edit, install, remove."""
    async with _dashboard() as browser:
        await _random_changes_with(client, browser, home, seed, steps)


async def _random_changes_with(client, browser, home, seed: int, steps: int) -> None:
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
            elif action == "remove":
                await _post(browser, f"/api/skills/{name}/remove")
            elif action == "place":
                machine = application_context.get_local_principal().machine_id
                await _post(browser, f"/api/skills/{name}/machines/{machine}",
                            enabled=chance.random() < 0.5, harness="agents")
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
        except (ToolError, AIStackError):
            # A refusal (no such skill yet, nothing to disable) changes nothing and logs nothing.
            pass


# Every POST the localhost dashboard serves, with a body that works: each changes the Library,
# so each must record an event. A new local action fails the test below until it is here.
LOCAL_WRITES = {
    "/api/skills/{name}/machines/{machine_id}": {"enabled": True, "harness": "agents"},
    "/api/skills/{name}/remove": {},
}
# The POSTs that change only this browser's session, not the Library.
SESSION_ONLY = {"/api/logout", "/app/login/{ticket}"}


async def test_every_localhost_dashboard_write_records_its_event(computer):
    """IMP-03: a route that forgot its event was caught by nothing."""
    posts = {route.path for route in dashboard.LOCAL_ROUTES if "POST" in route.methods}
    assert posts == set(LOCAL_WRITES) | SESSION_ONLY

    async with computer("laptop") as (laptop, home):
        _write(home, "wizard", "first")
        await _call(laptop, "push_skill", name="wizard")
        machine = application_context.get_local_principal().machine_id
        async with _dashboard() as browser:
            for path, body in LOCAL_WRITES.items():
                with application_context.get_session_factory().begin() as session:
                    before = len(_events(session))
                response = await _post(browser, path.format(name="wizard", machine_id=machine),
                                       **body)
                assert response.status_code == 200, (path, response.text)
                with application_context.get_session_factory().begin() as session:
                    assert len(_events(session)) > before, path


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


@pytest.mark.parametrize("kind", sorted(library_log._REPLAY_ONLY))
def test_this_release_cannot_record_a_replay_only_event(session_factory, kind):
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


def _moves(second: int, by, **place) -> library_log.Event:
    return _event(second, by, library_log.LIBRARY_MOVED, place=place)


def test_a_library_that_moved_still_replays(tmp_path):
    """AUTO-05: the release before the one that records a move must read it, or every
    computer still on it stops at a change of a kind it does not know (ADR-0024)."""
    replayed = _replayed(tmp_path, [
        _added(1, LAPTOP, "laptop"), _synced(2, LAPTOP),
        _moves(3, LAPTOP, kind="github", repository="maria/skills"), _synced(4, LAPTOP),
    ])

    assert _machines(replayed) == {LAPTOP: "laptop"}


@pytest.mark.anyio
@pytest.mark.parametrize("place, sentence", [
    ({"kind": "github", "repository": "maria/skills"},
     "moved to the GitHub repository maria/skills on 2026-10-15. Set AIStack up again"),
    ({"kind": "postgresql", "host": "db.example.com", "database": "library"},
     "moved to the PostgreSQL database library at db.example.com on 2026-10-15."),
    ({"kind": "this_computer"}, "moved onto '[^']+' alone on 2026-10-15"),
    ({"kind": "the_moon"}, "a place this release cannot name"),
])
async def test_every_tool_on_a_moved_library_says_where_it_went(computer, place, sentence):
    async with computer("laptop") as (laptop, home):
        _write(home, "wizard", "Cast spells.")
        await _call(laptop, "sync")
        caller = application_context.get_local_principal()
        moved = library_log.Event(uuid.uuid4(), "2026-10-15T09:00:00.000000Z",
                                  caller.machine_id, library_log.LIBRARY_MOVED, {"place": place})
        with application_context.get_session_factory().begin() as session:
            # As replay stores it: this release records no move of its own.
            library_log._store_event(session, moved, published=True)
            before = _snapshot(session)

        for tool, arguments in [("sync", {}), ("list_skills", {}), ("get_skill", {"name": "wizard"}),
                                ("push_skill", {"name": "wizard"}),
                                ("disable_skill", {"name": "wizard"}), ("open_dashboard", {})]:
            with pytest.raises(ToolError, match=sentence):
                await laptop.call_tool(tool, arguments)

        with application_context.get_session_factory().begin() as session:
            assert _snapshot(session) == before


# --- what an event carries, and what replay refuses -----------------------------------------

BEN = uuid.uuid4()


def test_an_event_is_one_canonical_line():
    """Every computer reads the same file, so its text is fixed: sorted keys, no spaces."""
    event = library_log.Event(uuid.UUID(int=1), "2026-10-15T09:00:01.000000Z", uuid.UUID(int=2),
                              library_log.SKILL_REMOVED, {"name": "wizard", "a": [1, 2]})

    assert event.to_json() == (
        '{"at":"2026-10-15T09:00:01.000000Z","data":{"a":[1,2],"name":"wizard"},'
        '"event_id":"00000000-0000-0000-0000-000000000001","kind":"skill_removed",'
        '"machine_id":"00000000-0000-0000-0000-000000000002"}')
    assert library_log.Event.from_json(event.to_json()) == event


def test_appended_events_are_stored_as_published_and_never_appended_twice(session_factory):
    first, second = _added(1, LAPTOP, "laptop"), _synced(2, LAPTOP)
    with session_factory.begin() as session:
        assert library_log.append(session, [first]) is True
        # The same event again sorts at, not after, what the copy holds.
        assert library_log.append(session, [first]) is False
        assert library_log.append(session, [second]) is True
        assert library_log.unpublished(session) == []
        assert [row.published for row in session.scalars(select(LibraryEvent))] == [True, True]


def test_catch_up_rebuilds_only_when_an_arrival_sorts_before_what_the_copy_holds(session_factory):
    early = _synced(3, DESKTOP)
    with session_factory.begin() as session:
        assert library_log.catch_up(session, [_added(1, LAPTOP, "laptop"),
                                              _added(2, DESKTOP, "desktop")]) is False
        assert library_log.catch_up(session, [_synced(4, LAPTOP)]) is False
    with session_factory.begin() as session:
        arrived = [*_events(session), early]
        assert library_log.catch_up(session, arrived) is True
        assert early.event_id in library_log.known_ids(session)


def _pushed_event(second, machine_id, name, harness, origin, project=False):
    return _event(
        second,
        machine_id,
        library_log.SKILL_PUSHED_TO_PROJECT if project else library_log.SKILL_PUSHED,
        name=name,
        origin=origin,
        harness=harness,
        archive=base64.b64encode(skill_archive(name)).decode(),
        **({"project": PROJECT_KEY, "project_name": "billing"} if project else {}),
    )


def test_a_push_event_carries_its_name_origin_harness_and_files(session_factory):
    archive = skill_archive("wizard")
    with session_factory.begin() as session:
        library_log.append(session, [_added(1, LAPTOP, "laptop")])
        event = library_log.pushed(session, LAPTOP, "wizard", "github.com/acme/skills", "agents",
                                   archive)

    assert event.kind == library_log.SKILL_PUSHED
    assert event.data == {"name": "wizard", "origin": "github.com/acme/skills",
                          "harness": "agents",
                          "archive": base64.b64encode(archive).decode("ascii")}


@pytest.mark.parametrize("prepared", [True, False], ids=["read-ahead", "read-in-replay"])
def test_a_replayed_push_keeps_its_origin_and_its_harness(portable_engine, prepared):
    events = [
        _added(1, LAPTOP, "laptop"),
        _pushed_event(2, LAPTOP, "wizard", "agents", "github.com/acme/skills"),
        _event(3, LAPTOP, library_log.PROJECT_FOLDER_ADDED, project=PROJECT_KEY,
               project_name="billing", harness="claude_code", path="/work/billing"),
        _pushed_event(4, LAPTOP, "notes", "claude_code", "github.com/acme/notes", project=True),
    ]
    with build_session_factory(portable_engine).begin() as session:
        library_log.append(session, events, library_log.prepared(events) if prepared else None)
        snapshot = _snapshot(session)
        origins = dict(session.execute(select(Skill.name, Skill.origin)).all())

    assert origins == {"wizard": "github.com/acme/skills", "notes": "github.com/acme/notes"}
    assert snapshot["placements"] == [(LAPTOP, "agents", "wizard", True, 1)]
    assert snapshot["project_placements"] == [
        (LAPTOP, PROJECT_KEY, "claude_code", "notes", True, 1)]


def test_project_events_replay_alike_with_and_without_archives_read_ahead(tmp_path,
                                                                          session_factory):
    baseline, changes = _project_changes()
    expected = _replayed(tmp_path, [*baseline, *changes])

    with session_factory.begin() as session:
        library_log.append(session, [*baseline, *changes])
        assert _snapshot(session) == expected


def test_a_removal_and_a_rename_carry_what_brings_the_computer_back(session_factory):
    with session_factory.begin() as session:
        library_log.append(session, [_added(1, LAPTOP, "laptop"), _added(2, DESKTOP, "desktop")])
        laptop = session.get(Machine, LAPTOP)
        removal = library_log.removed(session, DESKTOP, laptop)
        rename = library_log.renamed(session, DESKTOP, LAPTOP, "old laptop")

    assert (removal.machine_id, removal.kind) == (DESKTOP, library_log.MACHINE_REMOVED)
    assert removal.data == {"target_machine_id": str(LAPTOP), "name": "laptop", "os": "LINUX"}
    assert (rename.machine_id, rename.kind) == (DESKTOP, library_log.MACHINE_RENAMED)
    assert rename.data == {"target_machine_id": str(LAPTOP), "name": "old laptop"}


def test_a_computer_that_comes_back_keeps_the_name_and_system_its_removal_recorded(
        session_factory):
    removal = _event(4, DESKTOP, library_log.MACHINE_REMOVED, target_machine_id=str(LAPTOP),
                     name="old laptop", os="WINDOWS")
    with session_factory.begin() as session:
        library_log.append(session, [_added(1, LAPTOP, "laptop"), _added(2, DESKTOP, "desktop"),
                                     removal, _synced(5, LAPTOP)])
        laptop = session.get(Machine, LAPTOP)
        assert (laptop.name, laptop.os.value) == ("old laptop", "WINDOWS")


def test_two_computers_added_with_one_name_replay_to_two_names(tmp_path):
    longest = "x" * 64
    replayed = _replayed(tmp_path, [
        _added(1, LAPTOP, "laptop"), _added(2, DESKTOP, "laptop"),
        _added(3, STRANGER, longest), _added(4, uuid.UUID(int=4), longest),
    ])

    assert _machines(replayed) == {LAPTOP: "laptop", DESKTOP: "laptop-2", STRANGER: longest,
                                   uuid.UUID(int=4): "x" * 62 + "-2"}


def test_a_computer_added_twice_in_the_log_is_one_computer(tmp_path):
    replayed = _replayed(tmp_path, [_added(1, LAPTOP, "laptop"), _added(2, LAPTOP, "renamed")])

    assert _machines(replayed) == {LAPTOP: "laptop"}


def _two_people(session_factory):
    """Ben's computer and Maria's, in one database: replay must keep to Maria's."""
    with session_factory.begin() as session:
        onboarding_service.join(session, "ben", "laptop", "MACOS", machine_id=STRANGER,
                                user_id=BEN)
        onboarding_service.join(session, "maria", "desktop", "LINUX", machine_id=DESKTOP,
                                user_id=uuid.UUID(MARIA))


def test_replay_names_and_counts_only_the_persons_own_computers(session_factory):
    _two_people(session_factory)
    with session_factory.begin() as session:
        # Ben's "laptop" does not take the name from Maria's.
        library_log.append(session, [_added(1, LAPTOP, "laptop")])
        assert session.get(Machine, LAPTOP).name == "laptop"
        # Her last computer is not removed because Ben has one.
        library_log.append(session, [_removes(2, LAPTOP, LAPTOP, "laptop"),
                                     _removes(3, DESKTOP, DESKTOP, "desktop")])
        owners = dict(session.execute(select(Machine.machine_id, Machine.user_id)).all())

    assert owners == {STRANGER: BEN, DESKTOP: uuid.UUID(MARIA)}


def test_a_log_cannot_change_another_persons_computer(session_factory):
    _two_people(session_factory)
    with session_factory.begin() as session:
        library_log.append(session, [
            _event(1, DESKTOP, library_log.PROJECT_FOLDER_ADDED, project=PROJECT_KEY,
                   project_name="billing", harness="agents", target_machine_id=str(STRANGER)),
            _removes(2, DESKTOP, STRANGER, "laptop"),
            _renames(3, DESKTOP, STRANGER, "taken"),
        ])
        assert session.scalar(select(MachineProject.machine_project_id)) is None
        assert session.get(Machine, STRANGER).name == "laptop"


def test_a_project_folder_keeps_a_path_only_when_its_own_computer_added_it(tmp_path):
    def folder(second, target, path):
        return _event(second, LAPTOP, library_log.PROJECT_FOLDER_ADDED, project=PROJECT_KEY,
                      project_name="billing", harness="agents", path=path,
                      target_machine_id=str(target))

    replayed = _replayed(tmp_path, [
        _added(1, LAPTOP, "laptop"), _added(2, DESKTOP, "desktop"),
        folder(3, LAPTOP, "/work/billing"),
        # A path from another computer is where the repository is there, not here.
        folder(4, DESKTOP, "/elsewhere/billing"),
    ])

    assert replayed["project_folders"] == sorted([
        (LAPTOP, PROJECT_KEY, "agents", "/work/billing"),
        (DESKTOP, PROJECT_KEY, "agents", None),
    ])


def test_a_removal_of_a_computer_nobody_has_changes_nothing(tmp_path):
    replayed = _replayed(tmp_path, [_added(1, LAPTOP, "laptop"),
                                    _removes(2, LAPTOP, STRANGER, "ghost")])

    assert _machines(replayed) == {LAPTOP: "laptop"}


@pytest.mark.parametrize("change, sentence", [
    (lambda: _event(3, LAPTOP, library_log.SKILL_PLACED, name="wizard", harness="agents",
                    enabled=True, revision="1"), "revision that is not a number"),
    (lambda: _event(3, LAPTOP, library_log.SKILL_PLACED_IN_PROJECT, project=PROJECT_KEY,
                    name="wizard", harness="agents", enabled=True, revision="1"),
     "revision that is not a number"),
    (lambda: _removes(3, LAPTOP, "not-an-id", "laptop"), "not an id"),
    (lambda: _renames(3, LAPTOP, LAPTOP, 5), "not text"),
], ids=["revision", "project-revision", "computer-id", "computer-name"])
def test_replay_refuses_a_hand_edited_value_and_names_its_file(tmp_path, change, sentence):
    event = change()
    with pytest.raises(AIStackError) as refused:
        _replayed(tmp_path, [
            _added(1, LAPTOP, "laptop"),
            _pushed_event(2, LAPTOP, "wizard", "agents", None),
            _event(2, LAPTOP, library_log.PROJECT_FOLDER_ADDED, project=PROJECT_KEY,
                   project_name="billing", harness="agents", path="/work/billing"),
            event,
        ])

    assert f"log/{event.path}" in str(refused.value)
    assert sentence in str(refused.value)
