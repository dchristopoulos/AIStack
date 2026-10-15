import logging
import shlex
import tomllib

import pytest
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_access_token
from fastmcp.tools import FunctionTool
from sqlalchemy import select, update

from aistack.bootstrap.context import application_context
from aistack.db.models.machine import Machine
from aistack.db.models.user import User
from aistack.mcp.mcp import mcp
from aistack.services.token_service import generate_machine_token, hash_token
from tests.conftest import INVITE_CODE
from tests.mcp.conftest import client_for

pytestmark = pytest.mark.anyio

PROBE_TOOL_NAME = "claims_probe"


@pytest.fixture(name="claims_probe")
def claims_probe_fixture():
    """A machine-scope tool that reports who the server thinks is calling."""
    def claims_probe() -> dict:
        return dict(get_access_token().claims)

    mcp.add_tool(FunctionTool.from_function(claims_probe, name=PROBE_TOOL_NAME))
    yield
    mcp.local_provider.remove_tool(PROBE_TOOL_NAME)


async def _join(server_url, username="dimitris", machine_name="macbook") -> dict:
    async with client_for(server_url, INVITE_CODE) as client:
        return (await client.call_tool("join", {"username": username,
                                                "machine_name": machine_name,
                                                "os": "MACOS"})).structured_content


def _token_in(command: str) -> str:
    """Pull the bearer out of the command the way a shell would split it."""
    header = shlex.split(command)[-1]
    assert header.startswith("Authorization: Bearer ")
    return header.removeprefix("Authorization: Bearer ")


async def test_the_returned_command_connects_the_other_computer_as_a_new_machine(
        server_url, claims_probe, session_factory):
    joined = await _join(server_url)

    async with client_for(server_url, joined["token"]) as client:
        added = (await client.call_tool("add_machine", {"name": "windows-pc",
                                                        "os": "WINDOWS"})).structured_content
        caller = (await client.call_tool(PROBE_TOOL_NAME, {})).structured_content

    assert added["machine_name"] == "windows-pc"
    assert added["os"] == "WINDOWS"
    # User scope, or the vault only answers in the folder where the command was pasted.
    assert added["command"].startswith(
        f"claude mcp add --transport http --scope user aistack {server_url} --header ")

    new_token = _token_in(added["command"])
    assert new_token != joined["token"]
    # Codex on the other computer gets the same connection, with setup's approvals.
    codex = tomllib.loads(added["codex_config"])["mcp_servers"]["aistack"]
    assert codex["url"] == server_url
    assert codex["http_headers"] == {"Authorization": f"Bearer {new_token}"}
    assert {tool: rule["approval_mode"] for tool, rule in codex["tools"].items()} == {
        "sync": "approve", "get_skill": "approve", "push_skill": "approve"}

    # The pasted token authenticates as the new machine, not as the one that minted it.
    async with client_for(server_url, new_token) as client:
        new_machine = (await client.call_tool(PROBE_TOOL_NAME, {})).structured_content

    assert new_machine["user_id"] == caller["user_id"]
    assert new_machine["machine_id"] != caller["machine_id"]
    with session_factory() as session:
        stored = session.scalar(select(Machine).where(Machine.name == "windows-pc"))
        assert str(stored.machine_id) == new_machine["machine_id"]


async def test_the_caller_can_only_add_a_machine_for_themselves(server_url, session_factory):
    """There is no user argument to get wrong: the owner is the bearer's own user."""
    first = await _join(server_url, username="first", machine_name="one")
    await _join(server_url, username="second", machine_name="two")

    async with client_for(server_url, first["token"]) as client:
        await client.call_tool("add_machine", {"name": "extra", "os": "LINUX"})

    with session_factory() as session:
        owner = session.scalar(select(User.username).join(Machine, Machine.user_id == User.user_id)
                               .where(Machine.name == "extra"))
    assert owner == "first"


async def test_a_duplicate_machine_name_is_refused_with_what_to_change(server_url):
    joined = await _join(server_url, machine_name="macbook")

    async with client_for(server_url, joined["token"]) as client:
        with pytest.raises(ToolError) as rejection:
            await client.call_tool("add_machine", {"name": "macbook", "os": "MACOS"})

    assert "already have a machine named 'macbook'" in str(rejection.value)


async def test_the_new_token_appears_in_the_result_and_in_no_log_line(server_url, caplog):
    joined = await _join(server_url)

    with caplog.at_level(logging.DEBUG):
        async with client_for(server_url, joined["token"]) as client:
            added = (await client.call_tool("add_machine", {"name": "desktop",
                                                            "os": "LINUX"})).structured_content

    new_token = _token_in(added["command"])
    for record in caplog.records:
        if record.name.startswith("aistack."):
            assert new_token not in record.getMessage()
    assert any("Machine added" in record.getMessage() for record in caplog.records)


async def test_the_command_uses_the_public_url_when_one_is_configured(server_url, monkeypatch):
    """Behind a proxy the request's own address is the internal one, which nobody can paste."""
    joined = await _join(server_url)
    monkeypatch.setattr(application_context.get_settings(), "public_url",
                        "https://aistack.example.com")

    async with client_for(server_url, joined["token"]) as client:
        added = (await client.call_tool("add_machine", {"name": "desktop",
                                                        "os": "LINUX"})).structured_content

    assert " aistack https://aistack.example.com/mcp --header " in added["command"]


async def test_a_locked_out_user_recovers_by_rotating_a_token_hash(server_url, claims_probe,
                                                                 session_factory):
    """The documented recovery: replace the hash, keep the user and everything they pushed."""
    joined = await _join(server_url)
    replacement = generate_machine_token()

    with session_factory.begin() as session:
        session.execute(update(Machine).values(token_hash=hash_token(replacement)))

    async with client_for(server_url, replacement) as client:
        caller = (await client.call_tool(PROBE_TOOL_NAME, {})).structured_content

    with session_factory() as session:
        user = session.scalar(select(User))
    assert caller["user_id"] == str(user.user_id)
    assert user.username == joined["username"]
