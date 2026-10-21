"""Where each coding agent reads its rules (ADR-0036).

One table, read by the page and the program alike. Paths under the home folder are written
from it (`~/`) and paths in a repository are relative to its top level, always with forward
slashes. Research: docs/research/coding-agent-config-layout.md.
"""

from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath

from aistack.db.models.coding_agent import CodingAgent


class TurnOff(StrEnum):
    """How a repository's file is turned off for one person, without touching the file."""

    # Listed in `claudeMdExcludes` in the project's `.claude/settings.local.json`.
    CLAUDE_MD_EXCLUDES = "claude_md_excludes"
    # Left out of the `AGENTS.override.md` the program writes, which Codex reads instead.
    LEFT_OUT_OF_OVERRIDE = "left_out_of_override"


@dataclass(frozen=True)
class Fallback:
    """A repository file the agent reads only while none of `unless` exists."""

    path: str
    unless: tuple[str, ...]


@dataclass(frozen=True)
class AgentFiles:
    display_name: str
    # Its file for every project, under the home folder, or None where it keeps those rules
    # somewhere that is not a file (Cursor keeps them in the app's settings).
    every_project: str | None
    # Patterns, relative to the top level, of the files it reads in a repository. `**`
    # matches any number of folders, none included.
    repository: tuple[str, ...]
    fallback: Fallback | None
    # Where a person's own rule for a project goes, with `{name}` for the rule's name, or
    # None where AIStack does not write one.
    personal_project_rule: str | None
    turn_off: TurnOff | None
    # Why the switch is unavailable, shown on the page when `turn_off` is None.
    no_turn_off_reason: str | None
    # Whether AIStack writes rules for it in v1. The others' files are shown only.
    writes_rules: bool
    # The most it reads from one project's files, in bytes, when it has a limit.
    project_read_limit: int | None = None


_NOT_WRITTEN = "AIStack does not manage this agent's settings yet."

AGENT_FILES: dict[CodingAgent, AgentFiles] = {
    CodingAgent.CLAUDE_CODE: AgentFiles(
        display_name="Claude Code",
        every_project="~/.claude/CLAUDE.md",
        # `**/CLAUDE.md` takes in `.claude/CLAUDE.md` too.
        repository=("**/CLAUDE.md", ".claude/rules/**/*.md"),
        # Claude Code reads AGENTS.md only while no CLAUDE.md is there, which is why AIStack
        # never writes CLAUDE.local.md.
        fallback=Fallback("AGENTS.md", unless=("CLAUDE.md", ".claude/CLAUDE.md",
                                               "CLAUDE.local.md")),
        personal_project_rule=".claude/rules/aistack-{name}.md",
        turn_off=TurnOff.CLAUDE_MD_EXCLUDES,
        no_turn_off_reason=None,
        writes_rules=True,
    ),
    CodingAgent.CODEX: AgentFiles(
        display_name="Codex",
        every_project="~/.codex/AGENTS.md",
        repository=("**/AGENTS.override.md", "**/AGENTS.md"),
        fallback=None,
        # One file per folder: the repository's AGENTS.md followed by the person's rules.
        personal_project_rule="AGENTS.override.md",
        turn_off=TurnOff.LEFT_OUT_OF_OVERRIDE,
        no_turn_off_reason=None,
        writes_rules=True,
        project_read_limit=32 * 1024,
    ),
    CodingAgent.GEMINI_CLI: AgentFiles(
        display_name="Gemini CLI",
        every_project="~/.gemini/GEMINI.md",
        repository=("**/GEMINI.md",),
        fallback=None,
        personal_project_rule=None,
        turn_off=None,
        no_turn_off_reason=_NOT_WRITTEN,
        writes_rules=False,
    ),
    CodingAgent.CURSOR: AgentFiles(
        display_name="Cursor",
        every_project=None,
        repository=(".cursor/rules/**/*.mdc", "**/AGENTS.md", "CLAUDE.md"),
        fallback=None,
        personal_project_rule=None,
        turn_off=None,
        no_turn_off_reason=_NOT_WRITTEN,
        writes_rules=False,
    ),
    CodingAgent.COPILOT_CLI: AgentFiles(
        display_name="GitHub Copilot CLI",
        every_project="~/.copilot/copilot-instructions.md",
        repository=(".github/copilot-instructions.md", ".github/instructions/**/*.md",
                    "AGENTS.md", "CLAUDE.md", "GEMINI.md"),
        fallback=None,
        personal_project_rule=None,
        turn_off=None,
        no_turn_off_reason=_NOT_WRITTEN,
        writes_rules=False,
    ),
    CodingAgent.OPENCODE: AgentFiles(
        display_name="opencode",
        every_project="~/.config/opencode/AGENTS.md",
        repository=("AGENTS.md",),
        fallback=Fallback("CLAUDE.md", unless=("AGENTS.md",)),
        personal_project_rule=None,
        turn_off=None,
        no_turn_off_reason=_NOT_WRITTEN,
        writes_rules=False,
    ),
}


def writes_rules(agent: CodingAgent) -> bool:
    return AGENT_FILES[agent].writes_rules


def agents_writing_rules() -> tuple[CodingAgent, ...]:
    """The agents AIStack writes rules for, in the table's order."""
    return tuple(agent for agent, files in AGENT_FILES.items() if files.writes_rules)


def personal_project_rule_path(agent: CodingAgent, name: str) -> str | None:
    """Where this agent reads the person's rule `name` for a project, relative to its top
    level. The caller has validated `name`."""
    pattern = AGENT_FILES[agent].personal_project_rule
    return None if pattern is None else pattern.format(name=name)


def _matches(path: str, pattern: str) -> bool:
    return PurePosixPath(path).full_match(pattern)


def files_read(agent: CodingAgent, tracked: list[str]) -> list[str]:
    """Which of a repository's files, as git lists them, this agent reads, in their order."""
    files = AGENT_FILES[agent]
    read = [path for path in tracked
            if any(_matches(path, pattern) for pattern in files.repository)]
    fallback = files.fallback
    if (fallback is not None and fallback.path in tracked
            and not any(path in tracked for path in fallback.unless)
            and fallback.path not in read):
        read.append(fallback.path)
    return read


def readers(path: str, tracked: list[str]) -> tuple[CodingAgent, ...]:
    """The agents that read this repository file, given every file git tracks there."""
    return tuple(agent for agent in AGENT_FILES if path in files_read(agent, tracked))


def all_readers(tracked: list[str]) -> dict[str, tuple[CodingAgent, ...]]:
    """`readers` of every file at once, for the files some agent reads."""
    read = {agent: set(files_read(agent, tracked)) for agent in AGENT_FILES}
    found = {path: tuple(agent for agent in AGENT_FILES if path in read[agent])
             for path in tracked}
    return {path: agents for path, agents in found.items() if agents}
