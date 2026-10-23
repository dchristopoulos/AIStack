"""A project's page (ADR-0026, ADR-0037): one place across computers, found by role and by the
words a person reads, and confirmed against /api/state."""

import pytest

playwright_api = pytest.importorskip("playwright.async_api")
expect = playwright_api.expect

pytestmark = pytest.mark.anyio

KEY = "github.com/demo-team/demo-api"
WEBSITE = "github.com/demo-team/demo-website"


def _nav(page):
    return page.get_by_role("navigation", name="Main")


async def _open_project(opened, project="demo-api"):
    await _nav(opened.page).get_by_role("link", name=project).click()
    await expect(opened.page.get_by_role("heading", name=project, level=1)).to_be_visible()


async def _add_to(page, place: str, item: str) -> None:
    await _nav(page).get_by_role("button", name=f"Add to {place}").click()
    await page.get_by_role("menu", name=f"Add to {place}").get_by_role(
        "menuitem", name=item).click()


def _placements(state, name) -> set[tuple]:
    skill = next(skill for skill in state["skills"] if skill["name"] == name)
    return {(placement["harness"], placement["project"]) for placement in skill["placements"]}


def _machines_with(state, name, project) -> list[str]:
    names = {machine["id"]: machine["name"] for machine in state["machines"]}
    skill = next(skill for skill in state["skills"] if skill["name"] == name)
    return sorted(names[placement["machine"]] for placement in skill["placements"]
                  if placement["project"] == project)


async def test_a_project_page_shows_each_computer_and_one_table_of_what_its_agents_read(sign_in):
    dimitris = await sign_in("dimitris")
    page = dimitris.page
    await _open_project(dimitris)

    await expect(page.get_by_text(KEY, exact=True)).to_be_visible()
    await expect(page.get_by_role("link", name="Team project of demo-team")).to_be_visible()
    macbook = page.get_by_role("region", name="MacBook Pro M4 Pro")
    await expect(macbook.get_by_text("/Users/dimitris/code/demo-api")).to_be_visible()
    await expect(macbook.get_by_text("This one")).to_be_visible()
    await expect(page.get_by_role("region", name="Work desktop").get_by_text(
        "/home/dimitris/code/demo-api")).to_be_visible()

    table = page.get_by_role("table", name="What your agents read in demo-api")
    await expect(table.get_by_text("Skills for every project")).to_be_visible()
    # Its last row is in the project's own group, under the skills for every project.
    own = table.get_by_role("row").filter(has_text="demo-api-notes").last
    # Something true on one computer only says so on its row.
    await expect(own.get_by_text("Only on MacBook Pro M4 Pro")).to_be_visible()
    assert dimitris.console_errors == []


async def test_skills_are_added_to_a_project_on_every_computer_from_its_page(sign_in):
    dimitris = await sign_in("dimitris")
    page = dimitris.page
    await _open_project(dimitris)

    await page.get_by_role("button", name="Add skills").click()
    dialog = page.get_by_role("dialog", name="Add skills to demo-api")
    await dialog.get_by_role("checkbox", name="sql-style").check()
    await dialog.get_by_role("button", name="Add").click()

    table = page.get_by_role("table", name="What your agents read in demo-api")
    await expect(table.get_by_role("checkbox", name="sql-style for Claude Code")).to_be_checked()
    assert _machines_with(await dimitris.state(), "sql-style", KEY) == ["MacBook Pro M4 Pro", "Work desktop"]
    # It is also in the global folder, which Claude Code uses first.
    await expect(table.get_by_role("row").filter(has_text="sql-style").last.get_by_text(
        "Also for every project; Claude Code uses that copy.")).to_be_visible()
    assert dimitris.console_errors == []


async def test_a_tick_on_one_computer_only_reaches_every_computer_once_clicked(sign_in):
    dimitris = await sign_in("dimitris")
    page = dimitris.page
    await _open_project(dimitris)
    tick = page.get_by_role("checkbox", name="demo-api-notes for Claude Code")
    await expect(tick).not_to_be_checked()

    await tick.click()

    await expect(tick).to_be_checked()
    assert _machines_with(await dimitris.state(), "demo-api-notes", KEY) == ["MacBook Pro M4 Pro", "Work desktop"]
    assert dimitris.console_errors == []


async def test_the_skill_panel_ticks_a_project_folder_by_its_agent_and_project(sign_in):
    dimitris = await sign_in("dimitris")
    page = dimitris.page

    await page.get_by_role("button", name="Details of demo-api-notes").click()
    panel = page.get_by_role("dialog", name="demo-api-notes")
    await expect(panel.get_by_role("checkbox", name="MacBook Pro M4 Pro / Claude Code in demo-api")
                 ).to_be_checked()
    await panel.get_by_role("checkbox", name="MacBook Pro M4 Pro / Claude Code in demo-api").uncheck()
    await panel.get_by_role("button", name="Save").click()

    await expect(panel).to_have_count(0)
    assert ("claude_code", KEY) not in _placements(await dimitris.state(), "demo-api-notes")
    assert dimitris.console_errors == []


