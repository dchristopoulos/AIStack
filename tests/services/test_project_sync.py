"""Syncing a project's skills folder (ADR-0026): the global folder's rules, one folder at a
time, with the repository's own folders left alone."""

from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from aistack.commons.exceptions import ValidationError
from aistack.db.engine import build_session_factory
from aistack.db.models import Base
from aistack.db.models.harness import Harness
from aistack.services import (
    onboarding_service,
    project_service,
    projects,
    skill_service,
    sync_service,
    visibility,
)
from tests.archives import local_digests, skill_archive

REMOTE = "git@github.com:dchristopoulos/AIStack.git"
KEY = "github.com/dchristopoulos/aistack"
HERE = projects.validated_here("/Users/dimitris/code/aistack", REMOTE)
# A second clone of the same repository, somewhere else on the same computer.
CLONE = projects.validated_here("/Users/dimitris/clones/aistack", REMOTE)


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


def _push(session_factory, joined, name="wizard", **archive):
    with session_factory.begin() as session:
        return skill_service.push(session, machine_id=joined.machine.machine_id,
                                  user_id=joined.user.user_id, name=name, origin=None,
                                  archive=skill_archive(name, **archive))


def _decide(session_factory, joined, name, enabled, project: bool, revision=None):
    """A decision in the global folder or in this repository's, as an install would make."""
    with session_factory.begin() as session:
        skill = visibility.required_my_skill(session, joined.user.user_id, name)
        if project:
            folder = project_service.folder_in(session, joined.user.user_id,
                                               joined.machine.machine_id, KEY, "aistack",
                                               Harness.CLAUDE_CODE)
            project_service.set_enabled(session, folder, skill.skill_id, enabled, revision)
        else:
            skill_service.set_enabled(session, joined.machine.machine_id, Harness.CLAUDE_CODE,
                                      skill.skill_id, enabled, revision)


def _sync(session_factory, joined, local, project: bool, here=HERE, repository=()):
    with session_factory.begin() as session:
        return sync_service.sync(session, joined.machine.machine_id, joined.user.user_id,
                                 local, here=here,
                                 project=KEY if project else None, repository=repository)


def _verdicts(report) -> tuple:
    return (tuple(report.install), tuple(report.update),
            tuple((question.name, question.desired, question.local, question.options)
                  for question in report.ask),
            report.backup, report.up_to_date)


EDITED = local_digests(files={"notes.md": "my local edit\n"})


@pytest.mark.parametrize("decision, on_disk", [
    (True, None), (True, "first"), (True, "latest"), (True, "edited"),
    (False, None), (False, "latest"), (False, "edited"),
    (None, "latest"), (None, "edited"),
])
def test_a_project_folder_is_reconciled_as_the_global_one_is(session_factory, dimitris,
                                                             desktop, decision, on_disk):
    """The table is one (ADR-0007): every desired state against every observed one gives the
    same verdict in a project folder as in the global folder. Pushed from the other computer,
    so this one's folders start with no decision at all."""
    _push(session_factory, desktop, "wizard")
    _push(session_factory, desktop, "wizard", description="Second revision.")
    _push(session_factory, desktop, "fresh")
    local = {"first": {"wizard": local_digests()},
             "latest": {"wizard": local_digests(description="Second revision.")},
             "edited": {"wizard": EDITED}, None: {}}[on_disk]
    local = {**local, "fresh": local_digests("fresh")} if decision is None else local
    reports = []
    for project in (False, True):
        if decision is not None:
            _decide(session_factory, dimitris, "wizard", decision, project, revision=1)
        reports.append(_verdicts(_sync(session_factory, dimitris, local, project)))

    assert reports[0] == reports[1]


def test_the_repositorys_own_folders_are_never_touched(session_factory, dimitris):
    """A name the repository holds is not installed, updated, asked about or backed up, and
    one enabled here is reported once."""
    _push(session_factory, dimitris, "conventions")
    _push(session_factory, dimitris, "wizard")
    _decide(session_factory, dimitris, "conventions", True, project=True)
    _decide(session_factory, dimitris, "wizard", True, project=True)

    report = _sync(session_factory, dimitris, {"drafted": local_digests("drafted")},
                   project=True, repository=["conventions", "release-steps"])

    assert [install.name for install in report.install] == ["wizard"]
    assert report.left_to_repository == ("conventions",)
    assert report.backup == ("drafted",)
    assert report.ask == () and report.update == ()


