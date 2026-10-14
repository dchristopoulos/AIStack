"""The dashboard as a person uses it: a real browser, the real server, no demo mode.

Everything is found by role and by the words a user reads, never by a CSS class, so these
tests state what the page must let someone do and stay true when its look changes.
"""

import pytest
from playwright.async_api import expect

pytestmark = pytest.mark.anyio


def _skill(state: dict, name: str) -> dict:
    return next(skill for skill in state["skills"] if skill["name"] == name)


def _on(state: dict, name: str) -> list[str]:
    """The computers a skill in the user's library is placed on, by name."""
    names = {machine["id"]: machine["name"] for machine in state["machines"]}
    return sorted(names[placement["machine"]] for placement in _skill(state, name)["placements"])


def _team(state: dict, name: str) -> dict:
    return next(team for team in state["teams"] if team["name"] == name)


async def _open_team(opened, name: str) -> None:
    await opened.page.get_by_role("navigation", name="Spaces").get_by_role(
        "link", name=name, exact=True).click()


async def _open_computer(opened, name: str) -> None:
    await opened.page.get_by_role("navigation", name="Main").get_by_role("link", name=name).click()
    await expect(opened.page.get_by_role("heading", name=f"Claude Code on {name}", level=1)
                 ).to_be_visible()


async def test_a_sign_in_link_opens_the_library_and_the_page_talks_only_to_this_server(sign_in):
    maria = await sign_in("maria")

    await expect(maria.page.get_by_role("row").filter(has_text="code-review").get_by_role(
        "link", name="work-laptop / Claude Code")).to_be_visible()
    await expect(maria.page.get_by_role("navigation", name="Spaces")
                 .get_by_role("link", name="aistack", exact=True)).to_be_visible()
    assert "/app/login" not in maria.page.url
    assert maria.console_errors == []
    assert maria.foreign_requests == []


async def test_an_offered_update_is_taken_with_one_click(sign_in):
    maria = await sign_in("maria")
    assert _skill(await maria.state(), "code-review")["source"]["update_available"]

    await maria.page.get_by_role("button", name="Take update").click()

    await expect(maria.page.get_by_role("button", name="Take update")).to_have_count(0)
    code_review = _skill(await maria.state(), "code-review")
    assert (code_review["revision"], code_review["source"]["update_available"]) == (2, False)
    assert maria.console_errors == []


async def test_a_skill_is_added_to_another_computer_from_the_library(sign_in):
    dimitris = await sign_in("dimitris")
    page = dimitris.page
    row = page.get_by_role("row").filter(has_text="sql-style")

    await row.get_by_role("button", name="Add to…").click()
    dialog = page.get_by_role("dialog")
    await expect(dialog.get_by_role("checkbox", name="macbook / Claude Code")).to_be_checked()
    await dialog.get_by_role("checkbox", name="desktop / Claude Code").check()
    await dialog.get_by_role("button", name="Save").click()

    await expect(row.get_by_role("link", name="desktop / Claude Code")).to_be_visible()
    assert _on(await dimitris.state(), "sql-style") == ["desktop", "macbook"]
    assert dimitris.console_errors == []


async def test_a_skill_is_taken_off_a_computer_from_its_tag_and_stays_in_the_library(sign_in):
    dimitris = await sign_in("dimitris")
    page = dimitris.page

    row = page.get_by_role("row").filter(has_text="release-notes")

    await row.get_by_role("button", name="Remove release-notes from macbook / Claude Code").click()

    await expect(row.get_by_text("Only in your library")).to_be_visible()
    state = await dimitris.state()
    assert _on(state, "release-notes") == []
    assert "release-notes" in [skill["name"] for skill in state["skills"]]


async def test_a_computer_page_lists_what_it_has_and_removes_one(sign_in):
    dimitris = await sign_in("dimitris")
    page = dimitris.page
    await _open_computer(dimitris, "macbook")
    table = page.get_by_role("table", name="Skills in Claude Code on macbook")
    await expect(table.get_by_text("sql-style", exact=True)).to_be_visible()

    await page.get_by_role("button", name="Remove sql-style from Claude Code on macbook").click()

    await expect(table.get_by_text("sql-style", exact=True)).to_have_count(0)
    state = await dimitris.state()
    assert _on(state, "sql-style") == []
    assert "sql-style" in [skill["name"] for skill in state["skills"]]
    assert dimitris.console_errors == []


async def test_skills_are_added_to_a_computer_from_its_page(sign_in):
    dimitris = await sign_in("dimitris")
    page = dimitris.page
    await _open_computer(dimitris, "desktop")
    await expect(page.get_by_text("Nothing in Claude Code on desktop yet")).to_be_visible()

    await page.get_by_role("button", name="Add skills").first.click()
    dialog = page.get_by_role("dialog")
    await dialog.get_by_label("Search your library").fill("notes")
    await expect(dialog.get_by_role("checkbox", name="code-review")).to_be_hidden()
    await dialog.get_by_role("checkbox", name="meeting-notes").check()
    await dialog.get_by_role("button", name="Add", exact=True).click()

    await expect(page.get_by_role("table", name="Skills in Claude Code on desktop")
                 .get_by_text("meeting-notes", exact=True)).to_be_visible()
    assert _on(await dimitris.state(), "meeting-notes") == ["desktop", "macbook"]


