import asyncio

import pytest

from aistack.bootstrap.context import application_context
from tests.mcp.conftest import server_url_fixture


@pytest.mark.anyio
@pytest.mark.parametrize("raises", [True, False])
async def test_failed_server_startup_releases_its_socket_and_context(engine, monkeypatch, raises):
    sockets_seen = []

    async def failed_startup(self, sockets=None):
        sockets_seen.extend(sockets or [])
        if raises:
            raise RuntimeError("startup failed")

    monkeypatch.setattr("uvicorn.Server.serve", failed_startup)
    fixture = server_url_fixture.__wrapped__(engine)
    try:
        async with asyncio.timeout(1):
            with pytest.raises(RuntimeError, match="startup"):
                await anext(fixture)

        assert len(sockets_seen) == 1
        assert sockets_seen[0].fileno() == -1
        with pytest.raises(RuntimeError, match="has not been built"):
            application_context.get_session_factory()
    finally:
        await fixture.aclose()
        # Isolate later tests even if the fixture's cleanup regresses.
        application_context.dispose_application_context()
