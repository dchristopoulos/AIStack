"""Local mode's sync writes rules as the program does on a server (ADR-0036, ADR-0039): each
agent's file for every project, the person's rules in each project added on this computer,
Codex's override and the files turned off, in a temporary home and repository."""

import asyncio
import json
import subprocess

import pytest
from sqlalchemy import select

from aistack.bootstrap.__main__ import session_start_is_quiet
from aistack.bootstrap.context import application_context
from aistack.db.models.rule import Rule
from aistack.services import library_log, rule_files
from tests.mcp.test_library_log import (  # noqa: F401
    SHOP,
    _call,
    _dashboard,
    _events,
    _post,
    _replayed,
    _shop,
    _snapshot,
    anyio_backend_fixture,
    computer_fixture,
)

pytestmark = pytest.mark.anyio

OWN = "# Mine\n\nAlways answer in English.\n"
STYLE = "# Style\n\nShort sentences.\n"


@pytest.fixture(autouse=True)
def no_codex_home(monkeypatch):
    monkeypatch.delenv("CODEX_HOME", raising=False)


def _git(top, *arguments):
    return subprocess.run(["git", "-C", str(top), "-c", "user.name=t",
                           "-c", "user.email=t@example.com", *arguments], check=True,
                          capture_output=True, text=True).stdout


def _rule_names():
    with application_context.get_session_factory()() as session:
        return sorted(session.scalars(select(Rule.name).where(Rule.archived.is_(False))))


async def test_rules_reach_every_file_and_project_and_replay_to_the_same_library(computer,
                                                                                 tmp_path):
    async with computer("laptop") as (laptop, home), _dashboard() as browser:
        (home / ".claude").mkdir()
        (home / ".codex").mkdir()
        claude, codex = home / ".claude/CLAUDE.md", home / ".codex/AGENTS.md"
        claude.write_text(OWN)

        # A hand-written file is kept in the Library at the first sync, without asking.
        result = await _call(laptop, "sync")
        assert any("Backed up" in line and "claude-md" in line for line in result["rule_changes"])
        assert result["rule_questions"] == [] and result["rule_failures"] == []
        assert _rule_names() == ["claude-md"]

        # Edited on the page, and used for Codex too: both agents' files follow.
        await _post(browser, "/api/rules/claude-md/edit", text=STYLE)
        await _post(browser, "/api/rules/claude-md/agents", agents=["claude_code", "codex"])
        await _call(laptop, "sync")
        assert claude.read_text() == STYLE and codex.read_text() == STYLE

        # A project added on this computer gets its rules, kept out of git.
        top = _shop(home)
        await _post(browser, "/api/projects/add", folder=str(top), ticked=["AGENTS.md"])
        await _post(browser, "/api/rules", name="tests", text="Run the tests.\n",
                    agents=["claude_code", "codex"], project=SHOP)
        await _post(browser, "/api/projects/files/turn-off", project=SHOP, path="CLAUDE.md",
                    turned_off=True)
        result = await _call(laptop, "sync")
        assert result["rule_failures"] == []
        assert (top / ".claude/rules/aistack-tests.md").read_text() == "Run the tests.\n"
        override = (top / "AGENTS.override.md").read_text()
        assert override.startswith(rule_files.OVERRIDE_HEADER)
        assert "# Shop" in override and "Run the tests." in override
        settings = json.loads((top / ".claude/settings.local.json").read_text())
        assert settings["claudeMdExcludes"] == [str(top / "CLAUDE.md")]
        assert _git(top, "status", "--porcelain") == ""

        # Edited here and on the page: a question, keyed by the project, then the answer.
        rule = top / ".claude/rules/aistack-tests.md"
        rule.write_text("Run the tests twice.\n")
        await _post(browser, "/api/rules/tests/edit", text="Run all the tests.\n",
                    project=SHOP)
        result = await _call(laptop, "sync")
        [question] = result["rule_questions"]
        key = f"{SHOP}:project:claude_code:tests"
        assert question["key"] == key and question["file"] == str(rule)
        assert rule.read_text() == "Run the tests twice.\n"
        result = await _call(laptop, "sync", rule_choices={key: "push"})
        assert result["rule_questions"] == [] and result["rule_failures"] == []
        assert rule.read_text() == "Run the tests twice.\n"
        # Codex's part of the override follows the text kept.
        await _call(laptop, "sync")
        assert "Run the tests twice." in (top / "AGENTS.override.md").read_text()

        with application_context.get_session_factory().begin() as session:
            built, events = _snapshot(session), _events(session)

    kinds = [event.kind for event in events]
    assert library_log.RULE_CREATED in kinds and library_log.RULE_EDITED in kinds
    assert _replayed(tmp_path, events) == built


async def test_a_file_the_repository_tracks_is_never_written(computer):
    async with computer("laptop") as (laptop, home), _dashboard() as browser:
        (home / ".claude").mkdir()
        top = _shop(home)
        tracked = top / ".claude/rules/aistack-tests.md"
        tracked.parent.mkdir(parents=True)
        tracked.write_text("The repository's own.\n")
        _git(top, "add", ".claude")
        _git(top, "commit", "-qm", "rules")
        await _post(browser, "/api/projects/add", folder=str(top), ticked=[])
        await _post(browser, "/api/rules", name="tests", text="Mine.\n",
                    agents=["claude_code"], project=SHOP)

        result = await _call(laptop, "sync")

        assert any("The repository holds .claude/rules/aistack-tests.md" in line
                   for line in result["rule_failures"])
        assert tracked.read_text() == "The repository's own.\n"
        assert _git(top, "status", "--porcelain") == ""


async def test_the_session_start_hook_writes_a_rule_edited_on_the_page(computer):
    async with computer("laptop") as (laptop, home), _dashboard() as browser:
        (home / ".claude" / "skills").mkdir(parents=True)
        (home / ".claude/CLAUDE.md").write_text(OWN)
        await _call(laptop, "sync")
        assert await asyncio.to_thread(session_start_is_quiet)

        await _post(browser, "/api/rules/claude-md/edit", text=STYLE)
        assert await asyncio.to_thread(session_start_is_quiet)
        assert (home / ".claude/CLAUDE.md").read_text() == STYLE

        # Edited here and on the page: only a question needs the agent.
        (home / ".claude/CLAUDE.md").write_text("By hand.\n")
        await _post(browser, "/api/rules/claude-md/edit", text=OWN)
        assert not await asyncio.to_thread(session_start_is_quiet)
        assert (home / ".claude/CLAUDE.md").read_text() == "By hand.\n"
