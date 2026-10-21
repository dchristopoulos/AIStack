"""Rules on the page (ADR-0036, ADR-0037): the person's rules for every project and for one,
found by role and by the words a person reads, and confirmed against /api/state."""

import pytest

playwright_api = pytest.importorskip("playwright.async_api")
expect = playwright_api.expect

pytestmark = pytest.mark.anyio

KEY = "github.com/demo-team/demo-api"


def _nav(page):
    return page.get_by_role("navigation", name="Main")


async def _open(page, place: str) -> None:
    await _nav(page).get_by_role("link", name=place).click()
    await expect(page.get_by_role("heading", name=place, level=1)).to_be_visible()


async def _add_to(page, place: str, item: str) -> None:
    await _nav(page).get_by_role("button", name=f"Add to {place}").click()
    await page.get_by_role("menu", name=f"Add to {place}").get_by_role(
        "menuitem", name=item).click()


def _rule(state, name, project=None) -> dict | None:
    return next((rule for rule in state["rules"]
                 if rule["name"] == name and rule["project"] == project), None)


async def test_a_project_table_starts_with_the_rules_in_reading_order(sign_in):
    dimitris = await sign_in("dimitris")
    page = dimitris.page
    await _open(page, "demo-api")

    table = page.get_by_role("table", name="What your agents read in demo-api")
    text = await table.inner_text()
    order = ["Your rules for every project", "house-style", "Your rules for demo-api",
             "payments", "Skills for every project"]
    assert [text.index(words) for words in order] == sorted(text.index(w) for w in order)
    # A rule for every project is changed on Every project; here its ticks are marks.
    every = table.get_by_role("row").filter(has_text="house-style")
    await expect(every.get_by_text("Claude Code gets it")).to_be_attached()
    await expect(every.get_by_role("checkbox")).to_have_count(0)

    # The project's own rule: a tick chooses the agents that use it.
    own = table.get_by_role("row").filter(has_text="payments")
    await own.get_by_role("checkbox", name="payments for Codex").check()
    await expect(page.get_by_text("Saved which agents use payments.")).to_be_visible()
    assert _rule(await dimitris.state(), "payments", KEY)["agents"] == ["claude_code", "codex"]
    assert dimitris.console_errors == []


async def test_every_project_lists_rules_and_a_computer_names_each_agents_file(sign_in):
    dimitris = await sign_in("dimitris")
    page = dimitris.page
    await _open(page, "Every project")
    table = page.get_by_role("table", name="What your agents read in every project")
    row = table.get_by_role("row").filter(has_text="house-style")
    await row.get_by_role("checkbox", name="house-style for Codex").uncheck()
    await expect(page.get_by_text("Saved which agents use house-style.")).to_be_visible()
    assert _rule(await dimitris.state(), "house-style")["agents"] == ["claude_code"]

    await _open(page, "MacBook Pro M4 Pro")
    agents = page.get_by_role("table", name="Coding agents")
    await expect(agents.get_by_role("row").filter(has_text="Claude Code").get_by_text(
        "~/.claude/CLAUDE.md")).to_be_visible()
    await expect(agents.get_by_role("row").filter(has_text="Codex").get_by_text(
        "No rule in")).to_be_visible()
    await agents.get_by_role("button", name="Open house-style").click()
    await expect(page.get_by_role("dialog", name="house-style")).to_be_visible()
    assert dimitris.console_errors == []


async def test_the_side_panel_shows_a_rule_and_edit_saves_a_revision(sign_in):
    dimitris = await sign_in("dimitris")
    page = dimitris.page
    await _open(page, "demo-api")
    await page.get_by_role("button", name="Open payments").click()

    panel = page.get_by_role("dialog", name="payments")
    await expect(panel.get_by_text("Refunds go through")).to_be_visible()
    await expect(panel.get_by_role("checkbox", name="Claude Code")).to_be_checked()
    await expect(panel.get_by_role("checkbox", name="Codex")).not_to_be_checked()
    await panel.get_by_role("button", name="Edit").click()

    editor = page.get_by_role("dialog", name="Edit payments")
    text = editor.get_by_role("textbox", name="Text")
    await expect(text).to_have_value("# Payments\n\n- Refunds go through `payments/refunds.py` "
                                     "only.\n")
    await text.fill("# Payments\n\n- Ask before touching payments/.\n")
    await editor.get_by_role("button", name="Preview").click()
    await expect(editor.get_by_role("heading", name="Payments", exact=True)).to_be_visible()
    await expect(editor.get_by_role("listitem")).to_have_text("Ask before touching payments/.")
    await editor.get_by_role("button", name="Save").click()

    await expect(page.get_by_text("Saved payments as r2.")).to_be_visible()
    assert _rule(await dimitris.state(), "payments", KEY)["revision"] == 2
    assert dimitris.console_errors == []


async def test_a_line_that_looks_like_a_credential_is_named_before_saving(sign_in):
    dimitris = await sign_in("dimitris")
    page = dimitris.page
    await _open(page, "demo-api")
    await _add_to(page, "demo-api", "A rule…")

    dialog = page.get_by_role("dialog", name="A rule for demo-api")
    await dialog.get_by_role("textbox", name="Name").fill("deploy")
    await dialog.get_by_role("textbox", name="Text").fill(
        "# Deploy\n\nUse ghp_" + "a" * 36 + " to push.\n")
    await dialog.get_by_role("button", name="Add rule").click()

    await expect(dialog.get_by_role("alert")).to_contain_text("Line 3 looks like it holds a "
                                                              "credential")
    assert _rule(await dimitris.state(), "deploy", KEY) is None
    await dialog.get_by_role("button", name="Save anyway").click()

    await expect(page.get_by_text("Added deploy.")).to_be_visible()
    rule = _rule(await dimitris.state(), "deploy", KEY)
    assert rule["agents"] == ["claude_code", "codex"]
    table = page.get_by_role("table", name="What your agents read in demo-api")
    await expect(table.get_by_role("button", name="Open deploy")).to_be_visible()
    assert dimitris.console_errors == []


async def test_a_rule_for_every_project_is_added_and_removed(sign_in):
    dimitris = await sign_in("dimitris")
    page = dimitris.page
    await _add_to(page, "every project", "A rule…")
    dialog = page.get_by_role("dialog", name="A rule for every project")
    # Both agents already have house-style as their file for every project.
    await expect(dialog.get_by_role("checkbox", name="Claude Code")).not_to_be_checked()
    await dialog.get_by_role("textbox", name="Name").fill("scratch")
    await dialog.get_by_role("textbox", name="Text").fill("Notes.\n")
    await dialog.get_by_role("button", name="Add rule").click()
    await expect(page.get_by_text("Added scratch.")).to_be_visible()
    assert _rule(await dimitris.state(), "scratch")["agents"] == []

    await _open(page, "Every project")
    await page.get_by_role("button", name="Open scratch").click()
    await page.get_by_role("dialog", name="scratch").get_by_role("button",
                                                                 name="Remove…").click()
    confirm = page.get_by_role("dialog", name="Remove scratch?")
    await expect(confirm.get_by_text("stay as they are")).to_be_visible()
    await confirm.get_by_role("button", name="Remove").click()

    await expect(page.get_by_text("Removed scratch from your Library.")).to_be_visible()
    assert _rule(await dimitris.state(), "scratch") is None
    assert dimitris.console_errors == []
