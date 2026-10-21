"""A project's Markdown files and edits made on the page (ADR-0036), on both databases."""

import uuid

import pytest
from sqlalchemy import select

from aistack.commons.exceptions import Conflict, InvalidTicket, NotFound, ValidationError
from aistack.db.engine import build_session_factory
from aistack.db.models.harness import Harness
from aistack.db.models.machine_project import MachineProject
from aistack.db.models.project import Project
from aistack.db.models.project_file import ProjectFile, ProjectFileEdit
from aistack.services import onboarding_service, project_file_service, project_service
from aistack.services.content_hash import text_hash
from aistack.services.transfer_ticket import (
    ProjectFileEditTicket,
    ProjectFileUploadTicket,
    token_prefix,
)

KEY = "github.com/acme/shop"
TEXT = "# Shop\n"
LISTING = [("AGENTS.md", 7), ("CLAUDE.md", 7), ("GEMINI.md", 7), ("README.md", 7),
           (".cursor/rules/style.mdc", 7)]
SECRET = "ghp_" + "a" * 36


@pytest.fixture(name="session_factory")
def session_factory_fixture(portable_engine):
    return build_session_factory(portable_engine)


def _call(session_factory, function, *arguments, **options):
    with session_factory.begin() as session:
        return function(session, *arguments, **options)


def _person(session_factory, username):
    with session_factory.begin() as session:
        joined = onboarding_service.join(session, username, "laptop", "LINUX")
        return joined.user.user_id, joined.machine


@pytest.fixture(name="shop")
def shop_fixture(session_factory):
    """dimitris's project, managed on his laptop, its files listed and AGENTS.md read."""
    user_id, machine = _person(session_factory, "dimitris")
    with session_factory.begin() as session:
        project_service.register_folder(session, user_id, machine.machine_id, KEY, "shop",
                                        Harness.CLAUDE_CODE, "/code/shop")
        project = session.scalar(select(Project))
        project_file_service.record_listing(session, project, LISTING)
        row = session.scalar(select(ProjectFile).where(ProjectFile.path == "AGENTS.md"))
        row.text, row.content_hash = TEXT, text_hash(TEXT)
    return user_id, machine


def _rows(session_factory):
    with session_factory() as session:
        return {row.path: (row.ticked, row.agent and row.agent.value)
                for row in session.scalars(select(ProjectFile))}


@pytest.mark.parametrize("path", ["../AGENTS.md", "/etc/hosts", "docs\\a.md", "docs//a.md",
                                  "./a.md", "a.md\n", "", None, "docs/../../a.md"])
def test_a_listing_names_only_paths_inside_the_repository(path):
    with pytest.raises(ValidationError):
        project_file_service.validated_listing([{"path": path, "size": 1}])


@pytest.mark.parametrize("entry", [{"path": "src/app.py", "size": 1},
                                   {"path": "a.md", "size": -1}, {"path": "a.md", "size": True},
                                   {"path": "a.md"}])
def test_a_listing_holds_markdown_and_agent_files_with_their_sizes(entry):
    with pytest.raises(ValidationError):
        project_file_service.validated_listing([entry])


def test_a_listing_is_bounded_and_names_each_file_once():
    with pytest.raises(ValidationError, match="twice"):
        project_file_service.validated_listing([{"path": "a.md", "size": 1}] * 2)
    with pytest.raises(ValidationError, match="limit"):
        project_file_service.validated_listing(
            [{"path": f"{n}.md", "size": 1} for n in range(2001)])


def test_agent_files_are_ticked_and_a_changed_tick_stays(session_factory, shop):
    user_id, _ = shop
    assert _rows(session_factory) == {
        "AGENTS.md": (True, "codex"), "CLAUDE.md": (True, "claude_code"),
        "GEMINI.md": (True, "gemini_cli"), "README.md": (False, None),
        ".cursor/rules/style.mdc": (True, "cursor")}

    _call(session_factory, project_file_service.set_ticked, user_id, KEY, "README.md", True)
    _call(session_factory, project_file_service.set_ticked, user_id, KEY, "CLAUDE.md", False)
    with session_factory.begin() as session:
        project_file_service.record_listing(session, session.scalar(select(Project)),
                                            LISTING[:4])

    assert _rows(session_factory) == {
        "AGENTS.md": (True, "codex"), "CLAUDE.md": (False, "claude_code"),
        "GEMINI.md": (True, "gemini_cli"), "README.md": (True, None)}


def test_another_persons_project_is_answered_as_an_unknown_one(session_factory, shop):
    maria, laptop = _person(session_factory, "maria")
    for function, arguments in (
            (project_file_service.set_ticked, ("AGENTS.md", True)),
            (project_file_service.set_turned_off, ("AGENTS.md", True)),
            (project_file_service.save_edit, ("AGENTS.md", "x", text_hash(TEXT),
                                              str(laptop.machine_id))),
            (project_file_service.commit, ("AGENTS.md", "note"))):
        with pytest.raises(NotFound, match="You have no project"):
            _call(session_factory, function, maria, KEY, *arguments)


def test_only_a_file_an_agent_can_turn_off_is_turned_off(session_factory, shop):
    user_id, _ = shop
    _call(session_factory, project_file_service.set_turned_off, user_id, KEY, "CLAUDE.md", True)
    for path, reason in (("GEMINI.md", "does not manage"), ("README.md", "No coding agent")):
        with pytest.raises(ValidationError, match=reason):
            _call(session_factory, project_file_service.set_turned_off, user_id, KEY, path, True)
    with session_factory() as session:
        assert session.scalar(select(ProjectFile.turned_off)
                              .where(ProjectFile.path == "CLAUDE.md")) is True


