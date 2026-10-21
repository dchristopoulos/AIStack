import re

import pytest
from playwright.async_api import expect

from aistack.bootstrap.context import application_context
from aistack.bundled import RUN_COMMAND
from aistack.services import rule_service
from tests.local_dashboard import local_dashboard

pytestmark = pytest.mark.anyio


@pytest.fixture(name="browser")
async def watched_browser_fixture(browser):
    """The same browser, with every page these tests open checked at the end for a console
    error or an uncaught exception (IMP-04)."""
    errors: list[str] = []

    def watch(page) -> None:
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("console", lambda message: errors.append(message.text)
                if message.type == "error" else None)

    original = browser.new_context

    async def new_context(*arguments, **options):
        context = await original(*arguments, **options)
        context.on("page", watch)
        return context

    browser.new_context = new_context
    yield browser
    browser.new_context = original
    assert errors == []


async def test_the_local_dashboard_shows_the_library_and_nothing_a_team_needs(browser, tmp_path,
                                                                              sqlite_url):
    """`aistack dashboard`: the same page, with no way to start a team that has no server."""
    async with local_dashboard(tmp_path, sqlite_url) as (base, link):
        context = await browser.new_context()
        page = await context.new_page()

        await page.goto(link)
        await page.get_by_role("heading", name="Library", level=1).wait_for()
        await expect(page.get_by_role("row").filter(has_text="wizard")).to_be_visible()
        await expect(page.get_by_role("button", name="Add a team")).to_have_count(0)
        await expect(page.get_by_role("navigation", name="Spaces")).to_be_hidden()
        # A project's folders are a server's for now: nothing offers to add one here.
        await expect(page.get_by_role("button", name="Add to Projects")).to_have_count(0)
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


async def test_rules_are_listed_with_a_line_that_editing_comes_later(browser, tmp_path,
                                                                     sqlite_url):
    async with local_dashboard(tmp_path, sqlite_url) as (_, link):
        caller = application_context.get_local_principal()
        with application_context.get_session_factory().begin() as session:
            rule_service.create(session, caller.user_id, "house-style", "# Style\n")
        context = await browser.new_context()
        page = await context.new_page()
        await page.goto(link)

        await page.get_by_text("Your rules (1)").click()
        await expect(page.get_by_text("house-style")).to_be_visible()
        await expect(page.get_by_text("Editing them comes in a later release.")).to_be_visible()
        await context.close()


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
        why = dialog.get_by_text("through your own GitHub sign-in")
        await expect(why).to_be_hidden()
        await dialog.get_by_text("Why GitHub").click()
        await expect(why).to_be_visible()
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
        does = dialog.get_by_text("moves the Library with its history")
        await expect(does).to_be_hidden()
        await dialog.get_by_text("What it does").click()
        await expect(does).to_be_visible()
        await expect(dialog.get_by_text(after)).to_be_visible()
        await expect(dialog.get_by_text("other computers then need")).to_have_count(0)
        await context.close()


async def test_a_library_on_this_computer_only_is_pointed_at_a_move_until_dismissed(
        browser, tmp_path, sqlite_url):
    async with local_dashboard(tmp_path, sqlite_url) as (_, link):
        context = await browser.new_context()
        page = await context.new_page()
        await page.goto(link)

        notice = page.get_by_role("region", name="Your Library lives only on this computer")
        await expect(notice).to_be_visible()
        await notice.get_by_role("link", name="See where it can move").click()
        await expect(page.get_by_role("heading", name="Where your Library lives", level=1)
                     ).to_be_visible()

        await page.get_by_role("navigation", name="Main").get_by_role("link", name="Library"
                                                                      ).click()
        await notice.get_by_role("button", name="Dismiss").click()
        await expect(notice).to_have_count(0)
        await page.reload()
        await page.get_by_role("heading", name="Library", level=1).wait_for()
        await expect(notice).to_have_count(0)
        await context.close()


async def test_a_github_library_out_of_reach_says_so_and_shows_no_move_notice(
        browser, tmp_path, sqlite_url):
    """The test Library is a SQLite file, so /api/state is rewritten to a GitHub one that the
    last pull could not reach."""
    problem = "This computer is signed out of GitHub, so your Library here may be out of date."
    async with local_dashboard(tmp_path, sqlite_url) as (base, link):
        context = await browser.new_context()
        page = await context.new_page()

        async def unreachable(route):
            response = await route.fetch()
            await route.fulfill(response=response, json=await response.json() | {"library": {
                "kind": "github", "repository": "maria/aistack-library", "problem": problem,
                "unpublished": 2}})

        await page.route(f"{base}/api/state", unreachable)
        await page.goto(link)
        await page.get_by_role("heading", name="Library", level=1).wait_for()
        await expect(page.get_by_role("region", name="Your Library lives only on this computer")
                     ).to_have_count(0)

        await page.get_by_role("link", name=re.compile(r"^Library: GitHub\s*, not reached$")).click()
        await expect(page.get_by_text("Could not reach GitHub: showing this computer's copy. "
                                      "2 changes made here go out when it is back.")
                     ).to_be_visible()
        await expect(page.get_by_text(problem)).to_be_visible()
        await context.close()
