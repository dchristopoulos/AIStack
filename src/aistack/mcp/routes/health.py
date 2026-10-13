"""The health check a container runtime or a load balancer polls."""

import asyncio
import logging

from sqlalchemy import text
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from aistack.bootstrap.context.application_context import get_session_factory
from aistack.mcp.mcp import mcp

logger = logging.getLogger(__name__)

HEALTH_PATH = "/health"


@mcp.custom_route(HEALTH_PATH, methods=["GET"])
async def health(request: Request) -> Response:
    """200 when the server can reach its database, 503 when it cannot.

    Unauthenticated, so it says nothing but that: no version, no counts, no error text. The
    reason for a failure goes to the log, where the operator is the only reader.
    """
    try:
        await asyncio.to_thread(_ping_database)
    except Exception as error:
        logger.error(f"Health check failed. Error: '{type(error).__name__}'.")
        return JSONResponse({"status": "unavailable"}, status_code=503)
    return JSONResponse({"status": "ok"})


def _ping_database() -> None:
    with get_session_factory()() as session:
        session.execute(text("SELECT 1"))
