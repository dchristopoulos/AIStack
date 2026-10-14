"""The harnesses AIStack installs into: a skills folder with a name (ADR-0018).

A harness is a folder, not a program. Placing a skill in `agents` places it in every coding
agent that reads `~/.agents/skills`, which is why that entry is named after the folder and
lists who reads it. An agent that reads a folder already here is one more name in `read_by`;
a new folder is a new entry and a new `Harness` member.
"""

from dataclasses import dataclass
from typing import Literal

from aistack.commons.exceptions import ValidationError
from aistack.commons.text import loggable
from aistack.db.models.harness import Harness
from aistack.db.models.operating_system import OperatingSystem


@dataclass(frozen=True)
class HarnessEntry:
    display_name: str
    # Spelled the way a shell on that system reads it, because the agent pastes it into one.
    folders: dict[OperatingSystem, str]
    read_by: tuple[str, ...]


HARNESSES: dict[Harness, HarnessEntry] = {
    Harness.CLAUDE_CODE: HarnessEntry(
        display_name="Claude Code",
        folders={OperatingSystem.MACOS: "~/.claude/skills",
                 OperatingSystem.LINUX: "~/.claude/skills",
                 OperatingSystem.WINDOWS: "$HOME\\.claude\\skills"},
        read_by=("Claude Code",),
    ),
    Harness.AGENTS: HarnessEntry(
        display_name="Agents folder",
        folders={OperatingSystem.MACOS: "~/.agents/skills",
                 OperatingSystem.LINUX: "~/.agents/skills",
                 OperatingSystem.WINDOWS: "$HOME\\.agents\\skills"},
        read_by=("Codex", "Gemini CLI", "Kimi Code", "opencode", "Cursor",
                 "GitHub Copilot CLI", "Amp"),
    ),
}

# The keys as a tool parameter's type, so the schema shows the agent its choices. A test
# holds it equal to `Harness`.
HarnessKey = Literal["claude_code", "agents"]

# What a call that names no harness means, so a computer set up before harnesses existed
# keeps working with the sync skill it already has.
DEFAULT_HARNESS = Harness.CLAUDE_CODE


def validated_harness(harness: str | None) -> Harness:
    """The harness a caller named, or the default when they named none."""
    if harness is None:
        return DEFAULT_HARNESS
    try:
        return Harness(harness)
    except ValueError:
        allowed = ", ".join(member.value for member in Harness)
        raise ValidationError(
            f"harness must be one of {allowed}. Received: '{loggable(harness)}'."
        ) from None


def folder(harness: Harness, operating_system: OperatingSystem) -> str:
    """Where this harness's skills live on a machine with that operating system."""
    return HARNESSES[harness].folders[operating_system]