async def test_a_computer_copies_what_another_one_has(sign_in):
    dimitris = await sign_in("dimitris")
    page = dimitris.page
    on_macbook = [skill["name"] for skill in (await dimitris.state())["skills"]
                  if skill["placements"]]
    await _open_computer(dimitris, "desktop")

    await page.get_by_role("button", name="Copy from…").click()
    dialog = page.get_by_role("dialog")
    await expect(dialog.get_by_role("radio", name="macbook / Claude Code")).to_be_checked()
    await dialog.get_by_role("button", name="Copy").click()

    await expect(dialog).to_have_count(0)
    state = await dimitris.state()
    assert [name for name in on_macbook if _on(state, name) != ["desktop", "macbook"]] == []
    assert len(on_macbook) == 7


async def test_adding_a_computer_says_what_to_ask_the_agent(sign_in):
    dimitris = await sign_in("dimitris")
    page = dimitris.page

    await page.get_by_role("navigation", name="Main").get_by_role("button", name="Add a computer").click()

    sentence = page.get_by_role("dialog").get_by_role("textbox", name="What to say")
    await expect(sentence).to_have_value("add my Windows PC to aistack")
    await page.get_by_role("dialog").get_by_role("button", name="Done").click()
    await expect(page.get_by_role("dialog")).to_have_count(0)


async def test_a_skill_is_shared_into_a_nested_group_from_a_dialog(sign_in):
    dimitris = await sign_in("dimitris")
    page = dimitris.page

    await page.get_by_role("button", name="More actions for meeting-notes").click()
    await page.get_by_role("menuitem", name="Share with a team…").click()
    dialog = page.get_by_role("dialog")
    await dialog.get_by_label("Team", exact=True).select_option("aistack")
    await dialog.get_by_role("radio", name="developers/backend").check()
    await dialog.get_by_role("button", name="Share", exact=True).click()

    await expect(dialog).to_have_count(0)
    aistack = _team(await dimitris.state(), "aistack")
    assert ("meeting-notes", "developers/backend", "dimitris") in [
        (skill["name"], skill["group"], skill["pushed_by"]) for skill in aistack["skills"]]
    assert dimitris.console_errors == []


async def test_escape_closes_a_dialog_and_gives_focus_back(sign_in):
    dimitris = await sign_in("dimitris")
    page = dimitris.page
    opener = page.get_by_role("button", name="Add a team")

    await opener.click()
    await expect(page.get_by_role("dialog")).to_be_visible()
    await page.keyboard.press("Escape")

    await expect(page.get_by_role("dialog")).to_have_count(0)
    await expect(opener).to_be_focused()
    assert [team["name"] for team in (await dimitris.state())["teams"]] == ["aistack", "everyone"]


async def test_an_admin_makes_a_group_inside_a_group(sign_in):
    dimitris = await sign_in("dimitris")
    page = dimitris.page
    await _open_team(dimitris, "aistack")
    await page.get_by_role("tab", name="Groups").click()

    await page.get_by_role("button", name="New group").click()
    dialog = page.get_by_role("dialog")
    await dialog.get_by_label("Name").fill("frontend")
    await dialog.get_by_role("radio", name="developers/backend").check()
    await dialog.get_by_role("button", name="Create").click()

    await expect(dialog).to_have_count(0)
    await expect(page.get_by_role("switch", name="developers/backend/frontend is private")
                 ).to_be_visible()
    aistack = _team(await dimitris.state(), "aistack")
    assert "developers/backend/frontend" in [group["path"] for group in aistack["groups"]]


async def test_a_member_is_shown_no_private_group_and_no_admin_control(sign_in):
    alex = await sign_in("alex")
    page = alex.page
    await _open_team(alex, "aistack")

    await expect(page.get_by_role("button", name="developers", exact=False).first).to_be_visible()
    await expect(page.get_by_text("pentest-checklist")).to_have_count(0)
    await expect(page.get_by_role("switch", name="Subscribed to security")).to_have_count(0)
    await expect(page.get_by_role("button", name="More actions for code-review")
                 ).to_have_count(0)

    await page.get_by_role("tab", name="Groups").click()
    await expect(page.get_by_role("button", name="New group")).to_have_count(0)
    await expect(page.get_by_role("switch", name="developers is private")).to_have_count(0)
    assert alex.console_errors == []


