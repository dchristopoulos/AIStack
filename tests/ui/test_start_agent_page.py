"""Start an agent from the page (ADR-0038): on the computer the page is on, the aistack:// link
and the command; on any other computer, only the command."""

from urllib.parse import parse_qs, urlsplit

import pytest

playwright_api = pytest.importorskip("playwright.async_api")
expect = playwright_api.expect

pytestmark = pytest.mark.anyio

KEY = "github.com/demo-team/demo-api"


async def _open_project(page, project="demo-api"):
    await page.get_by_role("navigation", name="Main").get_by_role("link", name=project).click()
    await expect(page.get_by_role("heading", name=project, level=1)).to_be_visible()


async def test_this_computer_opens_the_agent_by_its_link_with_the_skills_ticked(sign_in):
    page = (await sign_in("dimitris")).page
    await _open_project(page)

    await page.get_by_role("button", name="Start an agent…").click()
    dialog = page.get_by_role("dialog", name="Start an agent in demo-api")
    await expect(dialog.get_by_text("Opens a terminal on MacBook Pro M4 Pro")).to_be_visible()
    await expect(dialog.get_by_role("radio", name="Claude Code")).to_be_checked()
    await expect(dialog.get_by_role("radio", name="Codex")).to_be_visible()
    # The project's own skills start ticked, the ones for every project do not.
    await expect(dialog.get_by_text("For demo-api", exact=True)).to_be_visible()
    await expect(dialog.get_by_role("checkbox", name="demo-api-notes")).to_be_checked()
    await expect(dialog.get_by_text("Plugin skills stay on")).to_be_visible()
    await expect(dialog.get_by_role("button", name="Open a terminal")).to_have_count(0)
    await expect(dialog.get_by_role("button", name="Copy the command")).to_be_visible()

    await dialog.get_by_label("More skills, by name").fill("repo-own, Not A Name")
    await dialog.get_by_role("link", name="Open on this computer").click()
    await expect(dialog.get_by_text('"Not A Name" is not a skill name.')).to_be_visible()

    await dialog.get_by_label("More skills, by name").fill("repo-own")
    link = await dialog.get_by_role("link", name="Open on this computer").get_attribute("href")
    parts = urlsplit(link)
    assert (parts.scheme, parts.netloc) == ("aistack", "start")
    assert parse_qs(parts.query) == {"agent": ["claude-code"], "project": [KEY],
                                     "skills": ["demo-api-notes,repo-own"]}
    await dialog.get_by_role("link", name="Open on this computer").click()
    await expect(dialog).to_be_hidden()

    # Ticked as last time for this project, in this browser.
    await page.get_by_role("button", name="Start an agent…").click()
    dialog = page.get_by_role("dialog", name="Start an agent in demo-api")
    await expect(dialog.get_by_role("checkbox", name="demo-api-notes")).to_be_checked()
    await expect(dialog.get_by_label("More skills, by name")).to_have_value("repo-own")
    await dialog.get_by_role("checkbox", name="demo-api-notes").uncheck()
    await dialog.get_by_label("More skills, by name").fill("")
    await dialog.get_by_role("link", name="Open on this computer").click()
    await expect(dialog.get_by_text("Tick at least one skill.")).to_be_visible()


async def test_another_computer_shows_only_the_command(sign_in):
    page = (await sign_in("dimitris")).page
    await _open_project(page)

    await page.get_by_role("region", name="Work desktop").get_by_role(
        "button", name="Start an agent in demo-api on Work desktop…").click()
    dialog = page.get_by_role("dialog", name="Start an agent in demo-api")
    await expect(dialog.get_by_text("Run this in a terminal on Work desktop")).to_be_visible()
    await expect(dialog.get_by_role("link", name="Open on this computer")).to_have_count(0)
    await expect(dialog.get_by_role("button", name="Open a terminal")).to_have_count(0)
    await dialog.get_by_label("More skills, by name").fill("repo-own")
    await expect(dialog.get_by_label("Command to run on Work desktop")).to_have_value(
        f"aistack start --agent=claude-code --project={KEY} --skills=repo-own")


async def test_a_computer_s_page_starts_each_agent_in_one_of_its_projects(sign_in):
    page = (await sign_in("dimitris")).page
    await page.get_by_role("navigation", name="Main").get_by_role("link", name="MacBook Pro M4 Pro").click()

    await page.get_by_role("button", name="Start Codex in a project on MacBook Pro M4 Pro…").click()
    dialog = page.get_by_role("dialog", name="Start Codex on MacBook Pro M4 Pro")
    await expect(dialog.get_by_role("radio", name="Codex")).to_be_checked()
    await dialog.get_by_label("Project").select_option(label="demo-api")
    await expect(dialog.get_by_text("For every project", exact=True)).to_be_visible()
    await expect(dialog.get_by_role("checkbox", name="commit-messages")).not_to_be_checked()
    await dialog.get_by_role("checkbox", name="commit-messages").check()
    link = await dialog.get_by_role("link", name="Open on this computer").get_attribute("href")
    assert parse_qs(urlsplit(link).query) == {"agent": ["codex"], "project": [KEY],
                                              "skills": ["commit-messages"]}
