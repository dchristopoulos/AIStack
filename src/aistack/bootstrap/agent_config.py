"""`aistack connect`: connect a coding agent to this computer's Library, the same way twice.

Setup used to have the agent assemble each edit itself: the program's full path, the order of
`claude mcp add`'s arguments, a table merged into Codex's config.toml, a hook merged into a
settings file. Each was a chance to get it wrong, and a duplicate table makes Codex's whole
config invalid. Here the installed program does them, and running it again changes nothing.

The Library's place is a credential when it is a database address, so nothing here prints it:
it goes from the environment, or the agent's existing entry, into the agent's own config.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

from aistack.bundled import SYNC_SKILL_NAME, local_sync_skill_document

SERVER_NAME = "aistack"
AGENTS = ("claude-code", "codex")

# The settings that say where the Library lives. AISTACK_HOME only when it is not the default.
PLACE_VARIABLES = ("AISTACK_LIBRARY_REPO", "AISTACK_DATABASE_URL", "AISTACK_HOME")

# What sync does without asking in Codex: comparing, listing, installing, and backing up to the
# person's own Library. Everything else still asks.
CODEX_APPROVED_TOOLS = ("sync", "list_skills", "get_skill", "push_skill")

HOOK_COMMAND = "echo AIStack: before the first task, run the sync-aistack skill."
_HOOK_ENTRY = {"matcher": "startup",
               "hooks": [{"type": "command", "command": HOOK_COMMAND, "timeout": 10}]}


class NotConnected(Exception):
    """A sentence for the person: what is missing, and what to do."""


def skills_folder(agent: str) -> Path:
    return Path.home() / (".claude" if agent == "claude-code" else ".agents") / "skills"


def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")


def configured_place(agent: str) -> dict[str, str]:
    """The place settings the agent already starts AIStack with, or {} when it has no entry."""
    if agent == "claude-code":
        config = _read_json(Path.home() / ".claude.json")
        server = config.get("mcpServers", {}).get(SERVER_NAME, {})
    else:
        config = _read_toml(codex_home() / "config.toml")
        server = config.get("mcp_servers", {}).get(SERVER_NAME, {})
    environment = server.get("env") or {}
    return {name: str(environment[name]) for name in PLACE_VARIABLES if name in environment}


def has_entry(agent: str) -> bool:
    if agent == "claude-code":
        return SERVER_NAME in _read_json(Path.home() / ".claude.json").get("mcpServers", {})
    return SERVER_NAME in _read_toml(codex_home() / "config.toml").get("mcp_servers", {})


def place_from_environment() -> dict[str, str]:
    return {name: os.environ[name] for name in PLACE_VARIABLES if os.environ.get(name)}


def installed_program() -> Path:
    """The full path of the running command. An agent started from a desktop app may not have
    uv's folder on its path, so the entry names the program by its full path."""
    program = Path(shutil.which(sys.argv[0]) or sys.argv[0]).resolve()
    if not program.is_file() and program.with_suffix(".exe").is_file():
        program = program.with_suffix(".exe")
    return program


def write_sync_skill(folder: Path) -> Path:
    target = folder / SYNC_SKILL_NAME / "SKILL.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(local_sync_skill_document(), encoding="utf-8", newline="\n")
    return target


def connect_claude_code(program: Path, place: dict[str, str], run=subprocess.run) -> None:
    claude = shutil.which("claude")
    if claude is None:
        raise NotConnected("The `claude` command was not found. Run this from a terminal where "
                           "`claude --version` works.")
    # Replacing an entry is remove then add; a missing one makes remove fail, which is fine.
    run([claude, "mcp", "remove", "--scope", "user", SERVER_NAME],
        capture_output=True, text=True)
    # The name comes before -e: `-e` takes every value after it, the name included.
    command = [claude, "mcp", "add", "--scope", "user", SERVER_NAME]
    for name, value in place.items():
        command += ["-e", f"{name}={value}"]
    command += ["--", str(program)]
    done = run(command, capture_output=True, text=True)
    if done.returncode != 0:
        # Claude Code's own message, with any value it repeats hidden: a database address
        # holds a password.
        reason = (done.stderr or "").strip()
        for value in place.values():
            reason = reason.replace(value, "<hidden>")
        raise NotConnected(f"`claude mcp add` failed: {reason[-300:]}")


