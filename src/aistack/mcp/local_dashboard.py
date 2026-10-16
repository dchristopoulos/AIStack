"""The dashboard a local mode process serves for `open_dashboard` (ADR-0020).

One per process, on 127.0.0.1, started the first time it is asked for. It runs as long as the
agent session that started this process, and goes with it.
"""

import hashlib
import html
import json
import os
import secrets
import socket
import threading
import time
import webbrowser
from pathlib import Path

import uvicorn

from aistack.bootstrap.context.application_context import (
    get_local_home,
    get_local_principal,
    get_ticket_signer,
)
from aistack.mcp.mcp import dashboard_server_config
from aistack.mcp.server_url import DASHBOARD_LOGIN_PATH

_STARTUP_SECONDS = 5
# How long the page that forwards the browser to a sign-in link stays on disk: long enough for
# a browser that is still starting to read it, and no longer than the link itself works.
_FORWARD_PAGE_SECONDS = 60
_FORWARD_PAGE_PREFIX = "open-dashboard-"

# A browser keeps the theme, the accent and picked agents per origin, and the port is part of
# it, so each Library home asks for the same port every time (UI-09). In the range nothing
# assigns, and only a preference: a port already taken means one the system picks.
_PORT_RANGE_START = 49152
_PORT_RANGE_SIZE = 10000

_lock = threading.Lock()
_server: uvicorn.Server | None = None
_port: int | None = None


def dashboard_link() -> str:
    """A fresh sign-in link to this process's dashboard, starting the page if it is not up."""
    global _server, _port
    principal = get_local_principal()
    with _lock:
        if _server is None:
            listener = listen()
            server = uvicorn.Server(dashboard_server_config(log_level="WARNING"))
            # uvicorn installs no signal handlers off the main thread, so the stdio server
            # keeps its own; a daemon thread ends with the process.
            threading.Thread(target=server.run, kwargs={"sockets": [listener]},
                             daemon=True).start()
            deadline = time.monotonic() + _STARTUP_SECONDS
            while not server.started:
                if time.monotonic() > deadline:
                    raise RuntimeError("The dashboard did not start within five seconds.")
                time.sleep(0.01)
            _server, _port = server, listener.getsockname()[1]
    ticket = get_ticket_signer().sign_dashboard_link(principal.dashboard_holder())
    return f"http://127.0.0.1:{_port}{DASHBOARD_LOGIN_PATH}/{ticket}"


def listen() -> socket.socket:
    """A socket on 127.0.0.1 at this Library home's own port, or any free one when that is
    taken, such as by a second dashboard of the same home."""
    home = str(get_local_home().resolve()).encode("utf-8")
    preferred = _PORT_RANGE_START + int(hashlib.sha256(home).hexdigest(), 16) % _PORT_RANGE_SIZE
    try:
        return socket.create_server(("127.0.0.1", preferred))
    except OSError:
        return socket.create_server(("127.0.0.1", 0))


def stop_dashboard() -> None:
    """Shut the page down. Tests use it between temporary Libraries."""
    global _server, _port
    with _lock:
        if _server is not None:
            _server.should_exit = True
        _server, _port = None, None


def open_in_browser(link: str) -> bool:
    """Open a sign-in link in the browser without putting it on a command line.

    A browser is started with its URL in its arguments, which any account on the computer can
    read while it runs, and the link is a credential (SEC-13). The browser opens instead a
    page in AISTACK_HOME that only this account can read and that forwards to the link; the
    page is deleted a minute later. False when no browser could be opened.
    """
    folder = get_local_home().resolve()
    _remove_forward_pages(folder, older_than=_FORWARD_PAGE_SECONDS)
    page = folder / f"{_FORWARD_PAGE_PREFIX}{secrets.token_hex(8)}.html"
    escaped = html.escape(link, quote=True)
    descriptor = os.open(page, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as file:
        # Chromium follows a script from a file to http, and not a meta refresh.
        file.write(f'<!doctype html><meta charset="utf-8"><title>AIStack</title>'
                   f'<script>location.replace({json.dumps(link).replace("</", "<\\/")})</script>'
                   f'<meta http-equiv="refresh" content="0;url={escaped}">'
                   f'<a href="{escaped}">Open the AIStack dashboard</a>')
    timer = threading.Timer(_FORWARD_PAGE_SECONDS, page.unlink, kwargs={"missing_ok": True})
    timer.daemon = True
    timer.start()
    try:
        return webbrowser.open(page.as_uri())
    except webbrowser.Error:
        page.unlink(missing_ok=True)
        return False


def _remove_forward_pages(folder: Path, older_than: float) -> None:
    """Pages a process that ended early left behind."""
    cutoff = time.time() - older_than
    for page in folder.glob(f"{_FORWARD_PAGE_PREFIX}*.html"):
        try:
            if page.stat().st_mtime < cutoff:
                page.unlink()
        except OSError:
            pass
