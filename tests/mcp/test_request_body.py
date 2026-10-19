"""A body over the limit is refused before the rest of it is read (SEC-09)."""

import asyncio
from urllib.parse import urlsplit

import pytest
from sqlalchemy import func, select
from starlette.requests import Request

from aistack.bootstrap.context.application_context import get_session_factory
from aistack.commons.exceptions import ValidationError
from aistack.db.models.skill import Skill
from aistack.mcp.routes import transfer
from aistack.mcp.routes.request_body import bounded_body
from tests.mcp.conftest import call, join

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


async def test_a_body_of_exactly_the_limit_declared_and_sent_is_read_whole():
    request, _ = _streaming_request(chunks=LIMIT // CHUNK,
                                    headers=[(b"content-length", str(LIMIT).encode())])

    assert await bounded_body(request, LIMIT, "too big", timeout_seconds=5) == b"x" * LIMIT

async def test_a_stalled_body_is_cancelled_and_told_to_send_it_again():
    stalled = asyncio.Event()
    cancelled = asyncio.Event()

    async def receive():
        try:
            await stalled.wait()
        finally:
            cancelled.set()
        return {"type": "http.request", "body": b"", "more_body": False}

    request = Request({"type": "http", "method": "PUT", "path": "/transfer/upload/ticket",
                       "headers": []}, receive)
    # The outer deadline bounds a broken inner deadline too.
    async with asyncio.timeout(1):
        with pytest.raises(ValidationError, match="did not finish within 0 seconds.*Send it again"):
            await bounded_body(request, LIMIT, "too big", timeout_seconds=0)

    assert cancelled.is_set()


async def test_an_upload_that_stalls_is_refused_before_it_can_store_anything(
        server_url, monkeypatch):
    token = await join(server_url)
    upload_url = (await call(server_url, token, "push_skill", name="wizard"))["upload_url"]
    path = urlsplit(upload_url).path
    stalled = asyncio.Event()

    async def receive():
        await stalled.wait()
        return {"type": "http.request", "body": b"", "more_body": False}

    request = Request({
        "type": "http", "method": "PUT", "path": path, "headers": [],
        "path_params": {"ticket": path.rsplit("/", 1)[1]},
    }, receive)
    monkeypatch.setattr(transfer, "UPLOAD_READ_TIMEOUT_SECONDS", 0)

    async with asyncio.timeout(1):
        response = await transfer.upload_skill(request)

    assert response.status_code == 400
    assert b"did not finish within 0 seconds" in response.body
    assert b"Send it again" in response.body
    with get_session_factory().begin() as session:
        assert session.scalar(select(func.count()).select_from(Skill)) == 0
