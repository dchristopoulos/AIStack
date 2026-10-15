"""Read a request body without ever holding more of it than the route accepts (SEC-09)."""

import asyncio

from starlette.requests import Request

from aistack.commons.exceptions import ValidationError


async def bounded_body(request: Request, limit: int, too_large: str,
                       timeout_seconds: float) -> bytes:
    """The body, refused as soon as it passes `limit` bytes or takes longer than the timeout.

    `request.body()` would buffer whatever arrives, so one request could fill the process's
    memory before any length check ran. A declared Content-Length over the limit is refused
    before a byte is read.
    """
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        raise ValidationError(too_large)
    chunks: list[bytes] = []
    received = 0
    try:
        # Without a deadline a client could open requests and never finish them.
        async with asyncio.timeout(timeout_seconds):
            async for chunk in request.stream():
                received += len(chunk)
                if received > limit:
                    raise ValidationError(too_large)
                chunks.append(chunk)
    except TimeoutError:
        raise ValidationError(
            f"The request did not finish within {timeout_seconds:g} seconds, so it was "
            "dropped. Send it again."
        ) from None
    return b"".join(chunks)
