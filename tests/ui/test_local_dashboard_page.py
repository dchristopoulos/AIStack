import pytest
from playwright.async_api import expect

from aistack.bundled import RUN_COMMAND
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
        await expect(page.get_by_role("navigation", name="Spaces")).to_be_hidden()
        # A full name is for teammates, and local mode has none.
        await page.goto(f"{link.split('/app/')[0]}/app#/settings")
        await expect(page.get_by_role("heading", name="Settings", level=1)).to_be_visible()
        await expect(page.get_by_label("Full name")).to_have_count(0)
        await page.goto(f"{link.split('/app/')[0]}/app#/library")

        await page.get_by_role("button", name="Details of wizard").click()
        details = page.get_by_role("dialog", name="wizard")
        await expect(details.get_by_role("button", name="Remove from library…")).to_be_visible()
        await expect(details.get_by_role("button", name="Share with a team…")).to_have_count(0)

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
        await expect(page.get_by_text("Connected: this page just read")).to_be_visible()

        await page.get_by_role("button", name="Move to a private GitHub repository").click()
        await expect(page.get_by_role("dialog").get_by_role("textbox", name="What to say")
                     ).to_have_value("move my AIStack Library to a private GitHub repository")
        await context.close()


async def test_adding_a_computer_says_this_computer_cannot_be_reached(browser, tmp_path,
                                                                     sqlite_url):
    async with local_dashboard(tmp_path, sqlite_url) as (_, link):
        context = await browser.new_context()
        page = await context.new_page()
        await page.goto(link)

        await page.get_by_role("button", name="Add a computer").click()

        dialog = page.get_by_role("dialog", name="Add a computer")
        await expect(dialog.get_by_text("another computer cannot reach it")).to_be_visible()
        await expect(dialog.get_by_text("add my Windows PC")).to_have_count(0)
        await dialog.get_by_role("link", name="See where it can move").click()
        await expect(page.get_by_role("heading", name="Where your Library lives", level=1)
                     ).to_be_visible()
        await context.close()


@pytest.mark.parametrize(("library", "sentence"), [
    ({"kind": "github", "repository": "maria/aistack-library"},
     "My Library is in the private GitHub repository maria/aistack-library."),
    ({"kind": "postgresql", "provider": "Neon", "host": "ep-calm.neon.tech"},
     "My Library is in my Neon database at ep-calm.neon.tech."),
])
async def test_adding_a_computer_names_the_shared_library(browser, tmp_path, sqlite_url,
                                                          library, sentence):
    """What the other computer is told depends on where the Library lives, which the page reads
    from /api/state; the answer is rewritten here because the test Library is a SQLite file."""
    async with local_dashboard(tmp_path, sqlite_url) as (base, link):
        context = await browser.new_context()
        page = await context.new_page()

        async def elsewhere(route):
            response = await route.fetch()
            await route.fulfill(response=response, json=await response.json() | {"library": library})

        await page.route(f"{base}/api/state", elsewhere)
        await page.goto(link)
        await page.get_by_role("button", name="Add a computer").click()

        pasted = page.get_by_role("dialog").get_by_role("textbox", name="What to paste")
        await expect(pasted).to_have_value(
            f"Set up AIStack: run `{RUN_COMMAND} setup` and follow what it prints. {sentence}")
        await context.close()


@pytest.mark.parametrize(("destination", "after"), [
    ("Move to only this computer", "Your other computers can no longer reach it."),
    ("Move to a free PostgreSQL database", "give it the same database address"),
])
async def test_each_move_says_what_it_means_for_the_other_computers(browser, tmp_path,
                                                                    sqlite_url, destination,
                                                                    after):
    async with local_dashboard(tmp_path, sqlite_url) as (base, link):
        context = await browser.new_context()
        page = await context.new_page()

        async def on_github(route):
            response = await route.fetch()
            await route.fulfill(response=response, json=await response.json() | {
                "library": {"kind": "github", "repository": "maria/aistack-library"}})

        await page.route(f"{base}/api/state", on_github)
        await page.goto(link)
        await page.get_by_role("navigation", name="Main").get_by_role(
            "link", name="Where it lives").click()
        await page.get_by_role("button", name=destination).click()

        dialog = page.get_by_role("dialog")
        await expect(dialog.get_by_text("moves the Library with its history")).to_be_visible()
        await expect(dialog.get_by_text(after)).to_be_visible()
        await expect(dialog.get_by_text("other computers then need")).to_have_count(0)
        await context.close()
