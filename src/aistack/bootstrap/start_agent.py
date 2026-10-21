"""`aistack start`: a coding agent in a project with only the chosen skills, for one session.

Neither agent has an allowlist, so each recipe turns off by name every other skill the agent
would load there, built from a scan of the folders at that moment (ADR-0038). Nothing is
written to the person's settings: the recipe is command-line flags, and their login, rules
and MCP servers stay as they are. The command says what it will start and waits for Enter
before it does, so a link or a page never starts anything on its own.
"""

import argparse
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

from aistack.bootstrap import agent_config
from aistack.commons.exceptions import AIStackError, ValidationError
from aistack.commons.text import loggable
from aistack.services import projects
from aistack.services.skill_validation import validated_skill_name


class StartRefused(AIStackError):
    """Why nothing was started, and what to do about it."""


@dataclass(frozen=True)
class Launch:
    program: str
    version: tuple[int, ...]
    folder: Path
    chosen: tuple[str, ...]
    # Every skill name the scan found where this agent loads skills from.
    on_disk: frozenset[str]


@dataclass(frozen=True)
class Prepared:
    command: list[str]
    turned_off: list[str]
    # Removed once the agent exits, where the process waits for it (Windows).
    files: list[Path]


@dataclass(frozen=True)
class Recipe:
    display_name: str
    program: str
    minimum: tuple[int, ...]
    # (home, project folder) -> skill names on disk the agent would load there.
    scan: Callable[[Path, Path], set[str]]
    prepare: Callable[[Launch, Callable], Prepared]
    note: str


