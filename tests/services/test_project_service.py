"""Project folders and their placements (ADR-0026), as rules a user would state."""

import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select, update

from aistack.commons.exceptions import NotFound
from aistack.db.engine import build_session_factory
from aistack.db.models.harness import Harness
from aistack.db.models.machine_project import MachineProject
from aistack.db.models.machine_project_skill import MachineProjectSkill
from aistack.db.models.machine_skill import MachineSkill
from aistack.db.models.project import Project
from aistack.db.models.skill import Skill
from aistack.services import onboarding_service, project_service, skill_service, sync_service
from aistack.services.reconciliation import Desired, Observed
from tests.archives import local_digests, skill_archive

KEY = "github.com/acme/billing"
PATH = "/Users/dimitris/code/billing"


@pytest.fixture(name="session_factory")
def session_factory_fixture(portable_engine):
    return build_session_factory(portable_engine)


@pytest.fixture(name="dimitris")
def dimitris_fixture(session_factory):
    with session_factory.begin() as session:
        return onboarding_service.join(session, "dimitris", "macbook", "MACOS")


@pytest.fixture(name="desktop")
def desktop_fixture(session_factory, dimitris):
    with session_factory.begin() as session:
        added = onboarding_service.add_machine(session, dimitris.user.user_id, "desktop",
                                               "LINUX")
    return SimpleNamespace(user=dimitris.user, machine=added.machine)


def _register(session_factory, joined, harness=Harness.CLAUDE_CODE, path=PATH):
    with session_factory.begin() as session:
        registered = project_service.register_folder(
            session,
            joined.user.user_id,
            joined.machine.machine_id,
            KEY,
            "billing",
            harness,
            path,
        )
        return registered.first_sync


def _push(session_factory, joined, name="wizard"):
    with session_factory.begin() as session:
        skill_service.push(session, machine_id=joined.machine.machine_id,
                           user_id=joined.user.user_id, name=name, origin=None,
                           archive=skill_archive(name))


def _place(session_factory, joined, name="wizard", enabled=True):
    with session_factory.begin() as session:
        folder = project_service.required_folder(session, joined.user.user_id,
                                                 joined.machine.machine_id, KEY,
                                                 Harness.CLAUDE_CODE)
        skill = session.scalar(select(Skill).where(Skill.name == name))
        project_service.set_enabled(session, folder, skill.skill_id, enabled)


def _decisions(session_factory, joined):
    with session_factory.begin() as session:
        folder = project_service.required_folder(session, joined.user.user_id,
                                                 joined.machine.machine_id, KEY,
                                                 Harness.CLAUDE_CODE)
        return project_service.decisions(session, folder)


def test_a_folders_first_sync_is_reported_once(session_factory, dimitris):
    assert _register(session_factory, dimitris) is True
    assert _register(session_factory, dimitris, path="/Users/dimitris/clones/billing") is False

    with session_factory() as session:
        folder = session.scalars(select(MachineProject)).one()
        assert folder.path == "/Users/dimitris/clones/billing"
        assert folder.last_synced_on is not None
        assert session.scalar(select(func.count()).select_from(Project)) == 1


def test_each_harness_is_its_own_folder_in_one_project(session_factory, dimitris):
    assert _register(session_factory, dimitris, Harness.CLAUDE_CODE) is True
    assert _register(session_factory, dimitris, Harness.AGENTS) is True

    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(MachineProject)) == 2
        assert session.scalar(select(func.count()).select_from(Project)) == 1


def test_a_folder_added_on_the_dashboard_first_syncs_when_it_syncs(session_factory, dimitris,
                                                                   desktop):
    _register(session_factory, dimitris)
    with session_factory.begin() as session:
        added = project_service.add_folder(session, desktop.user.user_id,
                                           desktop.machine.machine_id, KEY, Harness.CLAUDE_CODE)
        assert added.path is None and added.last_synced_on is None

    assert _register(session_factory, desktop) is True
    assert _register(session_factory, desktop) is False


def test_two_first_syncs_at_once_report_one_first_sync(postgres_engine, monkeypatch):
    """Two clones of one repository on one computer, syncing together. The barrier sits after
    both found no folder and before either inserts one. Without the savepoint the loser's
    duplicate aborts its whole transaction, and that sync fails."""
    session_factory = build_session_factory(postgres_engine)
    with session_factory.begin() as session:
        dimitris = onboarding_service.join(session, "dimitris", "macbook", "MACOS")
        session.add(Project(user_id=dimitris.user.user_id, key=KEY, name="billing"))

    at_the_insert = threading.Barrier(2)
    find_folder = project_service._folder
    waited = threading.local()

    def find_together(*args):
        found = find_folder(*args)
        if not getattr(waited, "done", False):
            waited.done = True
            at_the_insert.wait(timeout=30)
        return found

    monkeypatch.setattr(project_service, "_folder", find_together)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first_syncs = list(pool.map(lambda _: _register(session_factory, dimitris), range(2)))

    assert sorted(first_syncs) == [False, True]
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(MachineProject)) == 1


