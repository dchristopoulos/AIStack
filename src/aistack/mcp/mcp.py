import logging

import uvicorn
from fastmcp import FastMCP

logger = logging.getLogger(__name__)

# mask_error_details is always on, never env-gated: a "helpful in development" switch is one
# misconfigured deployment away from returning a stack trace to a caller. Tools raise ToolError
# with a message they meant to send; everything else is masked.
mcp = FastMCP("aistack", mask_error_details=True)

# Importing the tool modules is what registers their @mcp.tool functions, and it has to happen
# before http_app() builds the ASGI app.
from aistack.mcp.tools import onboarding  # noqa: F401, E402


async def run_http_stream_server(host: str, port: int, path: str, log_level: str) -> None:
    logger.info(f"Starting MCP server over streamable HTTP. Host: '{host}'. Port: '{port}'. "
                f"Path: '{path}'.")

    config = uvicorn.Config(
        mcp.http_app(path=path, transport="http"),
        host=host,
        port=port,
        log_level=log_level.lower(),
        # Uvicorn's default log_config installs handlers of its own, which emit
        # "INFO:     Started server process [7]" with no timestamp or logger name. With no
        # config, its loggers propagate to the root handler and come out like every other line.
        log_config=None,
        # Access logging is off: the URL carries no secrets today, but a bearer in a query
        # string is the classic way a token reaches a log file, and this is the switch that
        # would have to be found and turned off afterwards.
        access_log=False,
        timeout_graceful_shutdown=20,
    )
    await uvicorn.Server(config).serve()
