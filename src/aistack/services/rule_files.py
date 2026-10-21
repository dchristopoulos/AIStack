"""Rule files on this computer, read and written by `aistack sync` (ADR-0035, ADR-0036).

Where each file lives comes from `services/agent_files.py`; the server never names a path.
In a project, AIStack writes only two kinds of file, both kept out of git through
`.git/info/exclude` before the first write: Claude Code's `.claude/rules/aistack-<name>.md`
and Codex's `AGENTS.override.md`. It changes no tracked file, and nothing outside the
project's top level. A file is replaced only while it still has the content sync observed.
"""

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path, PurePosixPath

from aistack.commons.exceptions import ValidationError
from aistack.db.models.coding_agent import CodingAgent
from aistack.services import agent_files

# Codex reads one file per folder, so its personal project rules go into the override it
# reads instead of AGENTS.md: the repository's AGENTS.md, then each rule under a marker.
OVERRIDE_HEADER = ("<!-- AIStack made this file: this repository's AGENTS.md, then your own "
                   "rules for this project. Edit AGENTS.md, or your rules on the AIStack page; "
                   "every sync rewrites this file. -->")
_NAME = r"[a-z0-9]+(?:-[a-z0-9]+)*"
_SECTION = re.compile(rf"\n<!-- aistack:rule ({_NAME}) -->\n")
_CLAUDE_RULE = re.compile(rf"aistack-({_NAME})\.md")
SETTINGS_LOCAL = ".claude/settings.local.json"
_REPOSITORY_FILE = "AGENTS.md"


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def every_project_file(agent: CodingAgent, home: Path) -> Path | None:
    """This agent's file for every project, or None when the agent is not on this computer.
    Codex's lives in `CODEX_HOME` when that is set."""
    relative = PurePosixPath(agent_files.AGENT_FILES[agent].every_project.removeprefix("~/"))
    path = home.joinpath(*relative.parts)
    if agent is CodingAgent.CODEX and os.environ.get("CODEX_HOME"):
        path = Path(os.environ["CODEX_HOME"]) / relative.name
    return path if path.parent.is_dir() else None


def read(path: Path) -> bytes | None:
    try:
        return path.read_bytes() if path.is_file() else None
    except OSError:
        return None


def override_text(repository: str, sections: list[tuple[str, str]]) -> str:
    return OVERRIDE_HEADER + "\n" + repository + "".join(
        f"\n<!-- aistack:rule {name} -->\n{text}" for name, text in sections)


def parsed_override(content: bytes | None) -> dict[str, str] | None:
    """The rule sections of an override AIStack made, by name; None for any other file."""
    try:
        text = None if content is None else content.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if text is None or not text.startswith(OVERRIDE_HEADER + "\n"):
        return None
    parts = _SECTION.split(text[len(OVERRIDE_HEADER) + 1:])
    return dict(zip(parts[1::2], parts[2::2], strict=True))


def claude_rule_path(top: Path, name: str) -> Path:
    relative = agent_files.personal_project_rule_path(CodingAgent.CLAUDE_CODE, name)
    return top.joinpath(*PurePosixPath(relative).parts)


def override_path(top: Path) -> Path:
    return top / agent_files.AGENT_FILES[CodingAgent.CODEX].personal_project_rule


def claude_rules(top: Path, tracked: set[str]) -> dict[str, bytes]:
    """The person's Claude Code rule files for this project, by rule name. A file git tracks
    is the repository's, whatever its name."""
    folder = claude_rule_path(top, "x").parent
    found = {}
    if not folder.is_dir() or not inside(top, folder):
        return found
    for path in sorted(folder.iterdir()):
        match = _CLAUDE_RULE.fullmatch(path.name)
        relative = path.relative_to(top).as_posix()
        if match and relative not in tracked and not path.is_symlink():
            content = read(path)
            if content is not None:
                found[match.group(1)] = content
    return found


def inside(top: Path, path: Path) -> bool:
    """Whether `path`, with every link followed, stays within the project."""
    return path.resolve().is_relative_to(top.resolve())


