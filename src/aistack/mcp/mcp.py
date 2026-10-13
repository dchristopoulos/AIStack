import logging

import uvicorn
from fastmcp import FastMCP
from fastmcp.server.middleware import AuthMiddleware

from aistack.mcp.auth.policy import authorize

logger = logging.getLogger(__name__)

# Only deliberate ToolError messages reach callers; unexpected details stay masked.
# Authorization is attached once, here, so a tool is covered whether or not it says so.
mcp = FastMCP(
    "aistack",
    mask_error_details=True,
    middleware=[AuthMiddleware(auth=authorize)],
)

# Register tools and routes before building the HTTP app.
from aistack.mcp.routes import health, setup, transfer  # noqa: F401, E402
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

    return uvicorn.Config(
        # Stateless, with plain JSON responses (ADR-0013): every request stands alone, so a
        # restart or a second replica never strands a client on a session that is gone, and
        # a new machine can call `join` with one HTTP request before it has an MCP client.
        mcp.http_app(path=path, transport="http", stateless_http=True, json_response=True),
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
        f"Starting MCP server over streamable HTTP. Host: '{host}'. Port: '{port}'. "
        f"Path: '{path}'."
    )
    await uvicorn.Server(config).serve()
