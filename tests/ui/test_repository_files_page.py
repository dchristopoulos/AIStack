"""A project's own files on the page (ADR-0036, ADR-0038): adding a project by its folder, and
in the side panel turning a file off, editing it for one computer and committing the edit.
Found by role and by the words a person reads, and confirmed against /api/state."""

import uuid
from urllib.parse import unquote

import pytest
from sqlalchemy import select

from aistack.bootstrap.context import application_context
from aistack.db.models.harness import Harness
from aistack.db.models.machine import Machine
from aistack.db.models.project import Project
from aistack.db.models.project_file import ProjectFile, ProjectFileEdit
from aistack.db.models.timestamps import utc_now
from aistack.services import project_file_service, project_service

playwright_api = pytest.importorskip("playwright.async_api")
expect = playwright_api.expect

pytestmark = pytest.mark.anyio

KEY = "github.com/demo-team/demo-api"
SHOP = "github.com/dimitris/shop"
MACBOOK = "MacBook Pro M4 Pro"


def _file(state, path, project=KEY):
    return next(f for f in state["project_files"] if f["project"] == project and f["path"] == path)


def _program_added_shop(user_machine: str) -> None:
    """What `aistack project add ~/code/shop` leaves on the server, run on the MacBook."""
    with application_context.get_session_factory().begin() as session:
        machine_id = uuid.UUID(user_machine)
        user_id = session.get(Machine, machine_id).user_id
        registered = project_service.register_folder(session, user_id, machine_id, SHOP, "shop",
                                                     Harness.CLAUDE_CODE,
                                                     "/Users/dimitris/code/shop")
        registered.folder.repository_skills = "shop-release"
        project = session.scalar(select(Project).where(Project.key == SHOP))
        project_file_service.record_listing(session, project, [("AGENTS.md", 40),
                                                               ("README.md", 900)])


async def test_a_folder_on_this_computer_is_added_with_the_list_its_command_sends(sign_in):
    dimitris = await sign_in("dimitris")
    page = dimitris.page
    await page.get_by_role("button", name="Add to Projects").click()
    await page.get_by_role("menu", name="Add to Projects").get_by_role(
        "menuitem", name="A folder on this computer…").click()

    dialog = page.get_by_role("dialog", name="Add a project")
    await dialog.get_by_label(f"Folder on {MACBOOK}").fill("/Users/dimitris/code/shop")
    await dialog.get_by_role("button", name="Look inside").click()
    await expect(dialog.get_by_label(f"Command to run on {MACBOOK}")).to_have_value(
        "aistack project add /Users/dimitris/code/shop")
    link = await dialog.get_by_role("link", name="Open a terminal here").get_attribute("href")
    assert unquote(link) == "aistack://project-add?folder=/Users/dimitris/code/shop"
    await expect(dialog.get_by_text(f"Waiting for the list from {MACBOOK}")).to_be_visible()

    _program_added_shop((await dimitris.state())["this_computer"])
    await expect(dialog.get_by_text(f"Found {SHOP}.")).to_be_visible(timeout=10_000)
    await expect(dialog.get_by_role("checkbox", name="AGENTS.md")).to_be_checked()
    await expect(dialog.get_by_role("checkbox", name="README.md")).not_to_be_checked()
    await expect(dialog.get_by_role("region", name="Skills in this project").get_by_text(
        "shop-release")).to_be_visible()
    await dialog.get_by_role("checkbox", name="README.md").check()
    await dialog.get_by_role("button", name="Add shop").click()

    await expect(page.get_by_role("heading", name="shop", level=1)).to_be_visible()
    state = await dimitris.state()
    assert _file(state, "README.md", SHOP)["ticked"] is True
    assert _file(state, "AGENTS.md", SHOP)["ticked"] is True


async def _open_file(page, path):
    await page.get_by_role("navigation", name="Main").get_by_role("link", name="demo-api").click()
    table = page.get_by_role("table", name="What your agents read in demo-api")
    await table.get_by_role("button", name=f"Open {path}").click()
    return page.get_by_role("dialog", name=path)