def codex_block(program: Path, place: dict[str, str]) -> str:
    lines = [f"[mcp_servers.{SERVER_NAME}]", f"command = {_toml_string(str(program))}"]
    if place:
        pairs = ", ".join(f"{name} = {_toml_string(value)}" for name, value in place.items())
        lines.append(f"env = {{ {pairs} }}")
    # Time to read a large Library on its first start; Codex otherwise gives up in seconds.
    lines.append("startup_timeout_sec = 60")
    lines += [f'tools.{tool}.approval_mode = "approve"' for tool in CODEX_APPROVED_TOOLS]
    return "\n".join(lines) + "\n"


def connect_codex(program: Path, place: dict[str, str]) -> None:
    path = codex_home() / "config.toml"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    _read_toml(path)  # refuses a file that is not valid TOML before anything changes
    kept = _without_server_tables(text)
    try:
        if SERVER_NAME in tomllib.loads(kept).get("mcp_servers", {}):
            raise NotConnected(f"{path} sets `mcp_servers.{SERVER_NAME}` in a way this cannot "
                               "replace safely. Remove those lines, then run this again.")
    except tomllib.TOMLDecodeError as error:
        raise NotConnected(f"{path} would not stay valid TOML ({error}). Nothing was "
                           "changed.") from error
    updated = (kept.rstrip("\n") + "\n\n" if kept.strip() else "") + codex_block(program, place)
    tomllib.loads(updated)
    if updated != text:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(updated, encoding="utf-8")


def add_session_start_hook(agent: str) -> Path:
    """Add the SessionStart hook that reminds the agent to sync, once, keeping everything else."""
    path = (Path.home() / ".claude" / "settings.json" if agent == "claude-code"
            else codex_home() / "hooks.json")
    settings = _read_json(path)
    entries = settings.setdefault("hooks", {}).setdefault("SessionStart", [])
    present = any(hook.get("command") == HOOK_COMMAND
                  for entry in entries if isinstance(entry, dict)
                  for hook in entry.get("hooks", []) if isinstance(hook, dict))
    if not present:
        entries.append(_HOOK_ENTRY)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    return path


def _without_server_tables(text: str) -> str:
    """config.toml without the `[mcp_servers.aistack]` table and its subtables."""
    header = re.compile(r"\s*\[\[?\s*([^\]]+?)\s*\]\]?\s*(#.*)?$")
    ours = re.compile(rf"""mcp_servers\s*\.\s*(?:{SERVER_NAME}|"{SERVER_NAME}"|'{SERVER_NAME}')"""
                      r"(\s*\..*)?$")
    kept, skipping = [], False
    for line in text.splitlines(keepends=True):
        found = header.match(line)
        if found:
            skipping = bool(ours.match(found.group(1)))
        if not skipping:
            kept.append(line)
    return "".join(kept)


def _toml_string(value: str) -> str:
    # A TOML basic string: JSON's escapes are a subset TOML reads the same way.
    return json.dumps(value)


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8") or "{}")
    except json.JSONDecodeError as error:
        raise NotConnected(f"{path} is not valid JSON ({error.msg}, line {error.lineno}). "
                           "Fix it, then run this again. Nothing was changed.") from error
    if not isinstance(value, dict):
        raise NotConnected(f"{path} does not hold a JSON object. Nothing was changed.")
    return value


def _read_toml(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        raise NotConnected(f"{path} is not valid TOML ({error}). Fix it, then run this again. "
                           "Nothing was changed.") from error
