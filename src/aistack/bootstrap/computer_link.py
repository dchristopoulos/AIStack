"""The `aistack://` computer link: `aistack open <link>`, and its registration (ADR-0038).

Any website can open the link, so it is hostile input end to end: only three actions, only
their own parameters, each checked by the rule its command already uses, and a project must
be one this computer manages. The command it runs says what it will do and waits for Enter,
so a click never acts on its own. Nothing from the link reaches a shell unquoted or an option
position: the handler passes it after `--`, and the commands get `--name=value` arguments.
"""

import argparse
import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path, PureWindowsPath
from urllib.parse import parse_qsl, urlsplit

from aistack.bootstrap import agent_config, start_agent
from aistack.commons.exceptions import AIStackError, ValidationError
from aistack.commons.text import loggable
from aistack.services import projects

SCHEME = "aistack"
LINK_MAX_LENGTH = 4096
VALUE_MAX_LENGTH = 1024
# Every action's parameters, all required: anything else in a link refuses it.
ACTIONS = {
    "start": ("agent", "project", "skills"),
    "project-add": ("folder",),
    "sync": (),
}

# What setup runs registration with. Tests replace it, so no test registers on its computer.
_run = subprocess.run


class LinkRefused(AIStackError):
    """Why a link was not acted on."""


