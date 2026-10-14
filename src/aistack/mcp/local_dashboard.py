"""The dashboard a local mode process serves for `open_dashboard` (ADR-0020).

One per process, on 127.0.0.1 and a port the system picks, started the first time it is asked
for. It runs as long as the agent session that started this process, and goes with it.
"""

import socket
import threading
import time

import uvicorn

from aistack.bootstrap.context.application_context import get_local_principal, get_ticket_signer
from aistack.mcp.mcp import dashboard_server_config
from aistack.mcp.server_url import DASHBOARD_LOGIN_PATH

_STARTUP_SECONDS = 5

_lock = threading.Lock()
_server: uvicorn.Server | None = None
_port: int | None = None


def dashboard_link() -> str:
    """A fresh sign-in link to this process's dashboard, starting the page if it is not up."""
    global _server, _port
    principal = get_local_principal()
    with _lock:
        if _server is None:
            listener = socket.create_server(("127.0.0.1", 0))
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
    ticket = get_ticket_signer().sign_dashboard_link(principal.user_id)
    return f"http://127.0.0.1:{_port}{DASHBOARD_LOGIN_PATH}/{ticket}"


def stop_dashboard() -> None:
    """Shut the page down. Tests use it between temporary Libraries."""
    global _server, _port
    with _lock:
        if _server is not None:
            _server.should_exit = True
        _server, _port = None, None
