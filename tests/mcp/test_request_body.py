"""A body over the limit is refused before the rest of it is read (SEC-09)."""

import pytest
from starlette.requests import Request

from aistack.commons.exceptions import ValidationError
from aistack.mcp.routes.request_body import bounded_body

pytestmark = pytest.mark.anyio

LIMIT = 16 * 1024
CHUNK = 4 * 1024


def _streaming_request(chunks: int, headers: list[tuple[bytes, bytes]] | None = None):
    """A request whose body arrives in `chunks` pieces, counting how many were read."""
    sent = {"count": 0}

    async def receive():
        sent["count"] += 1
        return {"type": "http.request", "body": b"x" * CHUNK,
                "more_body": sent["count"] < chunks}

    scope = {"type": "http", "method": "POST", "path": "/api/teams", "headers": headers or []}
    return Request(scope, receive), sent


@pytest.fixture(name="anyio_backend")
def anyio_backend_fixture():
    return "asyncio"


async def test_a_body_past_the_limit_is_refused_before_it_is_drained():
    # A megabyte, sent in pieces with no length declared.
    request, sent = _streaming_request(chunks=256)

    with pytest.raises(ValidationError, match="too big"):
        await bounded_body(request, LIMIT, "too big", timeout_seconds=5)

    assert sent["count"] == LIMIT // CHUNK + 1


async def test_a_declared_length_past_the_limit_is_refused_before_any_of_it_is_read():
    request, sent = _streaming_request(chunks=256,
                                       headers=[(b"content-length", str(1024 * 1024).encode())])

    with pytest.raises(ValidationError, match="too big"):
        await bounded_body(request, LIMIT, "too big", timeout_seconds=5)

    assert sent["count"] == 0


async def test_a_body_within_the_limit_is_read_whole():
    request, _ = _streaming_request(chunks=2)

    assert await bounded_body(request, LIMIT, "too big", timeout_seconds=5) == b"x" * 2 * CHUNK
