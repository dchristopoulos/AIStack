"""A computer's project folders on the page (ADR-0026), found by role and by the words a
person reads, and confirmed against /api/state."""

import pytest

playwright_api = pytest.importorskip("playwright.async_api")
expect = playwright_api.expect

pytestmark = pytest.mark.anyio

KEY = "github.com/dchristopoulos/aistack"


def _tree(page):
    return page.get_by_role("navigation", name="Main")


async def _open_project(opened, computer="macbook", agent="Claude Code", project="aistack"):
    await _tree(opened.page).get_by_role("link", name=f"{computer} / {agent}, project {project}").click()
    await expect(opened.page.get_by_role(
        "heading", name=f"{agent} in {project} on {computer}", level=1)).to_be_visible()


def _placements(state, name) -> set[tuple]:
    skill = next(skill for skill in state["skills"] if skill["name"] == name)
    return {(placement["harness"], placement["project"]) for placement in skill["placements"]}


async def test_skills_are_added_to_a_project_folder_from_its_page(sign_in):
    dimitris = await sign_in("dimitris")
    page = dimitris.page
    await _open_project(dimitris)
    await expect(page.get_by_role("table", name="Skills in Claude Code in aistack on macbook")
                 .get_by_text("aistack-api-notes")).to_be_visible()

    await page.get_by_role("button", name="Add skills").first.click()
    dialog = page.get_by_role("dialog", name="Add to Claude Code in aistack on macbook")
    await dialog.get_by_role("checkbox", name="sql-style").check()
    await dialog.get_by_role("button", name="Add").click()

    await expect(page.get_by_role("table", name="Skills in Claude Code in aistack on macbook")
                 .get_by_text("sql-style")).to_be_visible()
    assert ("claude_code", KEY) in _placements(await dimitris.state(), "sql-style")
    # It is also in the global folder, which Claude Code uses first.
    await expect(page.get_by_text("Claude Code uses the global copy.")).to_be_visible()
    assert dimitris.console_errors == []


async def test_the_skill_panel_ticks_a_project_folder_by_its_agent_and_project(sign_in):
    dimitris = await sign_in("dimitris")
    page = dimitris.page

    await page.get_by_role("button", name="Details of aistack-api-notes").click()
    panel = page.get_by_role("dialog", name="aistack-api-notes")
    await expect(panel.get_by_role("checkbox", name="macbook / Claude Code in aistack")
                 ).to_be_checked()
    await panel.get_by_role("checkbox", name="macbook / Claude Code in aistack").uncheck()
    await panel.get_by_role("button", name="Save").click()

    await expect(panel).to_have_count(0)
    assert ("claude_code", KEY) not in _placements(await dimitris.state(), "aistack-api-notes")
    assert dimitris.console_errors == []


async def test_stop_managing_takes_the_project_off_the_computer(sign_in):
    dimitris = await sign_in("dimitris")
    page = dimitris.page
    await _open_project(dimitris)

    await page.get_by_role("button", name="Stop managing aistack…").click()
    confirm = page.get_by_role("dialog", name="Stop managing aistack on macbook?")
    await expect(confirm.get_by_text("still hidden from git")).to_be_visible()
    await confirm.get_by_role("button", name="Stop managing").click()

    await expect(page.get_by_role("heading", name="Claude Code on macbook", level=1)).to_be_visible()
    await expect(_tree(page).get_by_role("link", name="project aistack")).to_have_count(0)
    macbook = next(machine for machine in (await dimitris.state())["machines"]
                   if machine["name"] == "macbook")
    assert macbook["projects"] == []
    assert dimitris.console_errors == []


async def test_a_project_added_to_another_computer_waits_for_its_first_sync(sign_in):
    dimitris = await sign_in("dimitris")
    page = dimitris.page

    await _tree(page).get_by_role("button", name="Add a project to desktop").click()
    dialog = page.get_by_role("dialog", name="Add a project to desktop")
    await expect(dialog.get_by_label("What to say inside the repository")).to_have_value(
        "add this project to aistack")
    await dialog.get_by_role("radio", name="aistack for Claude Code").check()
    await dialog.get_by_role("button", name="Add").click()

    await expect(page.get_by_role("heading", name="Claude Code in aistack on desktop", level=1)
                 ).to_be_visible()
    await expect(page.get_by_role("heading", name="Not synced on desktop yet")).to_be_visible()
    await expect(page.get_by_text("Nothing in Claude Code in aistack on desktop yet")).to_be_visible()
    desktop = next(machine for machine in (await dimitris.state())["machines"]
                   if machine["name"] == "desktop")
    assert desktop["projects"][0]["folders"] == [
        {"harness": "claude_code", "path": None, "last_synced_on": None}]
    assert dimitris.console_errors == []


async def test_a_project_page_fits_a_phone(sign_in):
    dimitris = await sign_in("dimitris", viewport=(390, 844))
    page = dimitris.page
    macbook = next(machine["id"] for machine in (await dimitris.state())["machines"]
                   if machine["name"] == "macbook")

    await page.goto(f"{dimitris.base_url}/app#/f/{macbook}/claude_code/"
                    "github.com%2Fdchristopoulos%2Faistack")
    await expect(page.get_by_role("heading", name="Claude Code in aistack on macbook", level=1)
                 ).to_be_visible()

    assert await page.evaluate("document.documentElement.scrollWidth - window.innerWidth") <= 0
