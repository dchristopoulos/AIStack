"""Rules on the dashboard (ADR-0036): the routes and what /api/state shows of them."""

import pytest
from sqlalchemy import select

from aistack.bootstrap.context import application_context
from aistack.db.models.project_file import ProjectFile
from aistack.services.content_hash import text_hash
from tests.api.test_dashboard_over_http import _browser, _call, _join, _post, _state

pytestmark = pytest.mark.anyio

HERE = {"path": "/Users/dimitris/code/aistack",
        "remote": "git@github.com:dchristopoulos/AIStack.git"}
KEY = "github.com/dchristopoulos/aistack"
SECRET = "ghp_" + "a" * 36


async def test_a_rule_is_kept_edited_and_shown(server_url):
    laptop = await _join(server_url, "dimitris")
    async with _browser(server_url, laptop) as browser:
        created = await _post(browser, "/rules", name="house-style", text="# Style\n",
                              agents=["claude_code", "codex"])
        edited = await _post(browser, "/rules/house-style/edit", text="# Style\n- Short.\n")
        text = await browser.get("/api/rules/house-style/text")
        state = await _state(browser)

    assert created.status_code == 200, created.text
    assert created.json() == {"name": "house-style", "saved": True, "credential_lines": [],
                              "revision": 1, "unchanged": False}
    assert edited.json()["revision"] == 2
    assert text.json() == {"name": "house-style", "project": None, "revision": 2,
                           "text": "# Style\n- Short.\n", "credential_lines": []}
    assert [(rule["name"], rule["agents"], rule["revision"]) for rule in state["rules"]] == [
        ("house-style", ["claude_code", "codex"], 2)]


async def test_a_rule_that_looks_like_a_credential_needs_a_confirmation(server_url):
    laptop = await _join(server_url, "dimitris")
    async with _browser(server_url, laptop) as browser:
        warned = await _post(browser, "/rules", name="keys", text=f"one\n{SECRET}\n")
        before = await _state(browser)
        saved = await _post(browser, "/rules", name="keys", text=f"one\n{SECRET}\n",
                            confirmed=True)
        after = await _state(browser)

    assert warned.status_code == 200
    assert (warned.json()["saved"], warned.json()["credential_lines"]) == (False, [2])
    assert before["rules"] == []
    assert (saved.json()["saved"], saved.json()["credential_lines"]) == (True, [2])
    assert [rule["name"] for rule in after["rules"]] == ["keys"]


async def test_a_64_kib_rule_fits_in_the_body_and_a_bigger_one_says_its_size(server_url):
    laptop = await _join(server_url, "dimitris")
    async with _browser(server_url, laptop) as browser:
        # Control characters are six bytes each in JSON, so this body is 384 KiB.
        fits = await _post(browser, "/rules", name="full", text="\x01" * (64 * 1024))
        too_big = await _post(browser, "/rules", name="big", text="x" * (64 * 1024 + 1))

    assert fits.status_code == 200, fits.text
    assert too_big.status_code == 400
    assert "65537 bytes" in too_big.json()["error"]


async def test_rename_agents_and_remove(server_url):
    laptop = await _join(server_url, "dimitris")
    async with _browser(server_url, laptop) as browser:
        await _post(browser, "/rules", name="house-style", text="a")
        renamed = await _post(browser, "/rules/house-style/rename", new_name="style")
        agents = await _post(browser, "/rules/style/agents", agents=["codex"])
        refused = await _post(browser, "/rules/style/agents", agents=["cursor"])
        removed = await _post(browser, "/rules/style/remove")
        state = await _state(browser)

    assert renamed.json()["name"] == "style"
    assert agents.json()["agents"] == ["codex"]
    assert refused.status_code == 400 and "cursor" in refused.json()["error"]
    assert removed.json()["name"] == "style"
    assert state["rules"] == []


