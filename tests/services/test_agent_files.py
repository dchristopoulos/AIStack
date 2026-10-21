"""The table of where each coding agent reads its rules (ADR-0036)."""

from aistack.db.models.coding_agent import CodingAgent
from aistack.services import agent_files
from aistack.services.agent_files import AGENT_FILES, TurnOff


def test_every_agent_is_in_the_table():
    assert set(AGENT_FILES) == set(CodingAgent)


def test_v1_writes_rules_for_claude_code_and_codex_only():
    assert agent_files.agents_writing_rules() == (CodingAgent.CLAUDE_CODE, CodingAgent.CODEX)


def test_an_agent_aistack_writes_for_has_a_place_for_personal_rules_and_a_switch():
    for agent in agent_files.agents_writing_rules():
        files = AGENT_FILES[agent]
        assert files.every_project is not None
        assert files.personal_project_rule is not None
        assert files.turn_off is not None and files.no_turn_off_reason is None


def test_every_other_agent_says_why_its_switch_is_unavailable():
    for files in AGENT_FILES.values():
        if not files.writes_rules:
            assert files.turn_off is None and files.no_turn_off_reason


def test_the_files_for_every_project():
    assert AGENT_FILES[CodingAgent.CLAUDE_CODE].every_project == "~/.claude/CLAUDE.md"
    assert AGENT_FILES[CodingAgent.CODEX].every_project == "~/.codex/AGENTS.md"
    assert AGENT_FILES[CodingAgent.CURSOR].every_project is None


def test_a_personal_project_rule_never_stops_the_repositorys():
    # Claude Code reads AGENTS.md only while no CLAUDE.local.md exists, so never that file.
    assert agent_files.personal_project_rule_path(
        CodingAgent.CLAUDE_CODE, "house-style") == ".claude/rules/aistack-house-style.md"
    assert agent_files.personal_project_rule_path(CodingAgent.CODEX,
                                                  "house-style") == "AGENTS.override.md"
    assert agent_files.personal_project_rule_path(CodingAgent.CURSOR, "house-style") is None


def test_how_a_repository_file_is_turned_off():
    assert AGENT_FILES[CodingAgent.CLAUDE_CODE].turn_off is TurnOff.CLAUDE_MD_EXCLUDES
    assert AGENT_FILES[CodingAgent.CODEX].turn_off is TurnOff.LEFT_OUT_OF_OVERRIDE


def test_claude_code_reads_agents_md_only_without_a_claude_md():
    assert agent_files.files_read(CodingAgent.CLAUDE_CODE, ["AGENTS.md", "README.md"]) == [
        "AGENTS.md"]
    assert agent_files.files_read(CodingAgent.CLAUDE_CODE,
                                  ["AGENTS.md", "CLAUDE.md", ".claude/rules/x.md"]) == [
        "CLAUDE.md", ".claude/rules/x.md"]


def test_nested_files_and_rule_folders_are_read():
    tracked = ["AGENTS.md", "api/AGENTS.md", ".cursor/rules/style.mdc", "docs/guide.md",
               "GEMINI.md", ".github/copilot-instructions.md"]

    assert agent_files.files_read(CodingAgent.CODEX, tracked) == ["AGENTS.md", "api/AGENTS.md"]
    assert agent_files.files_read(CodingAgent.CURSOR, tracked) == [
        "AGENTS.md", "api/AGENTS.md", ".cursor/rules/style.mdc"]
    assert agent_files.files_read(CodingAgent.GEMINI_CLI, tracked) == ["GEMINI.md"]
    assert "docs/guide.md" not in agent_files.files_read(CodingAgent.COPILOT_CLI, tracked)


def test_who_reads_a_file():
    tracked = ["AGENTS.md", "CLAUDE.md"]

    assert agent_files.readers("AGENTS.md", tracked) == (
        CodingAgent.CODEX, CodingAgent.CURSOR, CodingAgent.COPILOT_CLI, CodingAgent.OPENCODE)
    assert agent_files.readers("CLAUDE.md", tracked) == (
        CodingAgent.CLAUDE_CODE, CodingAgent.CURSOR, CodingAgent.COPILOT_CLI)
    assert agent_files.readers("README.md", tracked + ["README.md"]) == ()


def test_codex_reads_at_most_32_kib_of_a_project():
    assert AGENT_FILES[CodingAgent.CODEX].project_read_limit == 32 * 1024