def run(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(
        prog="aistack start",
        description="Start a coding agent in a project with only the chosen skills, for this "
                    "one session. Nothing in your settings changes.")
    parser.add_argument("--agent", required=True, choices=list(RECIPES))
    parser.add_argument("--project",
                        help="The project: its folder, or its key. The current folder's "
                             "project by default")
    parser.add_argument("--skills", required=True,
                        help="The skills to keep, by name, separated by commas")
    parser.add_argument("--new-terminal", action="store_true",
                        help="Run this in a new terminal window instead of this one")
    parser.add_argument("--yes", action="store_true", help=argparse.SUPPRESS)
    arguments = parser.parse_args(argv)
    recipe = RECIPES[arguments.agent]
    try:
        chosen = chosen_skills(arguments.skills)
        folder = project_folder(arguments.project, Path.cwd(), Path.home(),
                                ask=input if sys.stdin.isatty() else None)
        if arguments.new_terminal:
            open_terminal(folder, [str(agent_config.installed_program()), "start",
                                   f"--agent={arguments.agent}", f"--project={folder}",
                                   f"--skills={','.join(chosen)}"])
            print(f"Opened a new terminal window to start {recipe.display_name} in {folder}.")
            return
        start(recipe, folder, chosen, confirm=not arguments.yes)
    except AIStackError as refusal:
        sys.exit(f"{recipe.display_name} was not started. {refusal.message}")


def chosen_skills(text: str) -> tuple[str, ...]:
    names = [name.strip() for name in text.split(",")]
    if not any(names):
        raise ValidationError("Choose at least one skill, as --skills=name,other-name.")
    if not all(names):
        raise ValidationError("--skills has an empty name. Separate names with single commas.")
    return tuple(dict.fromkeys(validated_skill_name(name) for name in names))


# What the localhost dashboard runs the command with. Tests replace it, so none opens a window.
_run_from_page = subprocess.run
_FROM_PAGE_TIMEOUT_SECONDS = 60


def start_from_page(agent: str, project: str, skills: list[str]) -> None:
    """`aistack start --new-terminal` for the localhost dashboard (ADR-0038): every value
    checked here, passed as one `--name=value` argument with no shell, and the command in the
    new window still waits for Enter. A refusal comes back as the command's own sentence."""
    if agent not in RECIPES:
        raise ValidationError(f"AIStack starts {', '.join(RECIPES)}, not '{loggable(agent)}'.")
    if len(skills) > 1000 or not all(isinstance(name, str) and "," not in name
                                     for name in skills):
        raise ValidationError("skills must be a list of skill names.")
    chosen = chosen_skills(",".join(skills))
    key = projects.validated_key(project)
    # A key, never a folder: `--project` also takes a path, and the page names projects.
    # `/x` on any system: Windows reads it as a folder on the current drive.
    if key.startswith(("~", ".")) or PureWindowsPath(key).anchor:
        raise ValidationError("project is not a project key AIStack made. Send the key sync "
                              "reported under project.")
    command = [sys.executable, "-m", "aistack.bootstrap", "start", "--new-terminal",
               f"--agent={agent}", f"--project={key}", f"--skills={','.join(chosen)}"]
    # An empty folder to run in, so no relative path resolves to a folder, and the command
    # cannot read the dashboard's own input or ask a question nobody sees.
    with tempfile.TemporaryDirectory() as nowhere:
        try:
            done = _run_from_page(command, cwd=nowhere, stdin=subprocess.DEVNULL,
                                  capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", timeout=_FROM_PAGE_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            raise StartRefused("Opening a terminal took too long. Run the command in a "
                               "terminal instead.") from None
    if done.returncode:
        said = (done.stderr or "").strip().splitlines()
        raise StartRefused(said[-1] if said else
                           f"{RECIPES[agent].display_name} was not started. Run the command "
                           "in a terminal to see why.")


def start(recipe: Recipe, folder: Path, chosen: tuple[str, ...], confirm: bool = True,
          run=subprocess.run, execute=None) -> None:
    program, version = installed(recipe, run)
    on_disk = frozenset(recipe.scan(Path.home(), folder))
    missing = [name for name in chosen if name not in on_disk]
    if missing:
        raise StartRefused(f"{_listed(missing)} {'is' if len(missing) == 1 else 'are'} not on "
                           f"this computer where {recipe.display_name} looks in {folder}. "
                           "Add them here first, then run this again.")
    prepared = recipe.prepare(Launch(program, version, folder, chosen, on_disk), run)
    try:
        print(f"AIStack will start {recipe.display_name} {_dotted(version)} in {folder}\n"
              f"with only these skills: {_listed(chosen)}.\n"
              f"Turned off for this session: {_listed(prepared.turned_off) or 'nothing else'}, "
              f"and the agent's bundled skills.\n{recipe.note}\n"
              f"Command: {shlex.join(prepared.command)}")
        if confirm:
            try:
                input("Press Enter to start it, or Ctrl-C to stop. ")
            except (EOFError, KeyboardInterrupt):
                raise StartRefused("Nothing was started.") from None
        (execute or _execute)(prepared.command, folder)
    finally:
        for file in prepared.files:
            file.unlink(missing_ok=True)


def installed(recipe: Recipe, run=subprocess.run) -> tuple[str, tuple[int, ...]]:
    program = shutil.which(recipe.program)
    if program is None:
        raise StartRefused(f"The `{recipe.program}` command was not found. Install "
                           f"{recipe.display_name}, or run this from a terminal where "
                           f"`{recipe.program} --version` works.")
    done = run([program, "--version"], capture_output=True, text=True, encoding="utf-8",
               errors="replace", timeout=60)
    found = re.search(r"(\d+)\.(\d+)\.(\d+)", done.stdout or "")
    if done.returncode or not found:
        raise StartRefused(f"`{recipe.program} --version` did not say which version is "
                           "installed. Check that it runs, then try again.")
    version = tuple(int(part) for part in found.groups())
    if version < recipe.minimum:
        raise StartRefused(f"{recipe.display_name} {_dotted(version)} is installed, and "
                           f"starting it with chosen skills needs {_dotted(recipe.minimum)} or "
                           "later. Update it, then run this again.")
    return program, version


def _execute(command: list[str], folder: Path) -> None:
    """Become the agent in the project's folder; on Windows, which has no exec, wait for it."""
    _refuse_batch_file_quoting(command)
    if os.name != "nt":
        os.chdir(folder)
        os.execvp(command[0], command)
    # Ctrl-C belongs to the agent: an interrupted wait here would kill it.
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    sys.exit(subprocess.run(command, cwd=folder).returncode)


# cmd.exe reads these inside a batch file's arguments, whatever list2cmdline quoted.
_BATCH_SPECIAL = set('"%^&|<>!\r\n')


def _refuse_batch_file_quoting(command: list[str]) -> None:
    if (os.name == "nt" and command[0].lower().endswith((".cmd", ".bat"))
            and any(_BATCH_SPECIAL & set(argument) for argument in command[1:])):
        raise StartRefused(f"{command[0]} is a batch file, which cannot be handed these "
                           "skill names safely. Install the agent's native program, then run "
                           "this again.")


# Project ---------------------------------------------------------------------------------

def project_folder(project: str | None, cwd: Path, home: Path, ask=None) -> Path:
    """The top level of the project's repository on this computer: the current one, a
    folder, or a key this computer manages, checked on disk. With `ask`, a key with no
    known folder here asks the person for it."""
    from aistack.services.server_sync import current_project

    if project is None:
        here = current_project(cwd, home)
        if here is None:
            raise StartRefused("This folder is not in a project. Run this inside a project's "
                               "repository, or name one with --project.")
        return here[0]
    folder = Path(project).expanduser()
    if folder.is_dir():
        here = current_project(folder.resolve(), home)
        if here is None:
            raise StartRefused(f"{loggable(folder)} is not in a git repository other than your "
                               "home folder, so it is not a project.")
        return here[0]
    key = projects.validated_key(project)
    here = current_project(cwd, home)
    if here is not None and _key_of(here) == key:
        return here[0]
    found = managed_folder(key, home)
    if found is not None:
        return found
    if ask is None:
        raise StartRefused(f"AIStack found no folder of project '{loggable(key)}' on this "
                           "computer. Run this inside its repository, or pass its folder with "
                           "--project.")
    try:
        answer = ask(f"Where is project '{loggable(key)}' on this computer? Its folder: ")
    except (EOFError, KeyboardInterrupt):
        raise StartRefused("Nothing was started.") from None
    folder = Path(answer.strip()).expanduser()
    here = current_project(folder.resolve(), home) if answer.strip() and folder.is_dir() else None
    if here is None or (here[1]["remote"] is not None and _key_of(here) != key):
        raise StartRefused(f"{loggable(answer.strip())} is not a folder of project "
                           f"'{loggable(key)}'.")
    return here[0]


def managed_folder(key: str, home: Path) -> Path | None:
    """The folder this computer last reported for a project it manages: local mode's Library
    record, or what server-mode sync recorded when the server said it manages it. Each is
    checked on disk, so a stale or forged record leads nowhere else."""
    from aistack.services.server_sync import current_project, reported_project

    machine_id, paths = _library_folders(key)
    for path in paths:
        here = current_project(Path(path), home)
        if here is not None and _key_of(here, machine_id) == key:
            return here[0]
    reported = reported_project(home, key)
    if reported is not None:
        here = current_project(reported, home)
        if here is not None and here[0] == reported.resolve() and (
                _key_of(here) == key
                or (here[1]["remote"] is None and key.startswith("local/"))):
            return here[0]
    return None


def _key_of(here: tuple[Path, dict], machine_id=None) -> str | None:
    top, reported = here
    try:
        if reported["remote"] is not None:
            return projects.project_key(reported["remote"])
    except ValidationError:
        return None
    return None if machine_id is None else projects.local_project_key(machine_id, str(top))


def _library_folders(key: str):
    """Where this computer's Library last saw the project's folders here. Each is checked on
    disk before use; a Library that cannot be read here (none, or a server's) offers none."""
    from aistack.bootstrap.configuration.settings.settings_config import LocalSettings
    from aistack.bootstrap.context import application_context
    from aistack.services import project_service

    try:
        settings = LocalSettings().resolved(record=False)
        if settings.place() is None and not (settings.home / "aistack.db").exists():
            return None, []
        application_context.build_local_context(settings)
        caller = application_context.get_local_principal()
        with application_context.get_read_session_factory()() as session:
            return caller.machine_id, project_service.folder_paths(
                session, caller.user_id, caller.machine_id, key)
    except Exception:
        return None, []
    finally:
        application_context.dispose_application_context()


# Scanning --------------------------------------------------------------------------------

def _skill_names(folder: Path) -> set[str]:
    """Each skill folder's name and the name its SKILL.md declares: an agent may know it by
    either, and turning off a name nobody uses costs nothing."""
    names = set()
    if not folder.is_dir():
        return names
    for skill in folder.iterdir():
        document = skill / "SKILL.md"
        if skill.name.startswith(".") or not document.is_file():
            continue
        names.add(skill.name)
        declared = _declared_name(document)
        if declared:
            names.add(declared)
    return names


def _declared_name(document: Path) -> str | None:
    try:
        lines = document.read_text(encoding="utf-8", errors="replace").split("\n")[:100]
    except OSError:
        return None
    if not lines or lines[0].strip() != "---":
        return None
    for line in lines[1:]:
        if line.strip() == "---":
            return None
        found = re.match(r"name:\s*(.*?)\s*$", line)
        if found:
            return found[1].strip("'\"") or None
    return None


def _nested_skill_folders(project: Path, folder: str) -> list[Path]:
    """`<folder>` anywhere below the project, as git sees it: Claude Code loads those lazily."""
    try:
        done = subprocess.run(
            ["git", "-C", str(project), "ls-files", "-z", "--cached", "--others",
             "--exclude-standard", "--", f":(glob)**/{folder}/*/SKILL.md"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10)
    except (OSError, subprocess.SubprocessError):
        return []
    return list({(project / path).parent.parent for path in done.stdout.split("\0") if path})


def _claude_code_managed() -> Path:
    if sys.platform == "darwin":
        return Path("/Library/Application Support/ClaudeCode/.claude/skills")
    if os.name == "nt":
        return Path(r"C:\Program Files\ClaudeCode\.claude\skills")
    return Path("/etc/claude-code/.claude/skills")


def _claude_code_scan(home: Path, project: Path) -> set[str]:
    roots = [home / ".claude" / "skills", project / ".claude" / "skills", _claude_code_managed(),
             *_nested_skill_folders(project, ".claude/skills")]
    names = set().union(*(_skill_names(root) for root in roots))
    # Legacy commands share the skills' names; turning one off by name is harmless if unused.
    for commands in (home / ".claude" / "commands", project / ".claude" / "commands"):
        if commands.is_dir():
            names |= {path.stem for path in commands.glob("*.md")}
    return names


def _codex_scan(home: Path, project: Path) -> set[str]:
    roots = [home / ".agents" / "skills", agent_config.codex_home() / "skills",
             Path("/etc/codex/skills"), project / ".codex" / "skills",
             project / ".agents" / "skills"]
    return set().union(*(_skill_names(root) for root in roots))


# Recipes ---------------------------------------------------------------------------------

# Claude Code reads claude.ai's skills in a terminal from this release, and the key that
# turns them off; an older one shows a settings error for a key it does not know.
_CLAUDE_CODE_SYNC = (2, 1, 275)


def _claude_code_prepare(launch: Launch, run) -> Prepared:
    """`claude --settings=<json>`: every other skill off by name, and the bundled ones.
    `--flag=value`, because some of its flags take every word after them."""
    turned_off = sorted(launch.on_disk - set(launch.chosen))
    settings = {"skillOverrides": dict.fromkeys(turned_off, "off"), "disableBundledSkills": True}
    if launch.version >= _CLAUDE_CODE_SYNC:
        settings["syncClaudeAiSkills"] = False
    text = json.dumps(settings, separators=(",", ":"))
    if os.name != "nt":
        return Prepared([launch.program, f"--settings={text}"], turned_off, [])
    # A file on Windows, where an npm install is a batch file that mangles quotes. The
    # process waits for the agent there, so it removes the file after.
    handle, path = tempfile.mkstemp(prefix="aistack-start-", suffix=".json")
    with os.fdopen(handle, "w", encoding="utf-8") as file:
        file.write(text)
    return Prepared([launch.program, f"--settings={path}"], turned_off, [Path(path)])


# Each round only adds names, so this bounds a Codex that keeps showing new ones.
_PREFLIGHT_ROUNDS = 5


def _codex_prepare(launch: Launch, run) -> Prepared:
    """`codex --no-daemon -c skills.bundled.enabled=false -c skills.config=[...]`, after
    `codex debug prompt-input` with the same flags shows exactly the chosen skills. Codex
    reads a `-c` value that does not parse as a string and ignores it silently, so the
    check is what makes the flags trustworthy."""
    chosen = set(launch.chosen)
    turned_off = set(launch.on_disk) - chosen
    for _ in range(_PREFLIGHT_ROUNDS):
        flags = _codex_flags(launch.chosen, turned_off)
        shown = _codex_shown(launch, flags, run)
        extra = shown - chosen
        if not extra:
            break
        if extra <= turned_off:
            raise StartRefused(f"Codex still shows {_listed(sorted(extra))} with these "
                               "settings, so it did not take them.")
        # Skills a plugin brings, or the budget left out of the first listing.
        turned_off |= extra
    else:
        raise StartRefused("Codex kept showing more skills after each check.")
    missing = [name for name in launch.chosen if name not in shown]
    if missing:
        raise StartRefused(f"Codex does not show {_listed(missing)} in {launch.folder}, so it "
                           "would start without them.")
    return Prepared([launch.program, "--no-daemon", *flags], sorted(turned_off), [])


def _codex_flags(chosen: tuple[str, ...], turned_off: set[str]) -> list[str]:
    # Chosen ones are turned on as well, over any rule in the person's own config.
    rules = ([f"{{name={_toml_string(name)},enabled=false}}" for name in sorted(turned_off)]
             + [f"{{name={_toml_string(name)},enabled=true}}" for name in chosen])
    return ["--config=skills.bundled.enabled=false", f"--config=skills.config=[{','.join(rules)}]"]


def _toml_string(name: str) -> str:
    # A literal string carries no double quotes, which a Windows batch file mangles.
    if "'" not in name and name.isprintable():
        return f"'{name}'"
    return json.dumps(name)


def _codex_shown(launch: Launch, flags: list[str], run) -> set[str]:
    """The skills Codex would put before the model with these flags, with no model call."""
    command = [launch.program, "debug", "prompt-input", *flags]
    _refuse_batch_file_quoting(command)
    try:
        done = run(command, cwd=launch.folder, capture_output=True, text=True,
                   encoding="utf-8", errors="replace", timeout=120)
    except (OSError, subprocess.SubprocessError) as error:
        raise StartRefused(f"`codex debug prompt-input` could not run ({error}), so AIStack "
                           "could not check which skills Codex would load.") from None
    if done.returncode:
        raise StartRefused("`codex debug prompt-input` failed, so AIStack could not check "
                           f"which skills Codex would load: {(done.stderr or '').strip()[-300:]}")
    try:
        rendered = json.loads(done.stdout)
    except ValueError:
        raise StartRefused("`codex debug prompt-input` did not print the JSON this release "
                           "of AIStack reads, so it could not check which skills Codex "
                           "would load.") from None
    return shown_skills(rendered)


_LISTED_SKILL = re.compile(r"- (\S+?)(?::\s|:$|\s\(file:)")


def shown_skills(rendered) -> set[str]:
    """Names under `### Available skills` in any text of Codex's rendered prompt input:
    `- name: description (file: ...)`, one per line, up to the first other line."""
    names = set()
    for text in _texts(rendered):
        if "### Available skills" not in text:
            continue
        for line in text.split("### Available skills", 1)[1].lstrip("\n").split("\n"):
            found = _LISTED_SKILL.match(line)
            if not found:
                break
            names.add(found[1])
    return names


def _texts(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _texts(item)
    elif isinstance(value, list):
        for item in value:
            yield from _texts(item)


RECIPES: dict[str, Recipe] = {
    "claude-code": Recipe(
        display_name="Claude Code",
        program="claude",
        minimum=(2, 1, 169),
        scan=_claude_code_scan,
        prepare=_claude_code_prepare,
        note="Plugin skills stay on unless the plugin is turned off, and resuming this session "
             "later from a plain terminal brings every skill back.",
    ),
    "codex": Recipe(
        display_name="Codex",
        program="codex",
        minimum=(0, 163, 0),
        scan=_codex_scan,
        prepare=_codex_prepare,
        note="Resuming this session later from a plain terminal brings every skill back.",
    ),
}


# A new terminal ----------------------------------------------------------------------------

def open_terminal(folder: Path, command: list[str], popen=subprocess.Popen) -> None:
    """A new terminal window that runs `command` in `folder`, every argument quoted for it.
    The command it runs asks for Enter itself, in that window."""
    if os.name == "nt":
        # Windows Terminal reads `;` as the start of another command; a new console reads
        # nothing, so it is the fallback.
        if shutil.which("wt") and not any(";" in part for part in [str(folder), *command]):
            popen(["wt", "-w", "new", "new-tab", "-d", str(folder), *command])
        else:
            popen(command, cwd=folder, creationflags=subprocess.CREATE_NEW_CONSOLE)
        return
    script = _script(folder, command)
    if sys.platform == "darwin":
        popen(["open", "-a", "Terminal", str(script)])
        return
    for terminal in (["x-terminal-emulator", "-e"], ["gnome-terminal", "--"], ["konsole", "-e"],
                     ["xfce4-terminal", "-x"], ["xterm", "-e"]):
        if shutil.which(terminal[0]):
            popen([*terminal, str(script)], start_new_session=True)
            return
    script.unlink(missing_ok=True)
    raise StartRefused("No terminal program was found to open. Run this in a terminal "
                       f"instead: cd {shlex.quote(str(folder))} && {shlex.join(command)}")


def _script(folder: Path, command: list[str]) -> Path:
    """A shell script that removes itself, then runs the command: `.command` is what macOS
    Terminal opens, and every terminal on Linux takes a path as one word."""
    handle, path = tempfile.mkstemp(prefix="aistack-start-", suffix=".command")
    with os.fdopen(handle, "w", encoding="utf-8") as file:
        file.write("#!/bin/sh\n"
                   'rm -f "$0"\n'
                   f"cd {shlex.quote(str(folder))} || exit 1\n"
                   f"{shlex.join(command)}\n"
                   "printf '\\nPress Enter to close this window. '\n"
                   "read _\n")
    os.chmod(path, 0o700)
    return Path(path)


def _listed(names) -> str:
    return ", ".join(loggable(name) for name in names)


def _dotted(version: tuple[int, ...]) -> str:
    return ".".join(str(part) for part in version)
