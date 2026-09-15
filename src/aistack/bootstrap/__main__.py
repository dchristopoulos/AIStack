import asyncio
import logging
import sys

from aistack.bootstrap.configuration.settings.settings_config import Settings
from aistack.bootstrap.context.application_context import build_application_context

logger = logging.getLogger(__name__)

LOG_FORMAT = "%(asctime)s %(levelname)-8s [%(name)s.%(funcName)s] %(message)s"

# Loggers that print raw protocol payloads at DEBUG. A tool result containing a machine token
# goes over the wire in plaintext by definition, so at DEBUG these write the token to the log
# file — the one place the secrets rule says it must never appear. They are floored at INFO
# regardless of AISTACK_LOG_LEVEL rather than trusted to the operator's choice of level.
WIRE_LOGGERS = ("mcp.client", "mcp.server.streamable_http", "sse_starlette", "httpcore", "httpx")


def configure_logging(log_level: str) -> None:
    logging.basicConfig(level=log_level, format=LOG_FORMAT, force=True)
    for wire_logger in WIRE_LOGGERS:
        logging.getLogger(wire_logger).setLevel(max(logging.INFO,
                                                    logging.getLevelName(log_level)))


async def main() -> None:
    settings = Settings()
    configure_logging(settings.log_level)

    build_application_context(settings)

    # Imported after the context is built, so a missing invite code fails before a port opens.
    from aistack.mcp.mcp import run_http_stream_server

    await run_http_stream_server(host=settings.host, port=settings.port,
                                 path=settings.mcp_path, log_level=settings.log_level)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except ValueError as error:
        # Configuration is wrong, not the code. A traceback would bury the one line that says
        # which variable to set, so this exits loudly and readably instead. ValueError covers
        # both a field pydantic rejected and the invite-code check that deliberately is not one.
        logging.basicConfig(level="INFO", format=LOG_FORMAT, force=True)
        logger.error(f"AIStack cannot start: its configuration is invalid.\n{error}")
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("Received interrupt signal, shutting down...")
