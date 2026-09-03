import asyncio
import contextlib
import socket

import pytest
import uvicorn
from fastmcp.client import BearerAuth, Client, StreamableHttpTransport

from aistack.bootstrap.configuration.settings.settings_config import Settings
from aistack.bootstrap.context import application_context
from aistack.mcp.mcp import mcp
from tests.conftest import INVITE_CODE


@pytest.fixture(name="anyio_backend")
def anyio_backend_fixture():
    return "asyncio"


@pytest.fixture(name="server_url")
async def server_url_fixture(sqlite_url: str):
    """The real server, on a real socket, against a temporary database.

    The in-memory transport skips the HTTP layer, and the HTTP layer is where the bearer is read
    and verified — so every auth-bearing flow gets one real request over a real port.
    """
    application_context.build_application_context(
        Settings(database_url=sqlite_url, aistack_invite_code=INVITE_CODE)
    )

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    server = uvicorn.Server(uvicorn.Config(mcp.http_app(path="/mcp", transport="http"),
                                           host="127.0.0.1", port=port, log_config=None))
    serving = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.01)

    yield f"http://127.0.0.1:{port}/mcp"

    server.should_exit = True
    with contextlib.suppress(asyncio.CancelledError):
        await serving
    application_context.dispose_application_context()


def client_for(server_url: str, bearer: str) -> Client:
    """An MCP client presenting `bearer`, which is the only thing the server authenticates on."""
    return Client(StreamableHttpTransport(server_url, auth=BearerAuth(bearer)))
