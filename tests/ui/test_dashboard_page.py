"""The dashboard as a person uses it: a real browser, the real server, no demo mode.

Everything is found by role and by the words a user reads, never by a CSS class, so these
tests state what the page must let someone do and stay true when its look changes.
"""

import pytest
from playwright.async_api import expect

pytestmark = pytest.mark.anyio


async def test_a_sign_in_link_opens_my_skills_and_the_page_talks_only_to_this_server(sign_in):
    maria = await sign_in("maria")

    await expect(maria.page.get_by_role("switch", name="code-review on work-laptop")
                 ).to_be_checked()
    await expect(maria.page.get_by_role("navigation", name="Main")
                 .get_by_role("link", name="acme")).to_be_visible()
    assert "/app/login" not in maria.page.url
    assert maria.console_errors == []
    assert maria.foreign_requests == []


async def test_an_offered_update_is_taken_with_one_click(sign_in):
    maria = await sign_in("maria")
    assert [skill["source"]["update_available"] for skill in (await maria.state())["skills"]
            if skill["name"] == "code-review"] == [True]

    await maria.page.get_by_role("button", name="Take update").click()

    await expect(maria.page.get_by_role("button", name="Take update")).to_have_count(0)
    code_review = next(skill for skill in (await maria.state())["skills"]
                       if skill["name"] == "code-review")
    assert (code_review["revision"], code_review["source"]["update_available"]) == (2, False)
    assert maria.console_errors == []


async def test_a_skill_is_switched_per_computer(sign_in):
    dimitris = await sign_in("dimitris")
    desktop = dimitris.page.get_by_role("switch", name="sql-style on desktop")
    await expect(desktop).not_to_be_checked()

    await desktop.click()

    await expect(desktop).to_be_checked()
    state = await dimitris.state()
    names = {machine["id"]: machine["name"] for machine in state["machines"]}
    sql_style = next(skill for skill in state["skills"] if skill["name"] == "sql-style")
    assert sorted(names[machine] for machine in sql_style["machines"]) == ["desktop", "macbook"]


async def test_a_skill_is_shared_into_a_nested_group_from_a_dialog(sign_in):
    dimitris = await sign_in("dimitris")
    page = dimitris.page
    row = page.get_by_role("row").filter(has_text="meeting-notes")

    await row.get_by_role("button", name="Share").click()
    dialog = page.get_by_role("dialog")
    await dialog.get_by_label("Team", exact=True).select_option("acme")
    await dialog.get_by_role("radio", name="backend/aistack").check()
    await dialog.get_by_role("button", name="Share", exact=True).click()

    await expect(dialog).to_have_count(0)
    acme = next(team for team in (await dimitris.state())["teams"] if team["name"] == "acme")
    assert ("meeting-notes", "backend/aistack", "dimitris") in [
        (skill["name"], skill["group"], skill["pushed_by"]) for skill in acme["skills"]]
    assert dimitris.console_errors == []


async def test_escape_closes_a_dialog_and_gives_focus_back(sign_in):
    dimitris = await sign_in("dimitris")
    page = dimitris.page
    opener = page.get_by_role("button", name="New team")

    await opener.click()
    await expect(page.get_by_role("dialog")).to_be_visible()
    await page.keyboard.press("Escape")

    await expect(page.get_by_role("dialog")).to_have_count(0)
    await expect(opener).to_be_focused()
    assert [team["name"] for team in (await dimitris.state())["teams"]] == ["acme", "everyone"]


async def test_an_admin_makes_a_group_inside_a_group(sign_in):
    dimitris = await sign_in("dimitris")
    page = dimitris.page
    await page.get_by_role("navigation", name="Main").get_by_role("link", name="acme").click()
    await page.get_by_role("tab", name="Groups").click()

    await page.get_by_role("button", name="New group").click()
    dialog = page.get_by_role("dialog")
    await dialog.get_by_label("Name").fill("frontend")
    await dialog.get_by_role("radio", name="backend/aistack").check()
    await dialog.get_by_role("button", name="Create").click()

    await expect(dialog).to_have_count(0)
    await expect(page.get_by_role("switch", name="backend/aistack/frontend is private")
                 ).to_be_visible()
    acme = next(team for team in (await dimitris.state())["teams"] if team["name"] == "acme")
    assert "backend/aistack/frontend" in [group["path"] for group in acme["groups"]]


async def test_a_member_is_shown_no_private_group_and_no_admin_control(sign_in):
    alex = await sign_in("alex")
    page = alex.page
    await page.get_by_role("navigation", name="Main").get_by_role("link", name="acme").click()

    await expect(page.get_by_role("button", name="backend", exact=False).first).to_be_visible()
    await expect(page.get_by_text("pentest-checklist")).to_have_count(0)
    await expect(page.get_by_role("switch", name="Subscribed to security")).to_have_count(0)
    await expect(page.get_by_role("button", name="More actions for code-review")
                 ).to_have_count(0)

    await page.get_by_role("tab", name="Groups").click()
    await expect(page.get_by_role("button", name="New group")).to_have_count(0)
    await expect(page.get_by_role("switch", name="backend is private")).to_have_count(0)
    assert alex.console_errors == []


