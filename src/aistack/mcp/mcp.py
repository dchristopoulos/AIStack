import logging

import uvicorn
from fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from fastmcp.server.middleware import AuthMiddleware

from aistack.bootstrap.context.application_context import get_failure_limiter
from aistack.commons.release import release
from aistack.mcp.argument_errors import ArgumentErrors
from aistack.mcp.auth.failure_limiter import CredentialGuard
from aistack.mcp.auth.policy import authorize

logger = logging.getLogger(__name__)

# Only deliberate ToolError messages reach callers; unexpected details stay masked.
# Authorization is attached once, here, so a tool is covered whether or not it says so.
# ArgumentErrors keeps a malformed call's values out of the answer (SEC-03).
mcp = FastMCP(
    "aistack",
    mask_error_details=True,
    middleware=[AuthMiddleware(auth=authorize), ArgumentErrors()],
)

# Register tools and routes before building the HTTP app.
from aistack.mcp.routes import health, invite, setup, transfer  # noqa: F401, E402
from aistack.mcp.tools import onboarding, skills, sync, teams  # noqa: F401, E402

# The dashboard's routes, registered last: they import the login path from the tools.
from aistack.api import dashboard  # noqa: F401, E402


def http_server_config(path: str, log_level: str, **bind) -> uvicorn.Config:
    """The uvicorn configuration AIStack is served with; `bind` is host and port, or nothing.

    One function so the test server runs what production runs: the settings below are
    security decisions, and a fixture with its own copy would prove nothing about them.
    """
    # http_app() captures auth at construction. Missing auth would expose the server.
    if mcp.auth is None:
        raise RuntimeError(
            "No token verifier is attached. build_application_context() must "
            "run before the MCP app is built, or the server accepts every "
            "request unauthenticated."
        )

    # Stateless, with plain JSON responses (ADR-0013): every request stands alone, so a
    # restart or a second replica never strands a client on a session that is gone, and
    # a new machine can call `join` with one HTTP request before it has an MCP client.
    app = mcp.http_app(path=path, transport="http", stateless_http=True, json_response=True)
    # Inside uvicorn's proxy-header handling, so the address it sees is the resolved client.
    return _uvicorn_config(CredentialGuard(app, get_failure_limiter), log_level, **bind)


def dashboard_server_config(log_level: str) -> uvicorn.Config:
    """`aistack dashboard` (ADR-0020): the dashboard's personal routes on 127.0.0.1 only.

    Bound to the loopback interface, so nothing off this computer reaches it. The host check
    turns away a page that renamed its own domain to 127.0.0.1 (DNS rebinding) and so would
    otherwise count as this origin. The caller passes the listening socket.
    """
    app = Starlette(
        routes=dashboard.LOCAL_ROUTES,
        middleware=[Middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1"])],
    )
    return _uvicorn_config(app, log_level)


def _uvicorn_config(app, log_level: str, **bind) -> uvicorn.Config:
    return uvicorn.Config(
        app,
        log_level=log_level.lower(),
        # Use the root logger's timestamp and logger-name format.
        log_config=None,
        # A transfer URL carries its ticket in the path (ADR-0010), and an access log line
        # is the request path. Off, so the one credential in a URL is never written down.
        access_log=False,
        timeout_graceful_shutdown=20,
        **bind,
    )


async def run_http_stream_server(host: str, port: int, path: str, log_level: str) -> None:
    config = http_server_config(path, log_level, host=host, port=port)

    logger.info(
        f"Starting AIStack {release()} over streamable HTTP. Host: '{host}'. Port: '{port}'. "
        f"Path: '{path}'."
    )
    await uvicorn.Server(config).serve()
