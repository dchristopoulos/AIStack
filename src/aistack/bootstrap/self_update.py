"""Local mode keeps itself current: once a day, a newer release is installed for the next start.

Setup installs AIStack as a uv tool so the agent starts it directly, with no index to reach:
it starts at once and works offline. This replaces the `uvx aistack-mcp@latest` the agent
used to run, which checked PyPI on every start and failed to start without a network. A
computer that has not updated yet keeps working beside one that has (ADR-0024).
"""

import logging
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from importlib import metadata
from pathlib import Path

logger = logging.getLogger(__name__)

PACKAGE = "aistack-mcp"
_CHECK_EVERY_SECONDS = 24 * 60 * 60
_PYPI_URL = f"https://pypi.org/pypi/{PACKAGE}/json"
_STAMP = "last-update-check"


def start_in_background(home: Path, force: bool = False) -> None:
    """Check for a newer release without delaying the agent; failures only reach the log."""
    threading.Thread(target=_check_and_upgrade, args=(home, force), daemon=True).start()


def _check_and_upgrade(home: Path, force: bool) -> None:
    try:
        upgraded = check_and_upgrade(home, force=force)
        if upgraded:
            logger.warning(f"AIStack {upgraded} is installed and takes over at the next start.")
    except Exception as error:  # an update is never worth stopping the Library for
        logger.info(f"Checking for a newer AIStack failed: {error}")


def check_and_upgrade(home: Path, latest_release=None, run=subprocess.run,
                      force: bool = False) -> str | None:
    """Install a newer release with `uv tool upgrade`, at most once a day, and only one with
    the same minor version: before 1.0 a new minor is one older releases stop working with
    (AGENTS.md), so moving to it is the person's call, made on every computer at once.

    `force` is for a Library another computer already moved to a newer release: this one
    cannot read it until it updates too, so it updates at once, to whatever is newest.
    Returns the version it installed, or None."""
    uv = _uv()
    if uv is None or not installed_as_uv_tool():
        return None
    stamp = home / _STAMP
    if (not force and stamp.exists()
            and time.time() - stamp.stat().st_mtime < _CHECK_EVERY_SECONDS):
        return None
    home.mkdir(parents=True, exist_ok=True)
    stamp.touch()

    current = metadata.version(PACKAGE)
    latest = (latest_release or _latest_on_pypi)()
    if _version(latest) <= _version(current):
        return None
    if not force and _version(latest)[:2] != _version(current)[:2]:
        logger.warning(f"AIStack {latest} is out. It is a new minor version, which older "
                       "releases may not work beside, so it is not installed by itself: run "
                       f"`uv tool upgrade {PACKAGE}` on each of your computers when you are "
                       "ready.")
        return None
    # Captured so nothing reaches local mode's stdout, which is the MCP channel. uv's output is
    # not logged: it can name the person's package index, credentials included.
    done = run([uv, "tool", "upgrade", PACKAGE], capture_output=True, text=True, timeout=300)
    if done.returncode != 0:
        logger.warning(f"`uv tool upgrade {PACKAGE}` failed with exit code {done.returncode}, "
                       f"so AIStack stays at {current}. Run it yourself to see why.")
        return None
    return latest


def _latest_on_pypi() -> str:
    import json

    with urllib.request.urlopen(_PYPI_URL, timeout=5) as response:
        return json.load(response)["info"]["version"]


def installed_as_uv_tool() -> bool:
    """Only a uv tool install is upgraded here: a checkout, pipx, or the container is not."""
    # uv leaves this receipt in every environment `uv tool install` makes.
    return (Path(sys.prefix) / "uv-receipt.toml").is_file()


def _uv() -> str | None:
    found = shutil.which("uv")
    if found:
        return found
    for folder in ("/opt/homebrew/bin", "/usr/local/bin", str(Path.home() / ".local" / "bin"),
                   str(Path.home() / ".cargo" / "bin")):
        candidate = Path(folder) / "uv"
        if candidate.is_file():
            return str(candidate)
    return None


def _version(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", text)[:3])