def test_an_edit_starts_from_the_text_shown_and_goes_to_a_computer_with_the_project(
        session_factory, shop):
    user_id, laptop = shop
    with session_factory.begin() as session:
        other = onboarding_service.add_machine(session, user_id, "desktop", "LINUX",
                                               added_by=laptop.machine_id)
    edit = project_file_service.save_edit
    with pytest.raises(Conflict, match="changed since you opened it"):
        _call(session_factory, edit, user_id, KEY, "AGENTS.md", "x", text_hash("older"),
              str(laptop.machine_id))
    with pytest.raises(ValidationError, match="does not have this project"):
        _call(session_factory, edit, user_id, KEY, "AGENTS.md", "x", text_hash(TEXT),
              str(other.machine.machine_id))
    maria, hers = _person(session_factory, "maria")
    with pytest.raises(NotFound, match="no computer"):
        _call(session_factory, edit, user_id, KEY, "AGENTS.md", "x", text_hash(TEXT),
              str(hers.machine_id))
    warned = _call(session_factory, edit, user_id, KEY, "AGENTS.md", f"x\n{SECRET}\n",
                   text_hash(TEXT), str(laptop.machine_id))
    assert (warned.saved, warned.credential_lines) == (False, [2])

    _call(session_factory, edit, user_id, KEY, "AGENTS.md", "first", text_hash(TEXT),
          str(laptop.machine_id))
    _call(session_factory, edit, user_id, KEY, "AGENTS.md", "second", text_hash(TEXT),
          str(laptop.machine_id))
    with session_factory() as session:
        edits = list(session.scalars(select(ProjectFileEdit)
                                     .order_by(ProjectFileEdit.created_on)))
    # A newer edit replaces one not yet shared.
    assert [(e.text, e.cancelled_on is None) for e in edits] == [("first", False),
                                                                  ("second", True)]


def test_only_a_written_edit_is_committed_with_a_note(session_factory, shop):
    user_id, laptop = shop
    _call(session_factory, project_file_service.save_edit, user_id, KEY, "AGENTS.md", "new",
          text_hash(TEXT), str(laptop.machine_id))
    with pytest.raises(Conflict, match="nothing to commit"):
        _call(session_factory, project_file_service.commit, user_id, KEY, "AGENTS.md", "Why")
    for note in ("", "  ", "a\x00b", "x" * 4097):
        with pytest.raises(ValidationError):
            project_file_service.validated_note(note)


def _ticket(session_factory, machine, kind, target_id):
    with session_factory() as session:
        prefix = token_prefix(session.get(type(machine), machine.machine_id).token_hash)
    if kind == "upload":
        return ProjectFileUploadTicket(machine.machine_id, prefix, target_id)
    return ProjectFileEditTicket(machine.machine_id, prefix, target_id)


def test_a_transfer_url_is_checked_again_when_it_is_used(session_factory, shop):
    user_id, laptop = shop
    with session_factory() as session:
        agents = session.scalar(select(ProjectFile.project_file_id)
                                .where(ProjectFile.path == "AGENTS.md"))
        readme = session.scalar(select(ProjectFile.project_file_id)
                                .where(ProjectFile.path == "README.md"))
    store = project_file_service.store_snapshot
    # A file nobody ticked is never read again.
    with pytest.raises(NotFound):
        _call(session_factory, store, _ticket(session_factory, laptop, "upload", readme), "x")
    stored = _call(session_factory, store, _ticket(session_factory, laptop, "upload", agents),
                   f"{SECRET}\n")
    assert (stored.saved, stored.credential_lines) == (False, [1])

    _call(session_factory, project_file_service.save_edit, user_id, KEY, "AGENTS.md", "new",
          text_hash(TEXT), str(laptop.machine_id))
    with session_factory() as session:
        edit_id = session.scalar(select(ProjectFileEdit.project_file_edit_id))
    # Another person's computer cannot read or settle the edit, nor another of the person's
    # own computers with the project: the edit was made for the laptop's working copy.
    _, hers = _person(session_factory, "maria")
    with session_factory.begin() as session:
        desktop = onboarding_service.add_machine(session, user_id, "desktop", "LINUX",
                                                 added_by=laptop.machine_id).machine
        project_service.register_folder(session, user_id, desktop.machine_id, KEY, "shop",
                                        Harness.CLAUDE_CODE, "/code/shop")
    for other in (hers, desktop):
        with pytest.raises(NotFound):
            _call(session_factory, project_file_service.edit_text,
                  _ticket(session_factory, other, "edit", edit_id))
    # A shared outcome waits for the note, and its address is https.
    edit_ticket = _ticket(session_factory, laptop, "edit", edit_id)
    with pytest.raises(Conflict):
        _call(session_factory, project_file_service.record_outcome, edit_ticket,
              {"outcome": "shared", "pull_request_url": "https://example.com/pr/1"})
    with pytest.raises(ValidationError):
        _call(session_factory, project_file_service.record_outcome, edit_ticket,
              {"outcome": "written", "pull_request_url": "javascript:alert(1)"})

    # The computer stops managing the project: its URLs stop working.
    with session_factory.begin() as session:
        session.query(MachineProject).delete()
    with pytest.raises(NotFound):
        _call(session_factory, store, _ticket(session_factory, laptop, "upload", agents), "x")
    with pytest.raises(NotFound):
        _call(session_factory, project_file_service.edit_text, edit_ticket)
    # A token rotated since the URL was minted voids it.
    with pytest.raises(InvalidTicket):
        _call(session_factory, store,
              ProjectFileUploadTicket(laptop.machine_id, "0" * 16, uuid.uuid4()), "x")
