import asyncio
import contextlib
import socket

import pytest
import uvicorn
from fastmcp.client import BearerAuth, Client, StreamableHttpTransport

from aistack.bootstrap.configuration.settings.settings_config import Settings
from aistack.bootstrap.context import application_context
from aistack.db.engine import build_session_factory
from aistack.mcp.mcp import mcp
from tests.conftest import INVITE_CODE


@pytest.fixture(name="anyio_backend")
def anyio_backend_fixture():
    return "asyncio"


@pytest.fixture(name="server_url")
async def server_url_fixture(portable_engine):
    """Use real HTTP so tests exercise bearer verification before tool dispatch."""
    try:
        application_context.build_application_context(
            Settings(
                _env_file=None,
                database_url=portable_engine.url.render_as_string(hide_password=False),
                aistack_invite_code=INVITE_CODE,
            )
        )
        # Pass the bound socket to Uvicorn so no other process can take its port.
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
            server = uvicorn.Server(uvicorn.Config(
                mcp.http_app(path="/mcp", transport="http"),
                log_config=None,
            ))
            serving = asyncio.create_task(server.serve(sockets=[listener]))
            try:
                async with asyncio.timeout(5):
                    while not server.started:
                        if serving.done():
                            await serving
                            raise RuntimeError("HTTP test server stopped before startup.")
                        await asyncio.sleep(0.01)

                yield f"http://127.0.0.1:{port}/mcp"
            finally:
                server.should_exit = True
                if not server.started:
                    serving.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await serving
    finally:
        application_context.dispose_application_context()


@pytest.fixture(name="session_factory")
def session_factory_fixture(portable_engine):
    return build_session_factory(portable_engine)


def client_for(server_url: str, bearer: str) -> Client:
    """An MCP client presenting `bearer`, which is the only thing the server authenticates on."""
    return Client(StreamableHttpTransport(server_url, auth=BearerAuth(bearer)))