async def test_a_projects_rules_travel_with_its_key(server_url):
    laptop = await _join(server_url, "dimitris")
    await _call(server_url, laptop, "sync", local={}, here=HERE, project=KEY)
    async with _browser(server_url, laptop) as browser:
        created = await _post(browser, "/rules", name="billing", text="a", project=KEY,
                              agents=["claude_code"])
        text = await browser.get("/api/rules/billing/text", params={"project": KEY})
        state = await _state(browser)

    assert created.status_code == 200, created.text
    assert text.json()["project"] == KEY
    assert [(rule["name"], rule["project"]) for rule in state["rules"]] == [("billing", KEY)]


async def test_another_persons_rules_are_out_of_reach(server_url):
    dimitris = await _join(server_url, "dimitris")
    await _call(server_url, dimitris, "sync", local={}, here=HERE, project=KEY)
    maria = await _join(server_url, "maria")
    async with _browser(server_url, dimitris) as browser:
        await _post(browser, "/rules", name="house-style", text="mine")
    async with _browser(server_url, maria) as browser:
        text = await browser.get("/api/rules/house-style/text")
        edit = await _post(browser, "/rules/house-style/edit", text="theirs")
        in_project = await _post(browser, "/rules", name="x", text="a", project=KEY)
        state = await _state(browser)

    assert text.status_code == edit.status_code == in_project.status_code == 404
    assert state["rules"] == []


async def test_a_change_without_the_dashboards_header_is_refused(server_url):
    laptop = await _join(server_url, "dimitris")
    async with _browser(server_url, laptop) as browser:
        refused = await browser.post("/api/rules", json={"name": "x", "text": "a"})
        state = await _state(browser)

    assert refused.status_code == 400
    assert state["rules"] == []


async def test_a_projects_files_are_ticked_turned_off_and_edited_for_one_computer(server_url):
    laptop = await _join(server_url, "dimitris")
    await _call(server_url, laptop, "sync", local={}, here=HERE)
    await _call(server_url, laptop, "sync", local={}, here=HERE, project=KEY,
                repository=["release"],
                project_files=[{"path": "AGENTS.md", "size": 6},
                               {"path": "README.md", "size": 3}])
    with application_context.get_session_factory().begin() as session:
        row = session.scalar(select(ProjectFile).where(ProjectFile.path == "AGENTS.md"))
        row.text, row.content_hash = "Rules\n", text_hash("Rules\n")
    async with _browser(server_url, laptop) as browser:
        state = await _state(browser)
        machine = state["this_computer"]
        ticked = await _post(browser, "/projects/files/tick", project=KEY, path="README.md",
                             ticked=True)
        off = await _post(browser, "/projects/files/turn-off", project=KEY, path="AGENTS.md",
                          turned_off=True)
        stale = await _post(browser, "/projects/files/edit", project=KEY, path="AGENTS.md",
                            text="New\n", base_hash=text_hash("Old\n"), machine=machine)
        edited = await _post(browser, "/projects/files/edit", project=KEY, path="AGENTS.md",
                             text="New\n", base_hash=text_hash("Rules\n"), machine=machine)
        early = await _post(browser, "/projects/files/commit", project=KEY, path="AGENTS.md",
                            note="Why")
        after = await _state(browser)

    assert [(f["path"], f["ticked"], f["agents"]) for f in state["project_files"]] == [
        # Claude Code reads AGENTS.md while the repository has no CLAUDE.md.
        ("AGENTS.md", True, ["claude_code", "codex", "cursor", "copilot_cli", "opencode"]),
        ("README.md", False, [])]
    assert state["machines"][0]["projects"][0]["folders"][0]["repository_skills"] == ["release"]
    assert (ticked.status_code, off.status_code, edited.status_code) == (200, 200, 200)
    assert stale.status_code == 409 and "changed since you opened it" in stale.json()["error"]
    assert early.status_code == 409
    files = {f["path"]: f for f in after["project_files"]}
    assert files["README.md"]["ticked"] and files["AGENTS.md"]["turned_off"]
    assert files["AGENTS.md"]["text"] == "Rules\n"
    assert (files["AGENTS.md"]["edit"]["text"], files["AGENTS.md"]["edit"]["machine"],
            files["AGENTS.md"]["edit"]["written_on"]) == ("New\n", machine, None)
