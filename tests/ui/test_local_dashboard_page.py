import re
import subprocess

import pytest
from playwright.async_api import expect

from aistack.bootstrap import start_agent
from aistack.bootstrap.context import application_context
from aistack.bundled import RUN_COMMAND
from aistack.db.models.harness import Harness
from aistack.services import project_service, repository_work
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
        # A folder on this computer is looked inside here; another computer's project is a
        # server's.
        await page.get_by_role("button", name="Add to Projects").click()
        menu = page.get_by_role("menu", name="Add to Projects")
        await expect(menu.get_by_role("menuitem")).to_have_count(1)
        await expect(menu.get_by_role("menuitem", name="A folder on this computer…")).to_be_visible()
        await page.keyboard.press("Escape")
        # A full name is for teammates, and local mode has none.
        await page.goto(f"{link.split('/app/')[0]}/app#/settings")
        await expect(page.get_by_role("heading", name="Settings", level=1)).to_be_visible()
        await expect(page.get_by_label("Full name")).to_have_count(0)
        await page.goto(f"{link.split('/app/')[0]}/app#/library")

        await page.get_by_role("button", name="Open wizard").click()
        details = page.get_by_role("dialog", name="wizard")
        await expect(details.get_by_role("button", name="Remove from library…")).to_be_visible()
        await expect(details.get_by_role("button", name="Share with a team…")).to_have_count(0)

        state = await (await page.request.get(f"{base}/api/state")).json()
        await context.close()

    assert state["server"] is False


async def test_a_rule_is_added_and_edited_here(browser, tmp_path, sqlite_url):
    """ADR-0039: the localhost dashboard edits rules, and each change is in the Library's log."""
    async with local_dashboard(tmp_path, sqlite_url) as (base, link):
        context = await browser.new_context()
        page = await context.new_page()
        await page.goto(link)
        nav = page.get_by_role("navigation", name="Main")
        await nav.get_by_role("link", name="Every project").click()
        await nav.get_by_role("button", name="Add to Every project").click()
        await page.get_by_role("menu", name="Add to Every project").get_by_role(
            "menuitem", name="A rule…").click()

        dialog = page.get_by_role("dialog", name="A rule for every project")
        await dialog.get_by_role("textbox", name="Name").fill("house-style")
        await dialog.get_by_role("textbox", name="Text").fill("# Style\n")
        await dialog.get_by_role("button", name="Add rule").click()
        await page.get_by_role("button", name="Open house-style").click()
        await page.get_by_role("dialog", name="house-style").get_by_role(
            "button", name="Edit").click()
        editor = page.get_by_role("dialog", name="Edit house-style")
        await editor.get_by_role("textbox", name="Text").fill("# Style\n- Short.\n")
        await editor.get_by_role("button", name="Save").click()
        await expect(page.get_by_text("Saved house-style as r2.")).to_be_visible()

        state = await (await page.request.get(f"{base}/api/state")).json()
        await context.close()

    assert [(rule["name"], rule["revision"]) for rule in state["rules"]] == [("house-style", 2)]


async def test_open_a_terminal_starts_the_agent_on_this_computer(browser, tmp_path, sqlite_url,
                                                                  monkeypatch):
    """ADR-0038: local mode opens the terminal itself, through its localhost-only route."""
    started = []
    monkeypatch.setattr(start_agent, "_run_from_page", lambda command, **_: (
        started.append(command[3:]) or subprocess.CompletedProcess(command, 0, "", "")))
    async with local_dashboard(tmp_path, sqlite_url) as (_, link):
        caller = application_context.get_local_principal()
        with application_context.get_session_factory().begin() as session:
            project_service.register_folder(session, caller.user_id, caller.machine_id,
                                            "github.com/maria/notes", "notes",
                                            Harness.CLAUDE_CODE, "/home/maria/notes"
                                            ).folder.repository_skills = "wizard"
        context = await browser.new_context()
        page = await context.new_page()
        await page.goto(link)
        await page.get_by_role("navigation", name="Main").get_by_role("link", name="notes").click()

        await page.get_by_role("button", name="Start an agent…").click()
        dialog = page.get_by_role("dialog", name="Start an agent in notes")
        await expect(dialog.get_by_role("link", name="Open on this computer")).to_have_count(0)
        await dialog.get_by_role("checkbox", name="wizard", exact=True).check()
        await dialog.get_by_role("button", name="Open a terminal").click()

        await expect(page.get_by_text("A terminal opened on")).to_be_visible()
        await context.close()

    assert started == [["start", "--new-terminal", "--agent=claude-code",
                        "--project=github.com/maria/notes", "--skills=wizard"]]


async def test_look_inside_shows_a_folders_files_at_once(browser, tmp_path, sqlite_url):
    """ADR-0038: the localhost dashboard reads the folder itself; nothing is sent anywhere."""
    top = tmp_path / "shop"
    top.mkdir()
    for path, text in {"AGENTS.md": "rules\n", "README.md": "readme\n"}.items():
        (top / path).write_text(text)
    subprocess.run(["git", "-C", str(top), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(top), "add", "."], check=True)
    async with local_dashboard(tmp_path, sqlite_url) as (_, link):
        context = await browser.new_context()
        page = await context.new_page()
        await page.goto(link)
        await page.get_by_role("button", name="Add to Projects").click()
        await page.get_by_role("menu", name="Add to Projects").get_by_role(
            "menuitem", name="A folder on this computer…").click()
        dialog = page.get_by_role("dialog", name="Add a project")
        await dialog.get_by_label(re.compile("^Folder on ")).fill(str(top))
        await dialog.get_by_role("button", name="Look inside").click()

        await expect(dialog.get_by_text("Found shop.")).to_be_visible()
        await expect(dialog.get_by_role("checkbox", name="AGENTS.md")).to_be_checked()
        await expect(dialog.get_by_role("checkbox", name="README.md")).not_to_be_checked()
        await context.close()