async def test_a_repository_file_is_turned_off_for_one_person_where_an_agent_can(sign_in):
    dimitris = await sign_in("dimitris")
    page = dimitris.page
    panel = await _open_file(page, "GEMINI.md")
    switch = panel.get_by_role("switch", name="Turn this file off for me")
    await expect(switch).to_have_attribute("aria-disabled", "true")
    await expect(panel.get_by_text("AIStack does not manage this agent's settings yet.")
                 ).to_be_visible()
    await page.keyboard.press("Escape")

    panel = await _open_file(page, "CLAUDE.md")
    await panel.get_by_role("switch", name="Turn this file off for me").click()
    await expect(page.get_by_text("Turned CLAUDE.md off for you.")).to_be_visible()
    assert _file(await dimitris.state(), "CLAUDE.md")["turned_off"] is True


async def test_an_edit_waits_for_its_computer_then_is_committed_with_a_note(sign_in):
    dimitris = await sign_in("dimitris")
    page = dimitris.page
    panel = await _open_file(page, "AGENTS.md")
    await expect(panel.get_by_text("Money is an integer number of cents")).to_be_visible()
    await expect(panel.get_by_role("button", name="Commit…")).to_have_count(0)
    await panel.get_by_role("button", name="Edit").click()

    editor = page.get_by_role("dialog", name="Edit AGENTS.md")
    await expect(editor.get_by_label("Write it on")).to_have_value(
        (await dimitris.state())["this_computer"])
    text = editor.get_by_label("Text")
    await text.fill(await text.input_value() + "- Refunds go through payments/refunds.py.\n")
    await editor.get_by_role("button", name="Save").click()
    await expect(page.get_by_text(f"Saved. {MACBOOK} writes it into its working copy")
                 ).to_be_visible()
    edit = _file(await dimitris.state(), "AGENTS.md")["edit"]
    assert edit["text"].endswith("refunds.py.\n") and edit["written_on"] is None
    table = page.get_by_role("table", name="What your agents read in demo-api")
    await expect(table.get_by_text(f"Waiting for {MACBOOK} to write your edit")).to_be_visible()

    # The MacBook's next sync writes it into its working copy, then reads the file again.
    with application_context.get_session_factory().begin() as session:
        written = session.scalar(select(ProjectFileEdit))
        written.written_on = utc_now()
        row = session.get(ProjectFile, written.project_file_id)
        row.text, row.content_hash = written.text, written.content_hash
    await page.reload()
    panel = await _open_file(page, "AGENTS.md")
    await expect(panel.get_by_text(f"Changed on {MACBOOK}, not committed yet")).to_be_visible()
    added = "+- Refunds go through payments/refunds.py."
    await expect(panel.get_by_role("region", name="What your edit changes").get_by_text(added)
                 ).to_be_visible()
    await panel.get_by_role("button", name="Commit…").click()

    share = page.get_by_role("dialog", name="Share your change to AGENTS.md")
    await expect(share.get_by_role("region", name="What your edit changes").get_by_text(added)
                 ).to_be_visible()
    await expect(share.get_by_text(f"Opens a pull request on {KEY} with only this file."))\
        .to_be_visible()
    await share.get_by_role("button", name="Open a pull request").click()
    await expect(share.get_by_text("Say what this change is about.")).to_be_visible()
    await share.get_by_label("What is this change about?").fill(
        "Refunds go through one module\n\nAgents stop writing refund queries by hand.")
    await share.get_by_role("button", name="Open a pull request").click()
    await expect(page.get_by_text(f"{MACBOOK} pushes a branch and opens the pull request")
                 ).to_be_visible()
    assert _file(await dimitris.state(), "AGENTS.md")["edit"]["note"].startswith(
        "Refunds go through one module")

    # The MacBook's next sync shares it: shown shared, with its pull request, until settled.
    with application_context.get_session_factory().begin() as session:
        shared = session.scalar(select(ProjectFileEdit).where(ProjectFileEdit.note.is_not(None)))
        shared.shared_on = utc_now()
        shared.pull_request_url = "https://github.com/demo-team/demo-api/pull/12"
    await page.reload()
    await expect(table.get_by_text("Shared as a pull request")).to_be_visible()
    panel = await _open_file(page, "AGENTS.md")
    await expect(panel.get_by_role("link", name="Open the pull request")).to_have_attribute(
        "href", "https://github.com/demo-team/demo-api/pull/12")
    await expect(panel.get_by_role("button", name="Commit…")).to_have_count(0)
    assert _file(await dimitris.state(), "AGENTS.md")["edit"]["branch"].startswith(
        "aistack/agents-md-")