async def test_a_team_is_created_and_joined_with_its_invite_code(sign_in):
    dimitris = await sign_in("dimitris")
    page = dimitris.page
    await page.get_by_role("button", name="New team").click()
    await page.get_by_role("dialog").get_by_label("Name").fill("design")
    await page.get_by_role("dialog").get_by_role("button", name="Create").click()
    await expect(page.get_by_role("heading", name="design", level=1)).to_be_visible()

    await page.get_by_role("tab", name="Settings").click()
    await page.get_by_role("button", name="Create new invite code").click()
    # It asks first: a new code stops the previous one working.
    await page.get_by_role("dialog").get_by_role("button", name="Create new code").click()
    code = await page.get_by_role("dialog").get_by_label("Invite code").input_value()
    assert code.startswith("aistinv_") and len(code) > 20
    await page.get_by_role("dialog").get_by_role("button", name="Done").click()

    alex = await sign_in("alex")
    await alex.page.get_by_role("button", name="Join with code").click()
    await alex.page.get_by_role("dialog").get_by_label("code").fill(code.strip())
    await alex.page.get_by_role("dialog").get_by_role("button", name="Join").click()

    await expect(alex.page.get_by_role("heading", name="design", level=1)).to_be_visible()
    assert "design" in [team["name"] for team in (await alex.state())["teams"]]


async def test_signing_out_closes_the_dashboard_in_that_browser(sign_in):
    maria = await sign_in("maria")

    await maria.page.get_by_role("button", name="Sign out").click()

    await expect(maria.page.get_by_text("open my aistack dashboard")).to_be_visible()
    assert (await maria.page.request.get(f"{maria.base_url}/api/state")).status == 401


@pytest.mark.parametrize("route", ["#/mine", "#/t/acme/skills", "#/t/acme/groups",
                                   "#/t/acme/members"])
async def test_nothing_scrolls_sideways_on_a_phone(sign_in, route):
    dimitris = await sign_in("dimitris", viewport=(390, 844))

    await dimitris.page.goto(f"{dimitris.base_url}/app{route}")
    await dimitris.page.wait_for_timeout(300)

    overflow = await dimitris.page.evaluate(
        "document.documentElement.scrollWidth - window.innerWidth")
    assert overflow <= 0
    assert dimitris.console_errors == []


async def test_the_phone_menu_opens_and_closes_with_a_control_you_can_see(sign_in):
    dimitris = await sign_in("dimitris", viewport=(390, 844))
    page = dimitris.page
    navigation = page.get_by_role("navigation", name="Main")
    await expect(navigation).to_be_hidden()

    await page.get_by_role("button", name="Open navigation").click()
    await expect(navigation.get_by_role("link", name="acme")).to_be_visible()
    close = page.get_by_label("Navigation").get_by_role("button", name="Close navigation")
    await expect(close).to_be_visible()
    await close.click()

    await expect(navigation).to_be_hidden()


async def test_a_group_is_opened_from_the_sidebar_and_shows_only_what_is_in_it(sign_in):
    dimitris = await sign_in("dimitris")
    page = dimitris.page
    navigation = page.get_by_role("navigation", name="Main")

    await navigation.get_by_role("link", name="aistack").click()

    await expect(page.get_by_role("table", name="Skills in backend/aistack")).to_be_visible()
    await expect(page.get_by_text("aistack-api-notes")).to_be_visible()
    await expect(page.get_by_text("sql-style")).to_have_count(0)
    assert page.url.endswith("#/t/acme/skills/backend/aistack")

    await page.reload()
    await expect(page.get_by_role("table", name="Skills in backend/aistack")).to_be_visible()

    await page.get_by_role("link", name="All of acme").click()
    await expect(page.get_by_text("sql-style")).to_be_visible()
    assert dimitris.console_errors == []


async def test_a_folded_team_hides_its_groups_and_stays_folded_after_a_reload(sign_in):
    dimitris = await sign_in("dimitris")
    page = dimitris.page
    navigation = page.get_by_role("navigation", name="Main")
    await expect(navigation.get_by_role("link", name="security")).to_be_visible()

    await navigation.get_by_role("button", name="Groups of acme").click()
    await expect(navigation.get_by_role("link", name="security")).to_have_count(0)

    await page.reload()
    await page.get_by_role("heading", name="My skills", level=1).wait_for()
    await expect(navigation.get_by_role("link", name="security")).to_have_count(0)
    await expect(navigation.get_by_role("button", name="Groups of acme")
                 ).to_have_attribute("aria-expanded", "false")


async def test_the_sidebar_shows_a_member_no_private_group_they_are_not_in(sign_in):
    alex = await sign_in("alex")
    navigation = alex.page.get_by_role("navigation", name="Main")

    await expect(navigation.get_by_role("link", name="backend")).to_be_visible()
    await expect(navigation.get_by_role("link", name="security")).to_have_count(0)

    await alex.page.goto(f"{alex.base_url}/app#/t/acme/skills/security")
    await expect(alex.page.get_by_role("table", name="Skills in acme")).to_be_visible()
    await expect(alex.page.get_by_text("pentest-checklist")).to_have_count(0)