def run(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(
        prog="aistack open",
        description="Act on an aistack:// link from the dashboard: start an agent, add a "
                    "project, or sync. The command says what it will do and waits for Enter.")
    parser.add_argument("link")
    parser.add_argument("--new-terminal", action="store_true",
                        help="Open it in a new terminal window, as the link handler does")
    arguments = parser.parse_args(argv)
    try:
        if arguments.new_terminal:
            # The full check runs in the window, where its refusal can be read.
            _shape(arguments.link)
            start_agent.open_terminal(Path.home(), [str(agent_config.installed_program()),
                                                    "open", "--", arguments.link])
            return
        command = link_command(arguments.link, Path.home())
    except AIStackError as refusal:
        sys.exit(f"AIStack did not act on this link. {refusal.message}")
    print("A web page opened this aistack:// link. Nothing happens without your Enter.")
    if command[0] == "start":
        start_agent.run(command[1:])
    elif command[0] == "project":
        from aistack.bootstrap import project_add

        project_add.run(command[1:])
    else:
        try:
            input("AIStack will sync this computer's skills with your Library. Press Enter "
                  "to sync, or Ctrl-C to stop. ")
        except (EOFError, KeyboardInterrupt):
            sys.exit("Nothing was synced.")
        sys.exit(subprocess.run([sys.executable, "-m", "aistack.bootstrap", "sync"]).returncode)


def _shape(link: str) -> None:
    if (len(link) > LINK_MAX_LENGTH or not link.isprintable()
            or not link.lower().startswith(f"{SCHEME}://")):
        raise LinkRefused(f"It is not an {SCHEME}:// link the dashboard makes.")


def parse(link: str) -> tuple[str, dict[str, str]]:
    """The action and its parameters, checked for shape only: each value is still hostile."""
    _shape(link)
    try:
        parts = urlsplit(link)
        if parts.port is not None:
            raise ValueError
    except ValueError:
        raise LinkRefused(f"It is not an {SCHEME}:// link the dashboard makes.") from None
    action = parts.netloc
    if (parts.scheme != SCHEME or action not in ACTIONS or parts.path not in ("", "/")
            or parts.fragment):
        raise LinkRefused(f"AIStack links do {', '.join(ACTIONS)}; this one asks for "
                          "something else.")
    try:
        pairs = parse_qsl(parts.query, keep_blank_values=True, strict_parsing=bool(parts.query),
                          max_num_fields=len(ACTIONS[action]))
    except ValueError:
        pairs = None
    names = [name for name, _ in pairs] if pairs is not None else []
    if pairs is None or len(names) != len(set(names)) or set(names) != set(ACTIONS[action]):
        wanted = ", ".join(ACTIONS[action]) or "no parameters"
        raise LinkRefused(f"An {action} link takes {wanted}, each once, and nothing else.")
    for name, value in pairs:
        if len(value) > VALUE_MAX_LENGTH or not value.isprintable():
            raise LinkRefused(f"Its {name} is longer than {VALUE_MAX_LENGTH} characters or has "
                              "a control character in it.")
    return action, dict(pairs)


def link_command(link: str, home: Path) -> list[str]:
    """The `aistack` arguments a link stands for, every value checked."""
    action, values = parse(link)
    try:
        if action == "sync":
            return ["sync"]
        if action == "project-add":
            folder = Path(values["folder"])
            if not folder.is_absolute() or not folder.is_dir():
                raise LinkRefused(f"{loggable(values['folder'])} is not a folder on this "
                                  "computer.")
            return ["project", "add", "--", str(folder.resolve())]
        if values["agent"] not in start_agent.RECIPES:
            raise LinkRefused(f"AIStack starts {', '.join(start_agent.RECIPES)}, not "
                              f"'{loggable(values['agent'])}'.")
        skills = start_agent.chosen_skills(values["skills"])
        key = projects.validated_key(values["project"])
    except ValidationError as refusal:
        raise LinkRefused(refusal.message) from None
    folder = start_agent.managed_folder(key, home)
    if folder is None:
        raise LinkRefused(f"'{loggable(key)}' is not a project this computer manages. Add it "
                          "here first, or run `aistack start` inside its folder.")
    return ["start", f"--agent={values['agent']}", f"--project={folder}",
            f"--skills={','.join(skills)}"]


# Registration ----------------------------------------------------------------------------

MACOS_APP = Path("Applications") / "AIStack Link.app"
MACOS_BUNDLE_ID = "io.github.dchristopoulos.aistack.link"
LSREGISTER = ("/System/Library/Frameworks/CoreServices.framework/Frameworks/"
              "LaunchServices.framework/Support/lsregister")
LINUX_ENTRY = "aistack-link.desktop"
WINDOWS_KEY = rf"Software\Classes\{SCHEME}"
REGISTERED = (f"Registered the {SCHEME}:// link, so the dashboard can open a terminal on this "
              "computer.")


def register(program: Path, home: Path | None = None, system: str | None = None,
             run=None, registry=None) -> str:
    """Point the link at `program`, replacing an earlier registration. Never raises: without
    the link, the page shows the command to copy instead."""
    home, system, run = home or Path.home(), system or sys.platform, run or _run
    try:
        _checked_program(program, system)
        if system == "darwin":
            _register_macos(program, home, run)
        elif system == "win32":
            for (key, name), value in _windows_values(program).items():
                (registry or _Registry()).set(key, name, value)
        else:
            _register_linux(program, home, run)
    except (OSError, subprocess.SubprocessError, ValueError, AIStackError) as error:
        return (f"The {SCHEME}:// link is not registered on this computer "
                f"({loggable(str(error))}). The dashboard shows commands to copy instead.")
    return REGISTERED


def registered(program: Path, home: Path | None = None, system: str | None = None,
               run=None, registry=None) -> bool:
    """Whether the link opens `program` on this computer."""
    home, system, run = home or Path.home(), system or sys.platform, run or _run
    try:
        if system == "darwin":
            with (home / MACOS_APP / "Contents" / "Info.plist").open("rb") as file:
                info = plistlib.load(file)
            return (info.get("AIStackProgram") == str(program)
                    and [SCHEME] in [entry.get("CFBundleURLSchemes")
                                     for entry in info.get("CFBundleURLTypes", [])])
        if system == "win32":
            registry = registry or _Registry()
            return all(registry.get(key, name) == value
                       for (key, name), value in _windows_values(program).items())
        entry = _linux_entry_path(home)
        default = run(["xdg-mime", "query", "default", f"x-scheme-handler/{SCHEME}"],
                      capture_output=True, text=True, timeout=30)
        return (entry.read_text(encoding="utf-8") == _desktop_entry(program)
                and default.stdout.strip() == LINUX_ENTRY)
    except (OSError, subprocess.SubprocessError, ValueError, AIStackError):
        return False


def status(program: Path) -> str:
    if registered(program):
        return f"The {SCHEME}:// link opens a terminal on this computer."
    return (f"The {SCHEME}:// link is not registered on this computer, so the dashboard shows "
            "commands to copy. Run setup again to register it.")


def _checked_program(program: Path, system: str) -> None:
    # Each handler embeds the path in its own quoting: refuse what any of them would read.
    text = str(program)
    windows = system == "win32"
    absolute = PureWindowsPath(text).is_absolute() if windows else text.startswith("/")
    if not absolute or not text.isprintable() or set(text) & set('"`$%' if windows else '"`$%\\'):
        raise LinkRefused(f"the program's path {loggable(text)} cannot be put in a link "
                          "handler")


def _register_macos(program: Path, home: Path, run) -> None:
    """An AppleScript applet whose `open location` hands the link to the program after `--`,
    quoted by AppleScript for the shell, with the URL type registered with Launch Services."""
    app = home / MACOS_APP
    app.parent.mkdir(parents=True, exist_ok=True)
    staging = app.with_name(".aistack-link-staging.app")
    source = app.with_name(".aistack-link.applescript")
    shutil.rmtree(staging, ignore_errors=True)
    literal = '"' + str(program).replace("\\", "\\\\").replace('"', '\\"') + '"'
    source.write_text("on open location link\n"
                      f"\tdo shell script quoted form of {literal} & "
                      '" open --new-terminal -- " & quoted form of link\n'
                      "end open location\n", encoding="utf-8")
    try:
        run(["osacompile", "-o", str(staging), str(source)], check=True, capture_output=True,
            timeout=60)
    finally:
        source.unlink(missing_ok=True)
    info_path = staging / "Contents" / "Info.plist"
    with info_path.open("rb") as file:
        info = plistlib.load(file)
    info.update(CFBundleIdentifier=MACOS_BUNDLE_ID, CFBundleName="AIStack Link",
                LSUIElement=True, AIStackProgram=str(program),
                CFBundleURLTypes=[{"CFBundleURLName": "AIStack computer link",
                                   "CFBundleURLSchemes": [SCHEME]}])
    with info_path.open("wb") as file:
        plistlib.dump(info, file)
    # The edited Info.plist no longer matches the applet's signature.
    run(["codesign", "--force", "--sign", "-", str(staging)], check=True, capture_output=True,
        timeout=60)
    shutil.rmtree(app, ignore_errors=True)
    staging.rename(app)
    run([LSREGISTER, "-f", str(app)], check=True, capture_output=True, timeout=60)


def _windows_values(program: Path) -> dict[tuple[str, str], str]:
    # `--` before the link: a link that reads as a flag is still only the link.
    return {(WINDOWS_KEY, ""): "URL:AIStack computer link",
            (WINDOWS_KEY, "URL Protocol"): "",
            (rf"{WINDOWS_KEY}\shell\open\command", ""): f'"{program}" open -- "%1"'}


class _Registry:
    """The current user's registry, which needs no administrator."""

    def set(self, key: str, name: str, value: str) -> None:
        import winreg

        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_SET_VALUE) as handle:
            winreg.SetValueEx(handle, name, 0, winreg.REG_SZ, value)

    def get(self, key: str, name: str) -> str | None:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as handle:
            return winreg.QueryValueEx(handle, name)[0]


def _linux_entry_path(home: Path) -> Path:
    data = os.environ.get("XDG_DATA_HOME", "")
    return (Path(data) if Path(data).is_absolute() else home / ".local" / "share") \
        / "applications" / LINUX_ENTRY


def _desktop_entry(program: Path) -> str:
    # `_checked_program` refused every character the Exec key would have to escape.
    return ("[Desktop Entry]\n"
            "Type=Application\n"
            "Name=AIStack computer link\n"
            f'Exec="{program}" open --new-terminal -- %u\n'
            "NoDisplay=true\n"
            "Terminal=false\n"
            f"MimeType=x-scheme-handler/{SCHEME};\n")


def _register_linux(program: Path, home: Path, run) -> None:
    entry = _linux_entry_path(home)
    entry.parent.mkdir(parents=True, exist_ok=True)
    entry.write_text(_desktop_entry(program), encoding="utf-8")
    run(["xdg-mime", "default", LINUX_ENTRY, f"x-scheme-handler/{SCHEME}"], check=True,
        capture_output=True, timeout=30)