def test_two_clones_of_a_project_share_its_decisions(session_factory, dimitris):
    _push(session_factory, dimitris, "wizard")
    _decide(session_factory, dimitris, "wizard", True, project=True)

    first = _sync(session_factory, dimitris, {}, project=True)
    second = _sync(session_factory, dimitris, {}, project=True, here=CLONE)

    assert [install.name for install in first.install] == ["wizard"]
    assert [install.name for install in second.install] == ["wizard"]
    assert first.project == second.project == sync_service.ProjectHere(KEY, "aistack", True)


def test_a_first_sync_offers_what_the_other_computers_have_in_the_project(
        session_factory, dimitris, desktop):
    for name in ("on-desktop", "decided-here", "on-disk-here", "removed"):
        _push(session_factory, dimitris, name)
    with session_factory.begin() as session:
        folder = project_service.folder_in(session, dimitris.user.user_id,
                                           desktop.machine.machine_id, KEY, "aistack",
                                           Harness.AGENTS)
        for name in ("on-desktop", "decided-here", "on-disk-here", "removed"):
            skill = visibility.required_my_skill(session, dimitris.user.user_id, name)
            project_service.set_enabled(session, folder, skill.skill_id, True)
        skill_service.remove_from_my_skills(session, dimitris.user.user_id, "removed")
    _decide(session_factory, dimitris, "decided-here", False, project=True)

    first = _sync(session_factory, dimitris, {"on-disk-here": local_digests("on-disk-here")},
                  project=True)
    again = _sync(session_factory, dimitris, {}, project=True)

    assert first.first_sync and first.from_other_computers == ("on-desktop",)
    assert not again.first_sync and again.from_other_computers == ()


def _rows(session_factory) -> dict[str, int]:
    with session_factory() as session:
        return {table.name: session.scalar(select(func.count()).select_from(table))
                for table in Base.metadata.sorted_tables}


def test_naming_a_repository_that_is_not_managed_stores_nothing(session_factory, dimitris):
    before = _rows(session_factory)

    report = _sync(session_factory, dimitris, {}, project=False)

    assert report.project == sync_service.ProjectHere(KEY, "aistack", managed=False)
    assert _rows(session_factory) == {**before, "machine_harness": before["machine_harness"] + 1}


def test_a_project_sync_writes_its_folder_and_nothing_else(session_factory, dimitris):
    _push(session_factory, dimitris, "wizard")
    before = _rows(session_factory)

    report = _sync(session_factory, dimitris, {"wizard": EDITED, "new": local_digests("new")},
                   project=True)

    assert report.first_sync and report.refresh_sync_skill is False
    assert _rows(session_factory) == {**before, "project": before["project"] + 1,
                                      "machine_project": before["machine_project"] + 1}


def test_a_repository_without_a_remote_is_this_computers_alone(session_factory, dimitris):
    here = projects.validated_here("/Users/dimitris/scratch/notes", None)

    report = _sync(session_factory, dimitris, {}, project=False, here=here)

    assert report.project.key == projects.local_project_key(dimitris.machine.machine_id,
                                                            here.path)
    assert report.project.name == "notes"


@pytest.mark.parametrize("project, repository", [
    ("github.com/someone/else", ()),
    (None, ["conventions"]),
])
def test_a_project_folder_is_named_by_the_key_of_the_repository_here(session_factory, dimitris,
                                                                     project, repository):
    with pytest.raises(ValidationError):
        with session_factory.begin() as session:
            sync_service.sync(session, dimitris.machine.machine_id, dimitris.user.user_id,
                              {}, here=HERE, project=project, repository=repository)


def test_the_sync_skill_never_goes_into_a_project_folder(session_factory, dimitris):
    _push(session_factory, dimitris, "sync-aistack")
    _decide(session_factory, dimitris, "sync-aistack", True, project=True)

    report = _sync(session_factory, dimitris, {}, project=True)

    assert report.install == () and report.left_to_repository == ()