def _git(top, *arguments):
    return subprocess.run(["git", "-C", str(top), "-c", "user.name=t",
                           "-c", "user.email=t@example.com", *arguments], check=True,
                          capture_output=True, text=True).stdout


async def test_a_folder_here_is_added_then_a_file_is_edited_and_shared(browser, tmp_path,
                                                                       sqlite_url, monkeypatch):
    """ADR-0039: Add keeps the ticked files at once, Edit writes into this working copy, and
    Commit… pushes a branch holding only that file."""
    for name in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):
        monkeypatch.setenv(name, "t")
    for name in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
        monkeypatch.setenv(name, "t@example.com")
    monkeypatch.setattr(repository_work.shutil, "which", lambda name: None)
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    top = tmp_path / "shop"
    top.mkdir()
    for path, text in {"AGENTS.md": "# Shop\n", "README.md": "readme\n"}.items():
        (top / path).write_bytes(text.encode())
    _git(top, "init", "-q", "-b", "main")
    _git(top, "add", ".")
    _git(top, "commit", "-qm", "init")
    _git(top, "remote", "add", "origin", str(remote))
    _git(top, "push", "-qu", "origin", "main")
    async with local_dashboard(tmp_path, sqlite_url) as (_, link):
        context = await browser.new_context()
        page = await context.new_page()
        await page.goto(link)
        await page.get_by_role("button", name="Add to Projects").click()
        await page.get_by_role("menu", name="Add to Projects").get_by_role(
            "menuitem", name="A folder on this computer…").click()
        dialog = page.get_by_role("dialog", name="Add a project")
        await dialog.get_by_label(re.compile("^Folder on ")).fill(str(top))
        await dialog.get_by_role("button", name="Look inside").click()
        await dialog.get_by_role("button", name="Add shop").click()

        await expect(page.get_by_role("heading", name="shop", level=1)).to_be_visible()
        table = page.get_by_role("table", name="What your agents read in shop")
        await table.get_by_role("button", name="Open AGENTS.md").click()
        panel = page.get_by_role("dialog", name="AGENTS.md")
        await expect(panel.get_by_text("# Shop")).to_be_visible()
        await panel.get_by_role("button", name="Edit").click()
        editor = page.get_by_role("dialog", name="Edit AGENTS.md")
        await editor.get_by_label("Text").fill("# Shop\nTests first.\n")
        await editor.get_by_role("button", name="Save").click()
        await expect(page.get_by_text("Wrote your edit into AGENTS.md on this computer.")
                     ).to_be_visible()
        assert (top / "AGENTS.md").read_text() == "# Shop\nTests first.\n"

        await table.get_by_role("button", name="Open AGENTS.md").click()
        panel = page.get_by_role("dialog", name="AGENTS.md")
        await expect(panel.get_by_text(re.compile("^Changed on .+, not committed yet$"))
                     ).to_be_visible()
        await panel.get_by_role("button", name="Commit…").click()
        share = page.get_by_role("dialog", name="Share your change to AGENTS.md")
        await share.get_by_label("What is this change about?").fill("Say tests come first")
        await share.get_by_role("button", name="Open a pull request").click()
        await expect(page.get_by_text(re.compile("^Pushed branch aistack/agents-md-"))
                     ).to_be_visible()

        # Shared: the page says so, with its branch, until this working copy commits the text.
        await page.reload()
        table = page.get_by_role("table", name="What your agents read in shop")
        await expect(table.get_by_text("Shared as a pull request")).to_be_visible()
        await table.get_by_role("button", name="Open AGENTS.md").click()
        panel = page.get_by_role("dialog", name="AGENTS.md")
        await expect(panel.get_by_text("Shared as a pull request")).to_be_visible()
        await expect(panel.get_by_text(re.compile("^On branch aistack/agents-md-"))
                     ).to_be_visible()
        await expect(panel.get_by_role("button", name="Commit…")).to_have_count(0)

        _git(top, "commit", "-qam", "Say tests come first")
        await page.reload()
        table = page.get_by_role("table", name="What your agents read in shop")
        await expect(table.get_by_role("button", name="Open AGENTS.md")).to_be_visible()
        await expect(table.get_by_text("Shared as a pull request")).to_have_count(0)
        await table.get_by_role("button", name="Open AGENTS.md").click()
        panel = page.get_by_role("dialog", name="AGENTS.md")
        await expect(panel.get_by_text("Tests first.")).to_be_visible()
        await expect(panel.get_by_role("button", name="Commit…")).to_have_count(0)
        await context.close()

    branches = _git(remote, "branch", "--list", "aistack/*")
    assert _git(remote, "show", f"{branches.strip()}:AGENTS.md") == "# Shop\nTests first.\n"


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
