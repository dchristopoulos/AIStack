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

# Register tools before building the HTTP app.
from aistack.mcp.tools import onboarding  # noqa: F401, E402


async def run_http_stream_server(host: str, port: int, path: str, log_level: str) -> None:
    # http_app() captures auth at construction. Missing auth would expose the server.
    if mcp.auth is None:
        raise RuntimeError(
            "No token verifier is attached. build_application_context() must "
            "run before the MCP app is built, or the server accepts every "
            "request unauthenticated."
        )

    logger.info(
        f"Starting MCP server over streamable HTTP. Host: '{host}'. Port: '{port}'. "
        f"Path: '{path}'."
    )

    config = uvicorn.Config(
        mcp.http_app(path=path, transport="http"),
        host=host,
        port=port,
        log_level=log_level.lower(),
        # Use the root logger's timestamp and logger-name format.
        log_config=None,
        # Avoid recording request URLs, which may contain credentials.
        access_log=False,
        timeout_graceful_shutdown=20,
    )
    await uvicorn.Server(config).serve()
