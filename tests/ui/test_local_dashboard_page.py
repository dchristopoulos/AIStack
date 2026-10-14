import pytest
from playwright.async_api import expect

from tests.local_dashboard import local_dashboard

pytestmark = pytest.mark.anyio


async def test_the_local_dashboard_shows_the_library_and_nothing_a_team_needs(browser, tmp_path,
                                                                              sqlite_url):
    """`aistack dashboard`: the same page, with no way to start a team that has no server."""
    async with local_dashboard(tmp_path, sqlite_url) as (base, link):
        context = await browser.new_context()
        page = await context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))

        await page.goto(link)
        await page.get_by_role("heading", name="Library", level=1).wait_for()
        await expect(page.get_by_role("row").filter(has_text="wizard")).to_be_visible()
        await expect(page.get_by_role("button", name="Add a team")).to_have_count(0)
        await expect(page.get_by_role("navigation", name="Spaces")).not_to_contain_text("null")

        await page.get_by_role("button", name="More actions for wizard").click()
        await expect(page.get_by_role("menuitem", name="Remove from library")).to_be_visible()
        await expect(page.get_by_role("menuitem", name="Share with a team…")).to_have_count(0)

        state = await (await page.request.get(f"{base}/api/state")).json()
        await context.close()

    assert state["server"] is False
    assert errors == []


async def test_the_page_says_where_the_library_lives(browser, tmp_path, sqlite_url):
    async with local_dashboard(tmp_path, sqlite_url) as (_, link):
        context = await browser.new_context()
        page = await context.new_page()
        await page.goto(link)
        await page.get_by_role("navigation", name="Main").get_by_role(
            "link", name="Where it lives").click()

        await expect(page.get_by_role("heading", name="Where your Library lives", level=1)
                     ).to_be_visible()
        await expect(page.get_by_role("heading", name="Only this computer", level=2)
                     ).to_be_visible()
        await expect(page.get_by_text("Only this computer (now)")).to_be_visible()
        await context.close()