async def test_stop_managing_takes_the_project_off_one_computer(sign_in):
    dimitris = await sign_in("dimitris")
    page = dimitris.page
    await _open_project(dimitris)

    await page.get_by_role("button", name="Stop managing demo-api on MacBook Pro M4 Pro…").click()
    confirm = page.get_by_role("dialog", name="Stop managing demo-api on MacBook Pro M4 Pro?")
    await expect(confirm.get_by_text("still hidden from git")).to_be_visible()
    await confirm.get_by_role("button", name="Stop managing").click()

    await expect(page.get_by_text("Stopped managing demo-api on MacBook Pro M4 Pro.")).to_be_visible()
    await expect(page.get_by_role("region", name="MacBook Pro M4 Pro")).to_have_count(0)
    await expect(page.get_by_role("region", name="Work desktop")).to_be_visible()
    macbook = next(machine for machine in (await dimitris.state())["machines"]
                   if machine["name"] == "MacBook Pro M4 Pro")
    assert [project["key"] for project in macbook["projects"]] == [WEBSITE]
    assert dimitris.console_errors == []


async def test_a_project_added_to_another_computer_waits_for_its_first_sync(sign_in):
    dimitris = await sign_in("dimitris")
    page = dimitris.page

    await _add_to(page, "demo-website", "Another computer…")
    dialog = page.get_by_role("dialog", name="Add demo-website to a computer")
    await dialog.get_by_role("radio", name="Work desktop, Claude Code").check()
    await dialog.get_by_role("button", name="Add").click()

    await expect(page.get_by_role("heading", name="demo-website", level=1)).to_be_visible()
    desktop_card = page.get_by_role("region", name="Work desktop")
    await expect(desktop_card.get_by_text("Claude Code. Not synced here yet")).to_be_visible()
    desktop = next(machine for machine in (await dimitris.state())["machines"]
                   if machine["name"] == "Work desktop")
    website = next(project for project in desktop["projects"] if project["key"] == WEBSITE)
    assert website["folders"] == [{"harness": "claude_code", "path": None, "last_synced_on": None,
                                   "repository_skills": []}]
    assert dimitris.console_errors == []


async def test_a_computer_s_plus_offers_a_project_and_a_new_repository(sign_in):
    dimitris = await sign_in("dimitris")
    page = dimitris.page

    await _add_to(page, "Work desktop", "A project…")
    dialog = page.get_by_role("dialog", name="Add a project to Work desktop")
    await expect(dialog.get_by_label("What to say inside the repository")).to_have_value(
        "add this project to aistack")
    await dialog.get_by_role("radio", name="demo-website for Claude Code").check()
    await dialog.get_by_role("button", name="Add").click()

    await expect(page.get_by_role("heading", name="demo-website", level=1)).to_be_visible()
    await _add_to(page, "Projects", "A folder on this computer…")
    await expect(page.get_by_role("dialog", name="Add a project").get_by_role(
        "button", name="Look inside")).to_be_visible()
    assert dimitris.console_errors == []


async def test_a_project_page_fits_a_phone(sign_in):
    dimitris = await sign_in("dimitris", viewport=(390, 844))
    page = dimitris.page

    await page.goto(f"{dimitris.base_url}/app#/p/github.com%2Fdemo-team%2Fdemo-api")
    await expect(page.get_by_role("heading", name="demo-api", level=1)).to_be_visible()
    # On a phone each tick says which agent it is for.
    await expect(page.get_by_role("checkbox", name="demo-api-notes for Claude Code")
                 ).to_be_visible()

    assert await page.evaluate("document.documentElement.scrollWidth - window.innerWidth") <= 0


@pytest.mark.parametrize("viewport", [(1280, 900), (390, 844)])
async def test_a_sidebar_plus_menu_opens_inside_the_sidebar(sign_in, viewport):
    dimitris = await sign_in("dimitris", viewport=viewport)
    page = dimitris.page
    if viewport[0] < 760:
        await page.get_by_role("button", name="Open navigation").click()

    # The sidebar scrolls and clips what runs past it, so the whole menu must sit inside it.
    for place in ("Projects", "Work desktop"):
        await _nav(page).get_by_role("button", name=f"Add to {place}").click()
        menu = page.get_by_role("menu", name=f"Add to {place}")
        await expect(menu).to_be_visible()
        box, sidebar = await menu.bounding_box(), await _nav(page).bounding_box()
        assert sidebar["x"] <= box["x"] and box["x"] + box["width"] <= sidebar["x"] + sidebar["width"]
        await page.keyboard.press("Escape")
    assert dimitris.console_errors == []
