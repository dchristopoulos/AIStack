import asyncio
import contextlib
import socket

import pytest
import uvicorn
from fastmcp.client import BearerAuth, Client, StreamableHttpTransport
from fastmcp.exceptions import ToolError
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from aistack.bootstrap.context import application_context
from aistack.bootstrap.configuration.settings.settings_config import Settings
from aistack.db.models.machine import Machine
from aistack.mcp.mcp import mcp
from tests.conftest import INVITE_CODE

# In-memory transport skips the HTTP layer, and the HTTP layer is where the bearer is read and
# verified. Every auth-bearing flow gets one real request over a real socket for that reason.
pytestmark = pytest.mark.anyio


@pytest.fixture(name="anyio_backend")
def anyio_backend_fixture():
    return "asyncio"


@pytest.fixture(name="server_url")
async def server_url_fixture(sqlite_url: str):
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


def _client(server_url: str, bearer: str) -> Client:
    return Client(StreamableHttpTransport(server_url, auth=BearerAuth(bearer)))


async def test_the_invite_code_joins_and_the_returned_token_authenticates(server_url,
                                                                         session_factory):
    async with _client(server_url, INVITE_CODE) as client:
        result = await client.call_tool("join", {"username": "dimitris",
                                                 "machine_name": "macbook",
                                                 "os": "MACOS"})

    joined = result.structured_content
    assert joined["username"] == "dimitris"
    assert joined["machine_name"] == "macbook"
    assert joined["token"].startswith("aist_")

    # The token the user was handed is the one the server will accept from now on.
    async with _client(server_url, joined["token"]) as client:
        assert "join" not in {tool.name for tool in await client.list_tools()}


async def test_the_bootstrap_principal_sees_join(server_url):
    async with _client(server_url, INVITE_CODE) as client:
        assert {tool.name for tool in await client.list_tools()} == {"join"}


async def test_a_machine_token_cannot_call_join(server_url, session_factory):
    async with _client(server_url, INVITE_CODE) as client:
        first = (await client.call_tool("join", {"username": "first", "machine_name": "one",
                                                 "os": "LINUX"})).structured_content

    async with _client(server_url, first["token"]) as client:
        with pytest.raises(ToolError):
            await client.call_tool("join", {"username": "second", "machine_name": "two",
                                            "os": "LINUX"})

    with session_factory() as session:
        assert session.scalars(select(Machine.name)).all() == ["one"]


@pytest.mark.parametrize("bearer", ["", "wrong-invite-code", "aist_not-a-real-token"])
async def test_an_unrecognized_bearer_is_rejected_before_any_tool_runs(server_url, bearer):
    with pytest.raises(Exception) as rejection:
        async with _client(server_url, bearer) as client:
            await client.call_tool("join", {"username": "x", "machine_name": "y", "os": "LINUX"})

    # Neither the presented bearer nor the configured invite code is echoed back.
    reported = str(rejection.value)
    assert bearer not in reported or bearer == ""
    assert INVITE_CODE not in reported


async def test_a_rejected_join_reports_what_to_fix_without_leaking_internals(server_url):
    async with _client(server_url, INVITE_CODE) as client:
        with pytest.raises(ToolError) as rejection:
            await client.call_tool("join", {"username": "  ", "machine_name": "macbook",
                                            "os": "MACOS"})

    assert "username is blank" in str(rejection.value)
    assert "ValidationError" not in str(rejection.value)


async def test_the_join_result_carries_the_token_and_no_aistack_log_line_does(server_url,
                                                                                caplog):
    with caplog.at_level("DEBUG"):
        async with _client(server_url, INVITE_CODE) as client:
            joined = (await client.call_tool("join", {"username": "dimitris",
                                                      "machine_name": "macbook",
                                                      "os": "MACOS"})).structured_content

    assert set(joined) == {"username", "machine_name", "token"}

    # Scoped to AIStack's own loggers: the transport necessarily carries the token in its
    # payload, and mcp/sse_starlette/httpx print that payload at DEBUG. Keeping them off DEBUG
    # is the server's job (see WIRE_LOGGERS in bootstrap.__main__), not this assertion's.
    aistack_lines = "\n".join(record.getMessage() for record in caplog.records
                              if record.name.startswith("aistack."))
    assert joined["token"] not in aistack_lines
    assert INVITE_CODE not in aistack_lines
