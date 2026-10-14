import asyncio
import contextlib
import shlex
import socket

import httpx
import pytest
import uvicorn
from fastmcp.client import BearerAuth, Client, StreamableHttpTransport
from sqlalchemy import select

from aistack.bootstrap.configuration.settings.settings_config import Settings
from aistack.bootstrap.context import application_context
from aistack.db.engine import build_session_factory
from aistack.db.models.machine import Machine
from aistack.mcp.mcp import http_server_config
from aistack.services.token_service import hash_token
from tests.archives import skill_archive
from tests.conftest import INVITE_CODE
from tests.teams import SERVER_TEAM, everyone


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
            server = uvicorn.Server(http_server_config(path="/mcp", log_level="INFO"))
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


async def join(server_url: str, username: str = "dimitris", machine_name: str = "macbook") -> str:
    """A new user's first machine, as its token."""
    async with client_for(server_url, INVITE_CODE) as client:
        joined = await client.call_tool("join", {"username": username,
                                                 "machine_name": machine_name, "os": "MACOS"})
    return joined.structured_content["token"]


async def call(server_url: str, token: str, tool: str, **arguments) -> dict:
    async with client_for(server_url, token) as client:
        return (await client.call_tool(tool, arguments)).structured_content


async def second_machine(server_url: str, token: str, name: str = "desktop") -> str:
    """Another computer of the same user, as its token, read from the command they would paste."""
    added = await call(server_url, token, "add_machine", name=name, os="LINUX")
    return shlex.split(added["command"])[-1].removeprefix("Authorization: Bearer ")


async def push(server_url: str, token: str, name: str = "wizard", **archive) -> dict:
    """Upload a skill into the caller's own skills, which nobody else sees."""
    issued = await call(server_url, token, "push_skill", name=name)
    async with httpx.AsyncClient() as http:
        return (await http.put(issued["upload_url"],
                               content=skill_archive(name, **archive))).json()


async def share_with_everyone(server_url: str, token: str, name: str = "wizard") -> dict:
    """What one shared vault used to do by itself: put a skill in front of every user."""
    with application_context.get_session_factory().begin() as session:
        user_id = session.scalar(select(Machine.user_id)
                                 .where(Machine.token_hash == hash_token(token)))
        everyone(session, user_id)
    return await call(server_url, token, "share_skill", name=name, team=SERVER_TEAM)