def _git(top: Path, *arguments: str) -> str:
    done = subprocess.run(["git", "-C", str(top), *arguments], capture_output=True, text=True,
                          timeout=5)
    if done.returncode:
        raise ValidationError("AIStack could not read this project's git state, so no rule "
                              "file was written in it.")
    return done.stdout


def tracked(top: Path) -> set[str]:
    """The paths git tracks among those AIStack may write in a project."""
    listed = _git(top, "ls-files", "-z", "--", agent_files.AGENT_FILES[
        CodingAgent.CODEX].personal_project_rule, SETTINGS_LOCAL, ".claude/rules")
    return {path for path in listed.split("\0") if path}


def exclude(top: Path, relative: str) -> None:
    """Keep one of AIStack's files in a project out of git, before it is written."""
    entry = "/" + relative
    path = Path(_git(top, "rev-parse", "--path-format=absolute", "--git-path",
                     "info/exclude").strip())
    path.parent.mkdir(parents=True, exist_ok=True)
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    if entry not in text.splitlines():
        path.write_text(text.rstrip("\n") + ("\n" if text.strip() else "") + entry + "\n",
                        encoding="utf-8")
    _git(top, "check-ignore", "-q", relative)


def replace(path: Path, content: bytes, observed: bytes | None,
            follow_link: bool = False) -> bool:
    """Write `content` over `path` only while it still holds what sync observed; False when
    it changed meanwhile. Through a temporary file and a rename, so an agent never reads half
    a file. A link is written through to the file it names only with `follow_link`, which is
    for the person's own files under their home; in a project a link could lead anywhere."""
    if path.is_symlink() and not follow_link:
        raise ValidationError(f"{path} is a link, so AIStack did not write it.")
    if read(path) != observed:
        return False
    target = path.resolve() if path.is_symlink() else path
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.aistack-{os.getpid()}")
    try:
        temporary.write_bytes(content)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return True


def remove(path: Path, observed: bytes) -> bool:
    if read(path) != observed:
        return False
    path.unlink()
    return True


def validated_repository_path(path: object) -> str:
    """A repository file the server listed, as a path relative to the top level."""
    if (not isinstance(path, str) or not path or "\\" in path or "\0" in path
            or "\n" in path or PurePosixPath(path).is_absolute()
            or ".." in PurePosixPath(path).parts):
        raise ValidationError("The server listed a repository file that is not a path inside "
                              "the project, so its setting was left alone.")
    return path


def turn_off_for_claude(top: Path, turned: dict[str, bool]) -> bool:
    """List the files turned off in `claudeMdExcludes` of the project's settings.local.json,
    and take back those turned on again, keeping every other key and entry. True when the
    file changed."""
    path = top.joinpath(*PurePosixPath(SETTINGS_LOCAL).parts)
    content = read(path)
    try:
        settings = {} if content is None else json.loads(content)
    except ValueError:
        settings = None
    if not isinstance(settings, dict) or not isinstance(
            settings.get("claudeMdExcludes", []), list):
        raise ValidationError(f"{path} is not a settings file AIStack can read, so the files "
                              "you turned off were not turned off for Claude Code. Repair it "
                              "and sync again.")
    excludes = list(settings.get("claudeMdExcludes", []))
    for relative, off in turned.items():
        absolute = str(top.joinpath(*PurePosixPath(relative).parts))
        if off and absolute not in excludes:
            excludes.append(absolute)
        elif not off and absolute in excludes:
            excludes.remove(absolute)
    if excludes == settings.get("claudeMdExcludes", []) or (
            not excludes and "claudeMdExcludes" not in settings):
        return False
    settings["claudeMdExcludes"] = excludes
    if not inside(top, path.parent if path.parent.exists() else top):
        raise ValidationError("The project's .claude folder leads outside the project, so no "
                              "setting was written there.")
    exclude(top, SETTINGS_LOCAL)
    return replace(path, (json.dumps(settings, indent=2) + "\n").encode("utf-8"), content)


def repository_text(top: Path) -> str:
    """The repository's AGENTS.md, which Codex no longer reads once the override exists."""
    content = read(top / _REPOSITORY_FILE)
    return "" if content is None else content.decode("utf-8", errors="replace")
