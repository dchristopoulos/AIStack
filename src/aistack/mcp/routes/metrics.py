"""`/metrics` for the operator's monitoring, behind a bearer of its own (STD-19)."""

import hashlib
import hmac
import logging

from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response

from aistack.bootstrap.context.application_context import get_failure_limiter, get_metrics_token
from aistack.commons import metrics as counts
from aistack.mcp.auth.failure_limiter import client_address, note_failure
from aistack.mcp.mcp import mcp

logger = logging.getLogger(__name__)

METRICS_PATH = "/metrics"


@mcp.custom_route(METRICS_PATH, methods=["GET"])
async def metrics(request: Request) -> Response:
    """The counts, to the bearer of AISTACK_METRICS_TOKEN. Without the setting, without the
    bearer and with a wrong one alike, a 404: nothing says the route is there.

    The bearer is compared in constant time over sha256 digests, as the invite code is, and
    a wrong one counts toward the throttle like any refused credential. It is never logged.
    """
    token = get_metrics_token()
    presented = request.headers.get("authorization", "")
    if token is None or not hmac.compare_digest(
            hashlib.sha256(presented.encode()).digest(),
            hashlib.sha256(f"Bearer {token.get_secret_value()}".encode()).digest()):
        if token is not None and presented:
            address = client_address(request)
            logger.info(f"Metrics bearer refused. Client: '{address}'.")
            note_failure(get_failure_limiter(), address, "metrics bearer")
        return PlainTextResponse("Not Found", status_code=404)
    return PlainTextResponse(counts.exposition(),
                             media_type="text/plain; version=0.0.4; charset=utf-8",
                             headers={"Cache-Control": "no-store"})
