"""The dashboard as a person uses it: a real browser, the real server, no demo mode.

Everything is found by role and by the words a user reads, never by a CSS class, so these
tests state what the page must let someone do and stay true when its look changes.
"""

import re

import pytest
from playwright.async_api import expect

from scripts.demo_seed import DEEP_GROUP, LONG_FULL_NAME, LONG_TEAM, LONG_USERNAME
from tests.mcp.conftest import call, join

pytestmark = pytest.mark.anyio


def _skill(state: dict, name: str) -> dict:
    return next(skill for skill in state["skills"] if skill["name"] == name)


def _placed(placements: list[dict], machine: str, harness: str) -> bool:
    return any(placement["machine"] == machine and placement["harness"] == harness
               for placement in placements)


def _on(state: dict, name: str) -> list[str]:
    """The computers a skill in the user's library is placed on in Claude Code, by name."""
    names = {machine["id"]: machine["name"] for machine in state["machines"]}
    return sorted(names[placement["machine"]] for placement in _skill(state, name)["placements"]
                  if placement["harness"] == "claude_code")


def _team(state: dict, name: str) -> dict:
    return next(team for team in state["teams"] if team["name"] == name)


async def _open_team(opened, name: str) -> None:
    await opened.page.get_by_role("navigation", name="Spaces").get_by_role(
        "link", name=name, exact=True).click()


