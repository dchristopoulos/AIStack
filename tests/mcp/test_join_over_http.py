import logging

import httpx
import pytest
from fastmcp.exceptions import ToolError
from sqlalchemy import select

from aistack.db.models.machine import Machine
from aistack.commons.text import loggable
from tests.conftest import INVITE_CODE
from tests.mcp.conftest import client_for

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("level", ["INFO", "DEBUG"])
@pytest.mark.parametrize("field", ["username", "machine_name"])
@pytest.mark.parametrize("value", ["x\nFORGED\x1b[2J", "A" * 100_000],
                         ids=["controls", "oversized"])
async def test_join_logs_escape_and_bound_names(server_url, caplog, level, field, value):
    arguments = {"username": "review", "machine_name": "laptop", "os": "LINUX", field: value}
    with caplog.at_level(level):
        async with client_for(server_url, INVITE_CODE) as client:
            result = await client.call_tool("join", arguments, raise_on_error=False)
    assert result.is_error == (len(value) > 64)
    records = [r for r in caplog.records if r.name.startswith("aistack.")]
    assert records
    for record in records:
        rendered = logging.Formatter().format(record)
        assert "\n" not in rendered and "\x1b" not in rendered
        assert len(rendered) < 1000
    if len(value) <= 64 or level == "DEBUG":
        assert any(loggable(value) in r.getMessage() for r in records)


async def test_invalid_os_is_rejected_by_the_http_schema(server_url, session_factory):
    async with client_for(server_url, INVITE_CODE) as client:
        with pytest.raises(ToolError):
            await client.call_tool("join", {"username": "review", "machine_name": "box",
                                            "os": "macos"})
    with session_factory() as session:
        assert session.scalars(select(Machine)).all() == []


async def test_the_invite_code_joins_and_the_returned_token_authenticates(server_url,
                                                                         session_factory):
    async with client_for(server_url, INVITE_CODE) as client:
        result = await client.call_tool("join", {"username": "dimitris",
                                                 "machine_name": "macbook",
                                                 "os": "MACOS"})

    joined = result.structured_content
    assert joined["username"] == "dimitris"
    assert joined["machine_name"] == "macbook"
    assert joined["token"].startswith("aist_")

    # The token the user was handed is the one the server will accept from now on.
    async with client_for(server_url, joined["token"]) as client:
        assert "join" not in {tool.name for tool in await client.list_tools()}


async def test_the_bootstrap_principal_sees_join(server_url):
    async with client_for(server_url, INVITE_CODE) as client:
        assert {tool.name for tool in await client.list_tools()} == {"join"}


async def test_a_machine_token_cannot_call_join(server_url, session_factory):
    async with client_for(server_url, INVITE_CODE) as client:
        first = (await client.call_tool("join", {"username": "first", "machine_name": "one",
                                                 "os": "LINUX"})).structured_content

    async with client_for(server_url, first["token"]) as client:
        with pytest.raises(ToolError):
            await client.call_tool("join", {"username": "second", "machine_name": "two",
                                            "os": "LINUX"})

    with session_factory() as session:
        assert session.scalars(select(Machine.name)).all() == ["one"]


@pytest.mark.parametrize("bearer", ["wrong-invite-code", "aist_not-a-real-token",
                                    INVITE_CODE[:-1], INVITE_CODE + "x"])
async def test_an_unrecognized_bearer_is_rejected_before_any_tool_runs(server_url,
                                                                      session_factory,
                                                                      bearer):
    with pytest.raises(Exception) as rejection:
        async with client_for(server_url, bearer) as client:
            await client.call_tool("join", {"username": "x", "machine_name": "y", "os": "LINUX"})

    reported = str(rejection.value)
    assert "401" in reported
    # Neither the presented bearer nor the configured invite code is echoed back.
    assert bearer not in reported
    assert INVITE_CODE not in reported

    # Rejected at the auth layer, so the tool never ran and wrote nothing.
    with session_factory() as session:
        assert session.scalars(select(Machine)).all() == []


async def test_a_rejected_join_reports_what_to_fix_without_leaking_internals(server_url):
    async with client_for(server_url, INVITE_CODE) as client:
        with pytest.raises(ToolError) as rejection:
            await client.call_tool("join", {"username": "  ", "machine_name": "macbook",
                                            "os": "MACOS"})

    assert "username is blank" in str(rejection.value)
    assert "ValidationError" not in str(rejection.value)


async def test_the_join_result_carries_the_token_and_no_aistack_log_line_does(server_url,
                                                                                caplog):
    with caplog.at_level("DEBUG"):
        async with client_for(server_url, INVITE_CODE) as client:
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


@pytest.mark.parametrize(("label", "headers"), [
    ("no Authorization header", {}),
    ("bare scheme", {"Authorization": "Bearer"}),
    ("wrong scheme", {"Authorization": "Basic abc123"}),
    ("garbage", {"Authorization": "!!!not-a-header!!!"}),
])
async def test_a_missing_or_malformed_authorization_header_is_rejected(server_url,
                                                                       session_factory,
                                                                       label, headers):
    """Absent and malformed, not merely wrong — those take a different path through the stack.

    The parametrized test above covers bearers that are well-formed and unrecognized. A request
    carrying no Authorization header at all never reaches the verifier, so it is the transport
    that has to reject it, and nothing in the suite proved that it does.
    """
    request = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    async with httpx.AsyncClient() as http:
        response = await http.post(
            server_url, json=request,
            headers={"Accept": "application/json, text/event-stream", **headers})

    assert response.status_code == 401, label
    assert INVITE_CODE not in response.text

    # Rejected before dispatch, so nothing was written.
    with session_factory() as session:
        assert session.scalars(select(Machine)).all() == []