async def test_a_team_is_created_and_joined_with_its_invite_code(sign_in):
    dimitris = await sign_in("dimitris")
    page = dimitris.page
    await page.get_by_role("button", name="Add a team").click()
    await page.get_by_role("dialog").get_by_role("button", name="Continue").click()
    create = page.get_by_role("dialog", name="New team")
    await create.get_by_label("Name").fill("design")
    await create.get_by_role("button", name="Create").click()
    await expect(page.get_by_role("heading", name="design", level=1)).to_be_visible()

    await page.get_by_role("tab", name="Settings").click()
    await page.get_by_role("button", name="Create new invite code").click()
    # It asks first: a new code stops the previous one working.
    await page.get_by_role("dialog").get_by_role("button", name="Create new code").click()
    code = await page.get_by_role("dialog").get_by_label("Invite code").input_value()
    assert code.startswith("aistinv_") and len(code) > 20
    await page.get_by_role("dialog").get_by_role("button", name="Done").click()

    alex = await sign_in("alex")
    await alex.page.get_by_role("button", name="Add a team").click()
    await alex.page.get_by_role("dialog").get_by_role("radio", name="Join with an invite code").check()
    await alex.page.get_by_role("dialog").get_by_role("button", name="Continue").click()
    join = alex.page.get_by_role("dialog", name="Join a team")
    await join.get_by_label("Invite code").fill(code.strip())
    await join.get_by_role("button", name="Join").click()

    await expect(alex.page.get_by_role("heading", name="design", level=1)).to_be_visible()
    assert "design" in [team["name"] for team in (await alex.state())["teams"]]


async def test_signing_out_closes_the_dashboard_in_that_browser(sign_in):
    maria = await sign_in("maria")

    await maria.page.get_by_role("button", name="Sign out").click()

    await expect(maria.page.get_by_text("open my aistack dashboard")).to_be_visible()
    assert (await maria.page.request.get(f"{maria.base_url}/api/state")).status == 401


@pytest.mark.parametrize("route", ["#/library", "#/f/{macbook}/claude_code", "#/t/aistack/skills",
                                   "#/t/aistack/groups", "#/t/aistack/members"])
async def test_nothing_scrolls_sideways_on_a_phone(sign_in, route):
    dimitris = await sign_in("dimitris", viewport=(390, 844))
    macbook = (await dimitris.state())["machines"][0]["id"]

    await dimitris.page.goto(f"{dimitris.base_url}/app{route.format(macbook=macbook)}")
    await dimitris.page.wait_for_timeout(300)

    overflow = await dimitris.page.evaluate(
        "document.documentElement.scrollWidth - window.innerWidth")
    assert overflow <= 0
    assert dimitris.console_errors == []


async def test_the_phone_menu_opens_and_closes_with_a_control_you_can_see(sign_in):
    dimitris = await sign_in("dimitris", viewport=(390, 844))
    page = dimitris.page
    spaces = page.get_by_role("navigation", name="Spaces")
    navigation = page.get_by_role("navigation", name="Main")
    await expect(spaces).to_be_hidden()
    await expect(navigation).to_be_hidden()

    await page.get_by_role("button", name="Open navigation").click()
    await expect(spaces.get_by_role("link", name="aistack", exact=True)).to_be_visible()
    await expect(navigation.get_by_role("link", name="desktop")).to_be_visible()
    close = page.get_by_label("Navigation").get_by_role("button", name="Close navigation")
    await expect(close).to_be_visible()
    await close.click()

    await expect(spaces).to_be_hidden()
    await expect(navigation).to_be_hidden()


async def test_a_group_is_opened_from_the_sidebar_and_shows_only_what_is_in_it(sign_in):
    dimitris = await sign_in("dimitris")
    page = dimitris.page
    await _open_team(dimitris, "aistack")

    await page.get_by_role("navigation", name="Main").get_by_role("link", name="backend").click()

    await expect(page.get_by_role("table", name="Skills in developers/backend")).to_be_visible()
    await expect(page.get_by_text("aistack-api-notes")).to_be_visible()
    await expect(page.get_by_text("sql-style")).to_have_count(0)
    assert page.url.endswith("#/t/aistack/skills/developers/backend")

    await page.reload()
    await expect(page.get_by_role("table", name="Skills in developers/backend")).to_be_visible()

    await page.get_by_role("link", name="All of aistack").click()
    await expect(page.get_by_text("sql-style")).to_be_visible()
    assert dimitris.console_errors == []


async def test_the_sidebar_shows_a_member_no_private_group_they_are_not_in(sign_in):
    alex = await sign_in("alex")
    await _open_team(alex, "aistack")
    navigation = alex.page.get_by_role("navigation", name="Main")

    await expect(navigation.get_by_role("link", name="developers")).to_be_visible()
    await expect(navigation.get_by_role("link", name="security")).to_have_count(0)

    await alex.page.goto(f"{alex.base_url}/app#/t/aistack/skills/security")
    await expect(alex.page.get_by_role("table", name="Skills in aistack")).to_be_visible()
    await expect(alex.page.get_by_text("pentest-checklist")).to_have_count(0)