async def _open_computer(opened, name: str, agent: str = "Claude Code") -> None:
    await opened.page.get_by_role("navigation", name="Main").get_by_role(
        "link", name=f"{name} / {agent}").click()
    await expect(opened.page.get_by_role("heading", name=f"{agent} on {name}", level=1)
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


async def test_an_update_over_your_own_changes_names_them_before_it_is_taken(sign_in):
    maria = await sign_in("maria")
    source = _skill(await maria.state(), "code-review")["source"]
    assert (source["update_available"], source["own_changes"]) == (True, True)

    await maria.page.get_by_role("button", name="Take update").click()
    dialog = maria.page.get_by_role("dialog", name="Take the update to code-review?")
    await expect(dialog.get_by_text("replaces your r2")).to_be_visible()
    await expect(dialog.get_by_text("replaced on work-laptop")).to_be_visible()
    assert _skill(await maria.state(), "code-review")["revision"] == 2

    await dialog.get_by_role("button", name="Take update").click()

    await expect(maria.page.get_by_role("button", name="Take update")).to_have_count(0)
    code_review = _skill(await maria.state(), "code-review")
    assert (code_review["revision"], code_review["pushed_by"],
            code_review["source"]["update_available"]) == (3, "dimitris", False)
    assert maria.console_errors == []


async def test_a_team_skill_named_like_one_of_yours_replaces_it_only_once_confirmed(sign_in):
    alex = await sign_in("alex")
    await _open_team(alex, "aistack")
    row = alex.page.get_by_role("row").filter(has_text="release-notes")

    await row.get_by_role("button", name="Replace yours with the team's release-notes…").click()
    dialog = alex.page.get_by_role("dialog", name="Replace your release-notes?")
    await expect(dialog.get_by_text("your own release-notes, r1, last pushed by alex")
                 ).to_be_visible()
    await expect(dialog.get_by_text("replaced on thinkpad")).to_be_visible()
    assert _skill(await alex.state(), "release-notes")["pushed_by"] == "alex"

    await dialog.get_by_role("button", name="Replace yours").click()

    await expect(row.get_by_text("In your library")).to_be_visible()
    mine = _skill(await alex.state(), "release-notes")
    assert (mine["revision"], mine["pushed_by"], mine["source"]["team"]) == (
        2, "dimitris", "aistack")
    assert alex.console_errors == []


async def test_the_share_dialog_says_what_sharing_would_go_over_before_it_does(sign_in):
    alex = await sign_in("alex")
    await alex.page.get_by_role("button", name="Details of release-notes").click()
    await alex.page.get_by_role("dialog", name="release-notes").get_by_role(
        "button", name="Share with a team…").click()
    dialog = alex.page.get_by_role("dialog", name="Share release-notes")

    await expect(dialog.get_by_text("aistack already has a different release-notes, last "
                                    "pushed by dimitris")).to_be_visible()
    await expect(dialog.get_by_role("button", name="Share anyway")).to_be_visible()
    await dialog.get_by_role("button", name="Cancel").click()
    assert _skill(_team(await alex.state(), "aistack"), "release-notes")["revision"] == 1

    maria = await sign_in("maria")
    await maria.page.get_by_role("button", name="Details of code-review").click()
    await maria.page.get_by_role("dialog", name="code-review").get_by_role(
        "button", name="Share with a team…").click()
    dialog = maria.page.get_by_role("dialog", name="Share code-review")

    await expect(dialog.get_by_text("aistack has r2 of code-review from dimitris, which you "
                                    "never took")).to_be_visible()
    await expect(dialog.get_by_role("button", name="Share anyway")).to_be_visible()
    assert alex.console_errors == [] and maria.console_errors == []


async def test_a_skill_is_added_to_another_computer_from_the_library(sign_in):
    dimitris = await sign_in("dimitris")
    page = dimitris.page
    row = page.get_by_role("row").filter(has_text="sql-style")

    await row.get_by_role("button", name="Add to computer").click()
    dialog = page.get_by_role("dialog")
    await expect(dialog.get_by_role("checkbox", name="macbook / Claude Code")).to_be_checked()
    await dialog.get_by_role("checkbox", name="desktop / Claude Code").check()
    await dialog.get_by_role("button", name="Save").click()

    await expect(row.get_by_role("link", name="desktop / Claude Code")).to_be_visible()
    assert _on(await dimitris.state(), "sql-style") == ["desktop", "macbook"]
    assert dimitris.console_errors == []


async def test_a_skill_is_taken_off_a_computer_from_its_details_and_stays_in_the_library(sign_in):
    dimitris = await sign_in("dimitris")
    page = dimitris.page
    row = page.get_by_role("row").filter(has_text="release-notes")
    # Where a skill is reads as words; nothing in the row removes it by accident.
    await expect(row.get_by_role("button", name="macbook", exact=False)).to_have_count(0)

    await row.get_by_role("button", name="Details of release-notes").click()
    details = page.get_by_role("dialog", name="release-notes")
    await expect(details.get_by_text("r1, 2 files")).to_be_visible()
    await details.get_by_role("checkbox", name="macbook / Claude Code").uncheck()
    await details.get_by_role("button", name="Save").click()

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


async def test_the_agents_folder_has_its_own_page_and_says_who_reads_it(sign_in):
    dimitris = await sign_in("dimitris")
    page = dimitris.page
    await _open_computer(dimitris, "macbook", "Agents folder")
    await expect(page.get_by_text("Read by Codex", exact=False)).to_be_visible()
    table = page.get_by_role("table", name="Skills in Agents folder on macbook")
    await expect(table.get_by_text("meeting-notes", exact=True)).to_be_visible()

    await page.get_by_role("button", name="Copy from…").click()
    dialog = page.get_by_role("dialog")
    await expect(dialog.get_by_role("radio", name="macbook / Claude Code")).to_be_checked()
    await dialog.get_by_role("button", name="Copy").click()

    await expect(dialog).to_have_count(0)
    await expect(table.get_by_text("sql-style", exact=True)).to_be_visible()
    state = await dimitris.state()
    macbook = state["machines"][0]["id"]
    in_agents = sorted(skill["name"] for skill in state["skills"]
                       if _placed(skill["placements"], macbook, "agents"))
    in_claude = sorted(skill["name"] for skill in state["skills"]
                       if _placed(skill["placements"], macbook, "claude_code"))
    assert in_agents == in_claude
    assert dimitris.console_errors == []


async def test_a_skill_is_added_to_the_agents_folder_from_the_library(sign_in):
    dimitris = await sign_in("dimitris")
    page = dimitris.page
    row = page.get_by_role("row").filter(has_text="sql-style")

    await row.get_by_role("button", name="Add to computer").click()
    dialog = page.get_by_role("dialog")
    await expect(dialog.get_by_role("checkbox", name="macbook / Agents folder")).not_to_be_checked()
    await dialog.get_by_role("checkbox", name="macbook / Agents folder").check()
    await dialog.get_by_role("button", name="Save").click()

    await expect(row.get_by_role("link", name="macbook / Agents folder")).to_be_visible()
    macbook = (await dimitris.state())["machines"][0]["id"]
    assert _placed(_skill(await dimitris.state(),
                                                                "sql-style")["placements"], macbook, "agents")


async def test_adding_a_computer_says_what_to_ask_the_agent(sign_in):
    dimitris = await sign_in("dimitris")
    page = dimitris.page

    await page.get_by_role("navigation", name="Main").get_by_role("button", name="Add a computer").click()

    sentence = page.get_by_role("dialog").get_by_role("textbox", name="What to say")
    await expect(sentence).to_have_value("add my Windows PC to aistack")
    # UX-20: what the agent answers is a credential, and the person carries it.
    await expect(page.get_by_role("dialog").get_by_text("holds a permanent key for that computer")).to_be_visible()
    await page.get_by_role("dialog").get_by_role("button", name="Done").click()
    await expect(page.get_by_role("dialog")).to_have_count(0)


async def test_an_agent_is_added_to_a_computer_and_given_a_skill(sign_in):
    dimitris = await sign_in("dimitris")
    page = dimitris.page
    navigation = page.get_by_role("navigation", name="Main")

    await navigation.get_by_role("button", name="Add an agent to desktop").click()
    dialog = page.get_by_role("dialog")
    await dialog.get_by_role("radio", name="Agents folder").check()
    await dialog.get_by_role("button", name="Open its folder").click()
    await expect(page.get_by_role("heading", name="Agents folder on desktop", level=1)).to_be_visible()
    await expect(navigation.get_by_role("link", name="desktop / Agents folder")).to_be_visible()

    await page.get_by_role("button", name="Add skills").first.click()
    await page.get_by_role("dialog").get_by_role("checkbox", name="meeting-notes").check()
    await page.get_by_role("dialog").get_by_role("button", name="Add", exact=True).click()

    await expect(page.get_by_role("table", name="Skills in Agents folder on desktop")
                 .get_by_text("meeting-notes", exact=True)).to_be_visible()
    state = await dimitris.state()
    desktop = next(m["id"] for m in state["machines"] if m["name"] == "desktop")
    assert _placed(_skill(state, "meeting-notes")["placements"], desktop, "agents")
    assert dimitris.console_errors == []


async def test_appearance_is_chosen_in_settings_and_kept_in_this_browser(sign_in):
    dimitris = await sign_in("dimitris")
    page = dimitris.page
    root = page.locator("html")

    await page.get_by_role("navigation", name="Main").get_by_role("link", name="Settings").click()
    await page.get_by_role("radio", name="Dark").check()
    await page.get_by_role("radio", name="Teal").check()

    await expect(root).to_have_attribute("data-theme", "dark")
    await expect(root).to_have_attribute("data-accent", "teal")
    await page.reload()
    await expect(root).to_have_attribute("data-theme", "dark")
    await expect(page.get_by_role("radio", name="Teal")).to_be_checked()

    await page.get_by_role("radio", name="Light").check()
    await expect(root).to_have_attribute("data-theme", "light")
    assert dimitris.console_errors == []


async def test_a_full_name_set_in_settings_is_what_teammates_read(sign_in):
    alex = await sign_in("alex")
    await alex.page.get_by_role("navigation", name="Main").get_by_role("link", name="Settings").click()

    await alex.page.get_by_label("Full name").fill("Alex Georgiou")
    await alex.page.get_by_role("button", name="Save name").click()

    await expect(alex.page.get_by_text("Your teammates now see Alex Georgiou.")).to_be_visible()
    assert (await alex.state())["user"] == {"username": "alex", "full_name": "Alex Georgiou"}
    dimitris = await sign_in("dimitris")
    await _open_team(dimitris, "aistack")
    await dimitris.page.get_by_role("tab", name="Members").click()
    row = dimitris.page.get_by_role("row").filter(has_text="Alex Georgiou")
    await expect(row.get_by_text("alex", exact=True)).to_be_visible()
    assert alex.console_errors == []


async def test_a_skill_is_shared_into_a_nested_group_from_a_dialog(sign_in):
    dimitris = await sign_in("dimitris")
    page = dimitris.page

    await page.get_by_role("button", name="meeting-notes", exact=True).click()
    await page.get_by_role("dialog", name="meeting-notes").get_by_role(
        "button", name="Share with a team…").click()
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
    assert [team["name"] for team in (await dimitris.state())["teams"]] == ["aistack"]


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
    await expect(page.get_by_role("button", name="Manage code-review")).to_have_count(0)

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
    await page.get_by_role("button", name="Create invite link").click()
    code = await page.get_by_role("dialog").get_by_label("Invite code").input_value()
    assert code.startswith("aistinv_") and len(code) > 20
    link = await page.get_by_role("dialog").get_by_label("Invite link").input_value()
    assert link.endswith(f"/invite/{code}")
    response = await page.request.get(link)
    assert response.status == 200 and "design" in await response.text()
    # This server is on 127.0.0.1, so the link opens only on this computer, and it says so.
    await expect(page.get_by_role("dialog").get_by_text("Only this computer can open this link")).to_be_visible()
    await page.get_by_role("dialog").get_by_role("button", name="Done").click()

    alex = await sign_in("alex")
    await alex.page.get_by_role("button", name="Add a team").click()
    await alex.page.get_by_role("dialog").get_by_role("radio", name="Join with an invite code").check()
    await alex.page.get_by_role("dialog").get_by_role("button", name="Continue").click()
    join = alex.page.get_by_role("dialog", name="Join a team")
    # The link is what people are sent, so pasting it works as well as the code.
    await join.get_by_label("Invite code").fill(link)
    await join.get_by_role("button", name="Join").click()

    await expect(alex.page.get_by_role("heading", name="design", level=1)).to_be_visible()
    assert "design" in [team["name"] for team in (await alex.state())["teams"]]


async def test_a_signed_in_member_joins_from_the_invite_page_in_one_click(sign_in):
    """AUTO-22: the page links to the dashboard with the code where the server never sees it."""
    maria = await sign_in("maria")
    await _open_team(maria, "friends")
    await maria.page.get_by_role("tab", name="Settings").click()
    await maria.page.get_by_role("button", name="Create invite link").click()
    link = await maria.page.get_by_role("dialog").get_by_label("Invite link").input_value()

    alex = await sign_in("alex")
    await alex.page.goto(link)
    await alex.page.get_by_role("link", name="join in your dashboard").click()
    join = alex.page.get_by_role("dialog", name="Join a team")
    await join.get_by_role("button", name="Join team").click()

    await expect(alex.page.get_by_role("heading", name="friends", level=1)).to_be_visible()
    assert "friends" in [team["name"] for team in (await alex.state())["teams"]]
    assert "aistinv_" not in alex.page.url
    assert alex.console_errors == []


async def test_an_admin_lets_a_member_invite_and_the_member_can(sign_in):
    dimitris = await sign_in("dimitris")
    await _open_team(dimitris, "aistack")
    await dimitris.page.get_by_role("tab", name="Members").click()

    await dimitris.page.get_by_role("switch", name="maria can invite").click()

    await expect(dimitris.page.get_by_role("switch", name="maria can invite")
                 ).to_have_attribute("aria-checked", "true")
    members = _team(await dimitris.state(), "aistack")["members"]
    assert next(m for m in members if m["username"] == "maria")["can_invite"] is True

    maria = await sign_in("maria")
    await _open_team(maria, "aistack")
    await maria.page.get_by_role("tab", name="Settings").click()
    await maria.page.get_by_role("button", name="Create invite link").click()
    link = await maria.page.get_by_role("dialog").get_by_label("Invite link").input_value()
    assert "/invite/aistinv_" in link
    assert maria.console_errors == []


async def test_an_invite_is_listed_as_pending_and_cancelled_from_the_list(sign_in):
    dimitris = await sign_in("dimitris")
    page = dimitris.page
    await _open_team(dimitris, "aistack")
    await page.get_by_role("tab", name="Settings").click()
    await page.get_by_role("button", name="Create invite link").click()
    await page.get_by_role("dialog").get_by_role("button", name="Done").click()
    invites = page.get_by_role("table", name="Invites")
    await expect(invites.get_by_text("Pending")).to_be_visible()

    await invites.get_by_role("button", name="Cancel the invite dimitris made").click()

    await expect(invites.get_by_text("Cancelled")).to_be_visible()
    assert [invite["status"] for invite in _team(await dimitris.state(), "aistack")["invites"]
            if invite["created_by"] == "dimitris"][0] == "CANCELLED"
    assert dimitris.console_errors == []


async def test_an_admin_deletes_a_team_and_members_keep_what_they_took(sign_in):
    maria = await sign_in("maria")
    taken = [skill["name"] for skill in (await maria.state())["skills"]
             if (skill.get("source") or {}).get("team") == "aistack"]
    dimitris = await sign_in("dimitris")
    page = dimitris.page
    await _open_team(dimitris, "aistack")
    await page.get_by_role("tab", name="Settings").click()

    await page.get_by_role("button", name="Delete team").click()
    await page.get_by_role("dialog", name="Delete aistack?").get_by_role(
        "button", name="Delete team").click()

    await expect(page.get_by_role("heading", name="Library", level=1)).to_be_visible()
    assert "aistack" not in [team["name"] for team in (await dimitris.state())["teams"]]
    after = await maria.state()
    assert "aistack" not in [team["name"] for team in after["teams"]]
    assert taken and set(taken) <= {skill["name"] for skill in after["skills"]}
    assert dimitris.console_errors == []


async def test_an_admin_renames_a_group_and_deletes_only_an_empty_one(sign_in):
    dimitris = await sign_in("dimitris")
    page = dimitris.page
    await _open_team(dimitris, "aistack")
    await page.get_by_role("tab", name="Groups").click()

    await page.get_by_role("button", name="Manage developers", exact=True).click()
    await page.get_by_role("menuitem", name="Rename…").click()
    rename = page.get_by_role("dialog", name="Rename developers")
    await rename.get_by_label("New name").fill("engineering")
    await rename.get_by_role("button", name="Rename").click()
    await expect(page.get_by_role("button", name="Manage engineering/backend")).to_be_visible()
    paths = [group["path"] for group in _team(await dimitris.state(), "aistack")["groups"]]
    assert "engineering/backend" in paths and "developers" not in paths

    await page.get_by_role("button", name="Manage security", exact=True).click()
    await page.get_by_role("menuitem", name="Delete group").click()
    refused = page.get_by_role("dialog", name="Delete security?")
    await refused.get_by_role("button", name="Delete group").click()
    await expect(refused.get_by_role("alert")).to_contain_text("still has skills")
    await refused.get_by_role("button", name="Cancel").click()

    await page.get_by_role("button", name="New group").first.click()
    create = page.get_by_role("dialog", name="New group in aistack")
    await create.get_by_label("Name").fill("typo")
    await create.get_by_role("button", name="Create group").click()
    await page.get_by_role("button", name="Manage typo", exact=True).click()
    await page.get_by_role("menuitem", name="Delete group").click()
    await page.get_by_role("dialog", name="Delete typo?").get_by_role(
        "button", name="Delete group").click()

    await expect(page.get_by_role("button", name="Manage typo", exact=True)).to_have_count(0)
    paths = [group["path"] for group in _team(await dimitris.state(), "aistack")["groups"]]
    assert "typo" not in paths and "security" in paths
    # The refusal's own answer is the one error a browser reports.
    assert [error for error in dimitris.console_errors if "409" not in error] == []


async def test_the_only_member_leaving_a_team_deletes_it(sign_in):
    alex = await sign_in("alex")
    page = alex.page
    await page.get_by_role("button", name="Add a team").click()
    await page.get_by_role("dialog").get_by_role("button", name="Continue").click()
    create = page.get_by_role("dialog", name="New team")
    await create.get_by_label("Name").fill("solo")
    await create.get_by_role("button", name="Create").click()
    await page.get_by_role("tab", name="Settings").click()

    await page.get_by_role("button", name="Leave team").click()
    await page.get_by_role("dialog", name="Leave solo?").get_by_role(
        "button", name="Leave and delete").click()

    await expect(page.get_by_role("heading", name="Library", level=1)).to_be_visible()
    assert "solo" not in [team["name"] for team in (await alex.state())["teams"]]
    assert alex.console_errors == []


async def test_someone_new_with_no_team_is_shown_how_to_get_one(browser, server_url, links):
    token = await join(server_url, "newbie", "laptop")
    context = await browser.new_context()
    page = await context.new_page()
    await page.goto((await call(server_url, token, "open_dashboard"))["url"])

    await expect(page.get_by_role("heading", name="Your library is empty")).to_be_visible()
    await expect(page.get_by_text('choose "Add a team" to create one or join')).to_be_visible()
    await context.close()


async def test_a_computer_that_never_synced_shows_no_agent_until_it_does(browser, server_url,
                                                                       links):
    """UX-07: shown with Claude Code, a computer added for Codex invited skills into a folder
    no agent there reads."""
    token = await join(server_url, "newbie", "laptop")
    await call(server_url, token, "add_machine", name="windows-pc", os="WINDOWS")
    context = await browser.new_context()
    page = await context.new_page()
    await page.goto((await call(server_url, token, "open_dashboard"))["url"])
    navigation = page.get_by_role("navigation", name="Main")

    await expect(navigation.get_by_text('Not synced yet: say "sync aistack" there.')
                 ).to_have_count(2)
    await expect(navigation.get_by_role("link", name="windows-pc / Claude Code")).to_have_count(0)

    await call(server_url, token, "sync", local={}, harness="agents")
    await page.reload()
    await expect(navigation.get_by_role("link", name="laptop / Agents folder")).to_be_visible()
    await expect(navigation.get_by_text('Not synced yet: say "sync aistack" there.')
                 ).to_have_count(1)
    await context.close()


async def _come_back_to_the_tab(page):
    # A headless tab is never hidden, so the return is announced as a browser announces it.
    await page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")


@pytest.mark.parametrize("return_event", [
    # A headless tab is never hidden, so the return is announced as a browser announces it.
    "document.dispatchEvent(new Event('visibilitychange'))",
    # The browser beside the terminal stays visible; coming back to it is a focus.
    "window.dispatchEvent(new Event('focus'))",
])
async def test_coming_back_to_the_tab_shows_what_changed_meanwhile(sign_in, return_event):
    maria = await sign_in("maria")
    name = (await maria.state())["skills"][0]["name"]
    listed = maria.page.get_by_role("main").get_by_text(name, exact=True)
    await expect(listed.first).to_be_visible()

    # Removed somewhere else while this tab sat in the background.
    removed = await maria.page.request.post(f"{maria.base_url}/api/skills/{name}/remove",
                                            headers={"X-AIStack-Request": "1"})
    assert removed.ok
    await maria.page.evaluate(return_event)

    await expect(listed).to_have_count(0)
    assert name not in [skill["name"] for skill in (await maria.state())["skills"]]
    assert maria.console_errors == []


async def test_coming_back_after_the_session_ended_says_so_before_any_click(sign_in):
    maria = await sign_in("maria")

    # What a server restart does to the session: the cookie no longer opens anything.
    await maria.page.context.clear_cookies()
    await _come_back_to_the_tab(maria.page)

    await expect(maria.page.get_by_role("heading", name="Your session has ended.")).to_be_visible()


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


# Every row of every table on the page: each box inside a cell stays inside that cell, and no
# box of one cell lies over a box of another. Rows and cells are found by their roles.
_LAYOUT_PROBLEMS = """() => {
  const problems = [];
  const boxes = cell => [cell, ...cell.querySelectorAll('*')]
    .map(node => ({ node, rect: node.getBoundingClientRect() }))
    .filter(box => box.rect.width > 0 && box.rect.height > 0);
  const label = node => (node.innerText || node.getAttribute('aria-label') || node.tagName)
    .trim().slice(0, 40);
  const overlap = (a, b) => Math.min(a.right, b.right) - Math.max(a.left, b.left) > 1
    && Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top) > 1;
  for (const row of document.querySelectorAll('[role=row]')) {
    const cells = [...row.querySelectorAll(':scope > [role=cell], :scope > [role=columnheader]')]
      .map(cell => ({ cell, rect: cell.getBoundingClientRect(), inside: boxes(cell) }));
    for (const { cell, rect, inside } of cells) {
      for (const box of inside) {
        if (box.rect.left < rect.left - 1 || box.rect.right > rect.right + 1) {
          problems.push(`'${label(box.node)}' sticks out of its cell in '${label(row)}'`);
        }
      }
    }
    for (let i = 0; i < cells.length; i++) {
      for (let j = i + 1; j < cells.length; j++) {
        for (const a of cells[i].inside) {
          const hit = cells[j].inside.find(b => overlap(a.rect, b.rect));
          if (hit) {
            problems.push(`'${label(a.node)}' lies over '${label(hit.node)}' in '${label(row)}'`);
            break;
          }
        }
      }
    }
  }
  const sideways = document.documentElement.scrollWidth - window.innerWidth;
  if (sideways > 0) problems.push(`the page scrolls ${sideways}px sideways`);
  return [...new Set(problems)];
}"""


async def _layout_problems(opened, route: str) -> list[str]:
    await opened.page.goto(f"{opened.base_url}/app{route}")
    await opened.page.get_by_role("heading", level=1).first.wait_for()
    await opened.page.wait_for_timeout(300)
    return [f"{route}: {problem}" for problem in await opened.page.evaluate(_LAYOUT_PROBLEMS)]


# Layout does not depend on the database, so these run on SQLite only, and each walks its
# widths in one browser tab rather than seeding a server per width.
_SQLITE_ONLY = pytest.mark.parametrize("portable_engine", ["sqlite"], indirect=True)


@_SQLITE_ONLY
async def test_tables_keep_their_columns_apart_at_tablet_width(sign_in):
    dimitris = await sign_in("dimitris")
    macbook = (await dimitris.state())["machines"][0]["id"]

    problems = []
    for width, height in ((834, 1194), (900, 900)):
        await dimitris.page.set_viewport_size({"width": width, "height": height})
        for route in ("#/library", f"#/f/{macbook}/claude_code", "#/t/aistack/skills",
                      "#/t/aistack/groups", "#/t/aistack/members"):
            problems += [f"{width}px {problem}"
                         for problem in await _layout_problems(dimitris, route)]

    assert problems == []
    assert dimitris.console_errors == []


@_SQLITE_ONLY
@pytest.mark.long_names
async def test_the_longest_names_fit_without_scrolling_sideways(sign_in):
    team = f"#/t/{LONG_TEAM}"
    dimitris = await sign_in("dimitris")
    someone = await sign_in(LONG_USERNAME)

    problems = []
    for width, height in ((1440, 900), (1024, 768), (834, 1194), (390, 844)):
        for opened in (dimitris, someone):
            await opened.page.set_viewport_size({"width": width, "height": height})
        found = []
        for route in (f"{team}/skills", f"{team}/skills/{DEEP_GROUP}", f"{team}/groups",
                      f"{team}/members"):
            found += await _layout_problems(dimitris, route)
        for route in (f"{team}/skills", "#/library"):
            found += await _layout_problems(someone, route)
        await someone.page.get_by_role("button", name="Details of code-review").click()
        details = someone.page.get_by_role("dialog", name="code-review")
        await expect(details).to_be_visible()
        if await details.evaluate("dialog => dialog.scrollWidth > dialog.clientWidth"):
            found.append("the details of code-review scroll sideways")
        await someone.page.keyboard.press("Escape")
        problems += [f"{width}px {problem}" for problem in found]

    assert problems == []
    assert dimitris.console_errors == someone.console_errors == []

    # On a phone, the place you are in the path and who you are are read in full.
    page = someone.page
    await page.goto(f"{someone.base_url}/app#/t/{LONG_TEAM}/members")
    here = page.get_by_role("navigation", name="You are here").get_by_text("Members")
    await expect(here).to_be_visible()
    assert await here.evaluate("node => node.scrollWidth <= node.clientWidth")
    await page.get_by_role("button", name="Open navigation").click()
    await expect(page.get_by_title(f"{LONG_FULL_NAME} ({LONG_USERNAME})")).to_be_visible()


@_SQLITE_ONLY
async def test_the_library_figures_are_read_in_full_on_a_phone(sign_in):
    dimitris = await sign_in("dimitris", viewport=(390, 844))

    for label in ("In your library", "Not on any computer", "Updates"):
        figure = dimitris.page.get_by_text(label, exact=True).locator("..")
        await expect(figure).to_be_visible()
        cut = await figure.evaluate(
            "tile => [...tile.children].some(line => line.scrollWidth > line.clientWidth)")
        assert not cut, label


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


@pytest.mark.parametrize("path", ["/app", "/invite/aistinv_not-a-code"])
async def test_the_pages_before_sign_in_ask_for_nothing_that_fails(browser, server_url, path):
    """Each page names its icon inline, so a browser never asks for /favicon.ico, gets a 404,
    and logs an error on every load."""
    page = await browser.new_page()
    errors = []
    page.on("console", lambda message: errors.append(message.location["url"])
            if message.type == "error" else None)

    address = server_url.removesuffix("/mcp") + path
    await page.goto(address)
    await page.get_by_role("heading", level=1).wait_for()
    await page.wait_for_load_state("networkidle")

    # The page itself answers 401 or 404 on purpose, and the browser logs that too.
    assert [url for url in errors if url != address] == []
    await page.close()


async def test_a_computer_says_where_it_came_from_and_is_renamed(sign_in):
    dimitris = await sign_in("dimitris")
    page = dimitris.page
    await _open_computer(dimitris, "desktop")
    await expect(page.get_by_text("Last synced")).to_be_visible()

    await page.get_by_role("button", name="Computer settings").click()
    dialog = page.get_by_role("dialog", name="desktop")
    await expect(dialog.get_by_text("macbook", exact=True)).to_be_visible()
    await dialog.get_by_label("Name").fill("old desktop")
    await dialog.get_by_role("button", name="Rename").click()

    await expect(dialog).to_have_count(0)
    await expect(page.get_by_text("Renamed desktop to old desktop.")).to_be_visible()
    names = [machine["name"] for machine in (await dimitris.state())["machines"]]
    assert names == ["macbook", "old desktop"]
    assert dimitris.console_errors == []


async def test_a_lost_computer_is_removed_from_its_page(sign_in):
    dimitris = await sign_in("dimitris")
    page = dimitris.page
    await _open_computer(dimitris, "desktop")

    await page.get_by_role("button", name="Computer settings").click()
    await page.get_by_role("dialog", name="desktop").get_by_role(
        "button", name="Remove this computer…").click()
    confirm = page.get_by_role("dialog", name="Remove desktop?")
    await expect(confirm.get_by_text("Its connection to AIStack stops at once")).to_be_visible()
    await confirm.get_by_role("button", name="Remove", exact=True).click()

    await expect(page.get_by_role("heading", name="Library", level=1)).to_be_visible()
    await expect(page.get_by_role("navigation", name="Main").get_by_role(
        "link", name="desktop / Claude Code")).to_have_count(0)
    assert [machine["name"] for machine in (await dimitris.state())["machines"]] == ["macbook"]
    assert dimitris.console_errors == []


# What a keyboard and a screen reader meet. Each test walks several screens in one tab, so the
# whole set costs a few seconds and needs no second database.

_AXE_ROUTES = ("#/library", "#/f/{macbook}/claude_code", "#/t/aistack/skills",
               "#/t/aistack/members", "#/t/aistack/groups", "#/t/aistack/settings",
               "#/settings", "#/storage")


async def _axe_violations(page) -> list[str]:
    from axe_playwright_python.async_playwright import Axe

    result = await Axe().run(page)
    return [f"{rule['id']}: {[node['target'] for node in rule['nodes']]}"
            for rule in result.response["violations"]]


async def _macbook(opened) -> str:
    return next(machine["id"] for machine in (await opened.state())["machines"]
                if machine["name"] == "macbook")


@_SQLITE_ONLY
async def test_axe_finds_nothing_on_any_screen_in_either_theme_or_on_a_phone(sign_in):
    problems = {}
    dimitris = await sign_in("dimitris")
    page = dimitris.page
    macbook = await _macbook(dimitris)
    # Measure settled theme colours, rather than an intermediate transition.
    await page.emulate_media(reduced_motion="reduce")
    for viewport, scheme in (((1280, 900), "light"), ((1280, 900), "dark"), ((390, 844), "light")):
        await page.set_viewport_size({"width": viewport[0], "height": viewport[1]})
        await page.evaluate("theme => window.appearance.set({theme})", scheme)
        for route in _AXE_ROUTES:
            await page.goto(f"{dimitris.base_url}/app{route.format(macbook=macbook)}")
            await expect(page.get_by_role("heading", level=1)).to_be_visible()
            problems[(viewport[0], scheme, route)] = await _axe_violations(page)
        if viewport[0] == 390:
            await page.get_by_role("button", name="Open navigation").click()
            problems[(390, scheme, "drawer")] = await _axe_violations(page)
            await page.keyboard.press("Escape")
        else:
            # A confirmation, and a switch that cannot be turned because a group above is off.
            await page.goto(f"{dimitris.base_url}/app#/t/aistack/skills")
            await page.get_by_role("switch", name="Subscribed to developers", exact=True).click()
            await expect(page.get_by_role("switch", name="Subscribed to developers/backend")
                         ).to_have_attribute("aria-disabled", "true")
            problems[(1280, scheme, "switch off through a group")] = await _axe_violations(page)
            await page.get_by_role("switch", name="Subscribed to developers", exact=True).click()
            await page.goto(f"{dimitris.base_url}/app#/t/aistack/settings")
            await page.get_by_role("button", name="Leave team").click()
            await expect(page.get_by_role("dialog")).to_be_visible()
            problems[(1280, scheme, "confirm")] = await _axe_violations(page)
    assert {where: found for where, found in problems.items() if found} == {}


@_SQLITE_ONLY
async def test_a_keyboard_skips_to_the_page_and_lands_on_each_new_page_s_heading(sign_in):
    dimitris = await sign_in("dimitris")
    page = dimitris.page

    await page.keyboard.press("Tab")
    skip = page.get_by_role("link", name="Skip to content")
    await expect(skip).to_be_focused()
    await page.keyboard.press("Enter")
    await expect(page.get_by_role("main")).to_be_focused()
    await page.keyboard.press("Tab")
    await expect(page.get_by_role("searchbox", name="Search your library")).to_be_focused()
    assert await page.get_by_role("searchbox", name="Search your library").get_attribute(
        "aria-keyshortcuts") == "/"

    await page.get_by_role("navigation", name="Main").get_by_role("link", name="Settings").focus()
    await page.keyboard.press("Enter")
    await expect(page.get_by_role("heading", name="Settings", level=1)).to_be_focused()
    assert await page.title() == "Settings, AIStack"

    titles = {}
    for tab in ("skills", "members", "groups", "settings"):
        await page.goto(f"{dimitris.base_url}/app#/t/aistack/{tab}")
        await expect(page.get_by_role("heading", level=1)).to_be_visible()
        titles[tab] = await page.title()
    assert titles == {"skills": "Skills, aistack, AIStack", "members": "Members, aistack, AIStack",
                      "groups": "Groups, aistack, AIStack",
                      "settings": "Team settings, aistack, AIStack"}
    await page.goto(f"{dimitris.base_url}/app#/t/aistack/members")
    await expect(page.get_by_role("button", name="Remove alex from aistack…")).to_have_text("Remove…")
    assert dimitris.console_errors == []


@_SQLITE_ONLY
async def test_tables_read_cell_by_cell_and_name_which_row_each_button_is_for(sign_in):
    maria = await sign_in("maria")
    page = maria.page
    await expect(page.get_by_role("button", name="Take update to code-review")).to_be_visible()
    await expect(page.get_by_role("button", name="Add to computer: sql-style")).to_be_visible()
    shapes = {}
    for route in ("#/library", "#/t/aistack/skills", "#/t/aistack/members"):
        await page.goto(f"{maria.base_url}/app{route}")
        await expect(page.get_by_role("table").first).to_be_visible()
        shapes[route] = await page.get_by_role("table").first.evaluate("""table => {
            const rows = [...table.querySelectorAll('[role=row]')];
            const width = row => [...row.querySelectorAll('[role=cell], [role=columnheader]')]
                .reduce((n, cell) => n + Number(cell.getAttribute('aria-colspan') || 1), 0);
            const names = [...table.querySelectorAll('button')]
                .map(b => b.getAttribute('aria-label') || b.textContent.trim());
            return { widths: [...new Set(rows.map(width))],
                     repeated: names.filter((n, i) => names.indexOf(n) !== i) };
        }""")
    assert all(len(shape["widths"]) == 1 for shape in shapes.values()), shapes
    assert all(shape["repeated"] == [] for shape in shapes.values()), shapes
    await expect(page.get_by_role("row").filter(has_text="dimitris").get_by_role("cell").first
                 ).to_have_accessible_name("dimitris Dimitris Christopoulos")

    # Taking the update takes its button away; focus goes to that skill, not to the page.
    await page.goto(f"{maria.base_url}/app#/library")
    await page.get_by_role("button", name="Take update to code-review").click()
    await page.get_by_role("dialog").get_by_role("button", name="Take update").click()
    await expect(page.get_by_role("button", name="code-review", exact=True)).to_be_focused()
    assert maria.console_errors == []


@_SQLITE_ONLY
async def test_a_confirmation_opens_on_cancel_and_a_held_enter_does_not_answer_it(sign_in):
    alex = await sign_in("alex")
    page = alex.page
    await page.goto(f"{alex.base_url}/app#/t/aistack/settings")

    await page.get_by_role("button", name="Leave team").focus()
    await page.keyboard.down("Enter")
    dialog = page.get_by_role("dialog", name="Leave aistack?")
    await expect(dialog.get_by_role("button", name="Cancel")).to_be_focused()
    await expect(dialog).to_have_accessible_description(
        re.compile("Skills you added to your library stay yours"))
    await page.keyboard.down("Enter")  # the same key, still held: a repeat
    await page.keyboard.up("Enter")
    assert [team["name"] for team in (await alex.state())["teams"]] == ["aistack"]

    # Back closes the dialog instead of leaving it over a page it has nothing to do with.
    await expect(dialog).to_be_visible()
    await page.go_back()
    await expect(page.get_by_role("dialog")).to_have_count(0)
    assert [team["name"] for team in (await alex.state())["teams"]] == ["aistack"]


@_SQLITE_ONLY
async def test_the_phone_drawer_keeps_focus_inside_until_it_is_closed(sign_in):
    dimitris = await sign_in("dimitris", viewport=(390, 844))
    page = dimitris.page
    await expect(page.get_by_role("link", name="Library: Server, connected")).to_be_visible()
    opener = page.get_by_role("button", name="Open navigation")

    await opener.click()
    outside = []
    for _ in range(40):
        await page.keyboard.press("Tab")
        if not await page.evaluate("!!document.activeElement.closest('aside')"):
            outside.append(await page.evaluate("document.activeElement.outerHTML.slice(0, 80)"))
    await page.keyboard.press("Escape")

    assert outside == []
    await expect(opener).to_be_focused()


@_SQLITE_ONLY
async def test_toasts_are_said_after_the_dialog_and_stay_until_dismissed(sign_in):
    dimitris = await sign_in("dimitris")
    page = dimitris.page
    await page.evaluate("""() => {
        window.toastsSeen = [];
        new MutationObserver(() => window.toastsSeen.push(!!document.querySelector('dialog[open]')))
            .observe(document.getElementById('toasts'), { childList: true });
    }""")
    await page.clock.install()

    await page.get_by_role("button", name="Add to computer: sql-style").click()
    dialog = page.get_by_role("dialog")
    await dialog.get_by_role("checkbox", name="desktop / Claude Code").check()
    await dialog.get_by_role("button", name="Save").click()
    toast = page.get_by_role("status").get_by_text("sql-style")
    await expect(toast).to_be_visible()
    assert await page.evaluate("window.toastsSeen") == [False]
    assert "desktop" in _on(await dimitris.state(), "sql-style")

    await toast.hover()
    await page.clock.fast_forward("00:20")
    await expect(toast).to_be_visible()
    await page.mouse.move(0, 0)
    # Later outcomes must not discard one that is still waiting to be read.
    for name in ("code-review", "release-notes", "commit-messages", "pentest-checklist"):
        await page.get_by_role("button", name=f"Add to computer: {name}").click()
        await page.get_by_role("dialog").get_by_role("checkbox", name="desktop / Claude Code").check()
        await page.get_by_role("dialog").get_by_role("button", name="Save").click()
    await expect(page.get_by_role("status").get_by_role("button", name="Dismiss")).to_have_count(5)
    await page.clock.fast_forward("01:00")
    await expect(toast).to_be_visible()
    dismiss = page.get_by_role("status").get_by_role("button", name="Dismiss")
    await dismiss.first.focus()
    await dismiss.first.click()
    await expect(toast).to_have_count(0)
    await expect(dismiss.first).to_be_focused()
    for _ in range(4):
        await page.keyboard.press("Enter")
    await expect(dismiss).to_have_count(0)
    await expect(page.get_by_role("heading", name="Library", level=1)).to_be_focused()

    # An error stays until it is dismissed.
    await page.route("**/api/skills/**", lambda route: route.fulfill(
        status=400, json={"error": "Nothing changed: the server said no."}))
    await page.get_by_role("button", name="Add to computer: sql-style").click()
    await page.get_by_role("dialog").get_by_role("checkbox", name="desktop / Claude Code").uncheck()
    await page.get_by_role("dialog").get_by_role("button", name="Save").click()
    await expect(page.get_by_role("dialog").get_by_text("the server said no")).to_be_visible()
    await page.keyboard.press("Escape")
    await page.goto(f"{dimitris.base_url}/app#/t/aistack/skills")
    await page.route("**/api/teams/**", lambda route: route.fulfill(
        status=400, json={"error": "Nothing changed: the server said no."}))
    await page.get_by_role("switch", name="Subscribed to developers", exact=True).click()
    error = page.get_by_role("alert").filter(has_text="the server said no")
    await expect(error).to_be_visible()
    await page.clock.fast_forward("01:00")
    await expect(error).to_be_visible()
    await error.get_by_role("button", name="Dismiss").click()
    await expect(error).to_have_count(0)


@_SQLITE_ONLY
async def test_a_switch_says_the_same_word_on_or_off_and_why_it_cannot_be_turned(sign_in):
    dimitris = await sign_in("dimitris")
    page = dimitris.page
    await page.goto(f"{dimitris.base_url}/app#/t/aistack/skills")
    parent = page.get_by_role("switch", name="Subscribed to developers", exact=True)
    child = page.get_by_role("switch", name="Subscribed to developers/backend")

    await parent.click()
    await expect(parent).to_have_attribute("aria-checked", "false")
    await expect(parent).to_have_text("Subscribed")
    await expect(child).to_have_attribute("aria-disabled", "true")
    await expect(child).to_have_accessible_description("Off through developers")
    await child.focus()
    await expect(child).to_be_focused()
    before = _team(await dimitris.state(), "aistack")["groups"]
    await page.keyboard.press("Enter")
    assert _team(await dimitris.state(), "aistack")["groups"] == before

    # Escape hides a tooltip that is in the way.
    await parent.hover()
    tip = "el => getComputedStyle(el, '::after').display"
    assert await parent.evaluate(tip) != "none"
    await page.keyboard.press("Escape")
    assert await parent.evaluate(tip) == "none"
    assert dimitris.console_errors == []


@_SQLITE_ONLY
async def test_the_pages_before_sign_in_pass_axe_and_follow_the_theme(browser, server_url, links,
                                                                       sign_in):
    """UI-17, STD-18: a language, a main landmark and the dashboard's colours in both themes,
    on the pages a newcomer or a signed-out person meets first."""
    base = server_url.removesuffix("/mcp")
    dimitris = await sign_in("dimitris")
    invite = await dimitris.page.request.post(f"{base}/api/teams/aistack/invite",
                                              headers={"X-AIStack-Request": "1"})
    code = (await invite.json())["code"]
    problems, backgrounds = {}, {}
    for scheme in ("light", "dark"):
        context = await browser.new_context(color_scheme=scheme)
        page = await context.new_page()
        for name, path in (("signed out", "/app"), ("link used", links["maria"]),
                           ("invite", f"/invite/{code}"), ("wrong invite", "/invite/aistinv_x")):
            await page.goto(path if path.startswith("http") else base + path)
            if name == "link used":
                # The seed's link for maria, spent here once, then opened by a new browser.
                await context.clear_cookies()
                await page.goto(path)
            await expect(page.get_by_role("main")).to_be_visible()
            assert await page.evaluate("document.documentElement.lang") == "en"
            problems[(scheme, name)] = await _axe_violations(page)
            backgrounds[(scheme, name)] = await page.evaluate(
                "getComputedStyle(document.body).backgroundColor")
        await context.close()

    assert {where: found for where, found in problems.items() if found} == {}
    assert {colour for (scheme, _), colour in backgrounds.items() if scheme == "dark"} == {
        "rgb(22, 23, 25)"}