def test_removing_a_skill_from_the_library_takes_it_out_of_every_project_folder(
        session_factory, dimitris):
    _push(session_factory, dimitris)
    _register(session_factory, dimitris)
    _place(session_factory, dimitris)

    with session_factory.begin() as session:
        skill_service.remove_from_my_skills(session, dimitris.user.user_id, "wizard")

    with session_factory() as session:
        assert session.scalars(select(MachineProjectSkill.enabled)).all() == [False]


def test_a_removed_skill_an_older_release_left_placed_is_wanted_nowhere(session_factory,
                                                                        dimitris):
    """A release from before projects removes a skill without touching the project tables:
    the placement stays enabled and the skill archived."""
    _push(session_factory, dimitris)
    _register(session_factory, dimitris)
    _place(session_factory, dimitris)
    with session_factory.begin() as session:
        session.execute(update(Skill).values(archived=True))

    assert _decisions(session_factory, dimitris) == {"wizard": (False, None)}


def test_a_removed_skill_left_enabled_in_a_global_folder_is_asked_about_and_never_installed(
        session_factory, dimitris):
    _push(session_factory, dimitris)
    with session_factory.begin() as session:
        session.execute(update(Skill).values(archived=True))
        session.execute(update(MachineSkill).values(enabled=True))

    def sync(local):
        with session_factory.begin() as session:
            return sync_service.sync(session, dimitris.machine.machine_id,
                                     dimitris.user.user_id, local)

    present = sync({"wizard": local_digests("wizard")})
    assert [(question.name, question.desired, question.local) for question in present.ask] == \
        [("wizard", Desired.DISABLED, Observed.CURRENT)]
    assert sync({}).install == ()


def test_a_first_sync_offers_what_the_other_computers_placed_in_the_project(session_factory,
                                                                            dimitris, desktop):
    for name in ("wizard", "drafted", "retired", "off"):
        _push(session_factory, dimitris, name)
    _register(session_factory, dimitris)
    for name in ("wizard", "drafted", "retired"):
        _place(session_factory, dimitris, name)
    _place(session_factory, dimitris, "off", enabled=False)
    with session_factory.begin() as session:
        # Removed by a release from before projects, so its placement is still enabled.
        session.execute(update(Skill).where(Skill.name == "retired").values(archived=True))
    _register(session_factory, desktop)
    _place(session_factory, desktop, "wizard")

    with session_factory() as session:
        project = session.scalars(select(Project)).one()
        offered_to_desktop = project_service.placed_elsewhere(
            session, desktop.user.user_id, project.project_id, desktop.machine.machine_id)
        offered_to_macbook = project_service.placed_elsewhere(
            session, dimitris.user.user_id, project.project_id, dimitris.machine.machine_id)

    assert offered_to_desktop == ["drafted", "wizard"]
    assert offered_to_macbook == ["wizard"]


def test_no_longer_managing_a_project_takes_its_placements_and_nothing_else(session_factory,
                                                                            dimitris, desktop):
    _push(session_factory, dimitris)
    for computer in (dimitris, desktop):
        _register(session_factory, computer)
        _place(session_factory, computer)

    with session_factory.begin() as session:
        assert project_service.remove_folder(session, dimitris.user.user_id,
                                             dimitris.machine.machine_id, KEY) == 1

    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(MachineProjectSkill)) == 1
        assert session.scalar(select(func.count()).select_from(Project)) == 1
        assert session.scalar(select(func.count()).select_from(Skill)) == 1
    assert _decisions(session_factory, desktop) == {"wizard": (True, None)}


def test_a_project_somebody_else_manages_answers_like_one_nobody_does(session_factory,
                                                                      dimitris):
    _register(session_factory, dimitris)
    with session_factory.begin() as session:
        maria = onboarding_service.join(session, "maria", "laptop", "LINUX")

    refusals = []
    for key in (KEY, "github.com/acme/nothing"):
        with session_factory.begin() as session:
            for attempt in (
                lambda: project_service.required_folder(session, maria.user.user_id,
                                                        maria.machine.machine_id, key,
                                                        Harness.CLAUDE_CODE),
                lambda: project_service.add_folder(session, maria.user.user_id,
                                                   maria.machine.machine_id, key,
                                                   Harness.CLAUDE_CODE),
                lambda: project_service.remove_folder(session, maria.user.user_id,
                                                      maria.machine.machine_id, key),
            ):
                with pytest.raises(NotFound) as refused:
                    attempt()
                refusals.append(refused.value.message.replace(key, "<key>"))

    assert refusals[:3] == refusals[3:]
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(MachineProject)) == 1
