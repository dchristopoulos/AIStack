"""`aistack github`: a personal Library on GitHub, with nothing to do on github.com but sign
in once (ADR-0025).

The person approves the GitHub CLI in the browser with a one-time code; AIStack then finds or
creates their private repository and prints its name for setup. git reaches it later through
the same `gh` login, so AIStack still keeps no token. A team's Library is not offered here.
"""

import re
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

from aistack.services.library_repo import gh_command

REPOSITORY_NAME = "aistack-library"
_DEVICE_URL = "https://github.com/login/device"
_SIGN_IN_LOG = "github-sign-in.txt"
_CODE = re.compile(r"one-time code: ([A-Z0-9]{4}-[A-Z0-9]{4})")
# GitHub lets a one-time code be used for fifteen minutes.
_CODE_LIFETIME_SECONDS = 15 * 60
# Short enough that an agent's shell does not give up on the command first.
_WAIT_FOR_APPROVAL_SECONDS = 90
_POLL_SECONDS = 3
SIGNED_IN, WAITING, FAILED = 0, 2, 1


def connect(home: Path) -> int:
    """Sign in if needed, then find or create the repository. Prints what the agent needs and
    returns the exit status: 0 with the repository named, 2 while GitHub waits for the person
    to approve, 1 on anything to fix first."""
    gh = gh_command()
    if _run(gh, "--version") is None:
        print("The GitHub CLI is not installed. Install it (macOS: `brew install gh`; "
              "Windows: `winget install --id GitHub.cli`; others: https://cli.github.com), "
              "then run this again.")
        return FAILED
    if not _signed_in(gh):
        waiting = _waiting_sign_in(gh, home)
        if waiting is not None:
            return waiting
    return _find_or_create(gh)


def _waiting_sign_in(gh: str, home: Path) -> int | None:
    """None once signed in; otherwise the code to show, and WAITING or FAILED."""
    log = home / _SIGN_IN_LOG
    code = _code(log) if _fresh(log) else None
    if code is not None:
        # A sign-in already started: give the person a moment to finish it.
        deadline = time.monotonic() + _WAIT_FOR_APPROVAL_SECONDS
        while time.monotonic() < deadline:
            if _signed_in(gh):
                log.unlink(missing_ok=True)
                return None
            time.sleep(_POLL_SECONDS)
    else:
        code = _start_sign_in(gh, log)
        if code is None:
            print("GitHub did not hand out a sign-in code. Check the internet connection, "
                  "then run this again.")
            return FAILED
        webbrowser.open(_DEVICE_URL)
    print(f"Sign in to GitHub: open {_DEVICE_URL}, enter the code {code}, and approve GitHub "
          f"CLI. Then run this command again.")
    return WAITING


def _start_sign_in(gh: str, log: Path) -> str | None:
    """Start `gh auth login` on its own, so it keeps waiting for approval after this command
    returns, and read the one-time code it prints."""
    log.parent.mkdir(parents=True, exist_ok=True)
    detached = ({"creationflags": subprocess.DETACHED_PROCESS
                 | subprocess.CREATE_NEW_PROCESS_GROUP}
                if sys.platform == "win32" else {"start_new_session": True})
    with open(log, "w", encoding="utf-8") as output:
        subprocess.Popen([gh, "auth", "login", "--web", "--hostname", "github.com",
                          "--skip-ssh-key"],
                         stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
                         **detached)
    for _ in range(30):
        code = _code(log)
        if code is not None:
            return code
        time.sleep(0.5)
    return None


def _find_or_create(gh: str) -> int:
    owner = _run(gh, "api", "user", "--jq", ".login")
    if not owner:
        print("GitHub did not answer who is signed in. Check the internet connection and "
              "`gh auth status`, then run this again.")
        return FAILED
    repository = f"{owner.strip()}/{REPOSITORY_NAME}"
    private = _run(gh, "repo", "view", repository, "--json", "isPrivate", "--jq", ".isPrivate")
    if private is None:
        created = _run(gh, "repo", "create", repository, "--private",
                       "--description", "My AIStack Library, kept by AIStack.")
        if created is None:
            print(f"Could not create the private repository {repository}. Check `gh auth "
                  f"status`, then run this again.")
            return FAILED
    elif private.strip() != "true":
        # Somebody else's use of the name, or a repository made public: never put a Library
        # where anyone can read it.
        print(f"{repository} already exists and is public, so AIStack will not keep a Library "
              f"in it. Set AISTACK_LIBRARY_REPO to the name of a private repository instead.")
        return FAILED
    print(f"Your Library's repository is {repository}, private.")
    print(f"AISTACK_LIBRARY_REPO={repository}")
    return SIGNED_IN


def _signed_in(gh: str) -> bool:
    return _run(gh, "auth", "status", "--hostname", "github.com") is not None


def _run(gh: str, *arguments: str) -> str | None:
    """stdout, or None when gh is missing or the command failed."""
    try:
        done = subprocess.run([gh, *arguments], capture_output=True, text=True, timeout=60,
                              stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.stdout if done.returncode == 0 else None


def _code(log: Path) -> str | None:
    try:
        found = _CODE.search(log.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return None
    return found.group(1) if found else None


def _fresh(log: Path) -> bool:
    try:
        return time.time() - log.stat().st_mtime < _CODE_LIFETIME_SECONDS
    except OSError:
        return False
