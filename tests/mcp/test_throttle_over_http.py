"""Refused credentials are counted per address and turn a guessing run away (SEC-02, STD-05).

The test server trusts X-Forwarded-For from 127.0.0.1, as uvicorn does by default, so a header
stands in for a second client.
"""

import logging

import httpx
import pytest
from fastmcp.client import BearerAuth, Client, StreamableHttpTransport
from fastmcp.exceptions import ToolError

from aistack.bootstrap.__main__ import ARGUMENT_ECHO_LOGGER, configure_logging
from aistack.mcp.auth.failure_limiter import FAILURE_LIMIT, REFUSED_JOIN_LIMIT, REJECTED_BEARER
from tests.conftest import INVITE_CODE
from tests.mcp.conftest import call, join

pytestmark = pytest.mark.anyio

GUESSER = "203.0.113.7"
LIST_TOOLS = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
MCP_HEADERS = {"Accept": "application/json, text/event-stream"}


def _base(server_url: str) -> str:
    return server_url.removesuffix("/mcp")


async def _post_with_bearer(http: httpx.AsyncClient, server_url: str, bearer: str,
                            address: str | None = None) -> httpx.Response:
    headers = {**MCP_HEADERS, "Authorization": f"Bearer {bearer}"}
    if address is not None:
        headers["X-Forwarded-For"] = address
    return await http.post(server_url, json=LIST_TOOLS, headers=headers)


async def test_wrong_bearers_from_one_address_are_turned_away(server_url, caplog):
    machine_token = await join(server_url)

    with caplog.at_level(logging.INFO):
        async with httpx.AsyncClient() as http:
            refused = [await _post_with_bearer(http, server_url, f"aist_wrong{n}", GUESSER)
                       for n in range(FAILURE_LIMIT)]
            throttled = await _post_with_bearer(http, server_url, "aist_wrong-again", GUESSER)
            # The right token from the same address waits too: it could be the guess that won.
            right_from_guesser = await _post_with_bearer(http, server_url, machine_token,
                                                         GUESSER)
            # Somebody else is not held up by it.
            elsewhere = await _post_with_bearer(http, server_url, machine_token)

    assert {response.status_code for response in refused} == {401}
    assert throttled.status_code == 429
    assert 0 < int(throttled.headers["retry-after"]) <= 60
    assert "Too many refused credentials" in throttled.json()["error"]
    assert right_from_guesser.status_code == 429
    assert elsewhere.status_code == 200

    # Each refusal names the address, which is what an operator or fail2ban acts on, and one
    # more line says the address was turned away. The turned-away requests add nothing.
    rejections = [record.getMessage() for record in caplog.records
                  if record.getMessage().startswith("Bearer rejected")]
    assert len(rejections) == FAILURE_LIMIT
    assert all(f"Client: '{GUESSER}'" in line for line in rejections)
    throttle_lines = [record.getMessage() for record in caplog.records
                      if record.getMessage().startswith("Client throttled")]
    assert len(throttle_lines) == 1 and GUESSER in throttle_lines[0]


async def test_a_rejected_bearer_is_told_what_aistack_can_do(server_url):
    async with httpx.AsyncClient() as http:
        response = await _post_with_bearer(http, server_url, "aist_replaced-token")

    assert response.status_code == 401
    assert response.json() == {"error": REJECTED_BEARER}
    assert "re-register" not in response.text
    assert "re-register" not in response.headers["www-authenticate"]
    assert "aist_replaced-token" not in response.text
    assert 'error="invalid_token"' in response.headers["www-authenticate"]


async def test_wrong_invite_links_count_toward_the_same_limit(server_url, caplog):
    machine_token = await join(server_url)
    async with httpx.AsyncClient() as http:
        with caplog.at_level(logging.INFO):
            pages = [await http.get(f"{_base(server_url)}/invite/aistinv_guess{n}",
                                    headers={"X-Forwarded-For": GUESSER})
                     for n in range(FAILURE_LIMIT)]
        page_after = await http.get(f"{_base(server_url)}/invite/aistinv_guess",
                                    headers={"X-Forwarded-For": GUESSER})
        bearer_after = await _post_with_bearer(http, server_url, machine_token, GUESSER)
        health = await http.get(f"{_base(server_url)}/health",
                                headers={"X-Forwarded-For": GUESSER})

    assert {page.status_code for page in pages} == {404}
    assert page_after.status_code == 429
    assert bearer_after.status_code == 429
    # Health answers anyway, so a throttled address can tell it apart from a server that is down.
    assert health.status_code == 200
    assert any(f"Invite page refused" in record.getMessage()
               and f"Client: '{GUESSER}'" in record.getMessage() for record in caplog.records)


async def test_wrong_dashboard_links_count_toward_the_limit(server_url):
    async with httpx.AsyncClient() as http:
        for n in range(FAILURE_LIMIT):
            await http.get(f"{_base(server_url)}/app/login/not-a-ticket-{n}",
                           headers={"X-Forwarded-For": GUESSER})
        after = await http.get(f"{_base(server_url)}/app/login/not-a-ticket",
                               headers={"X-Forwarded-For": GUESSER})

    assert after.status_code == 429


async def test_wrong_team_codes_from_a_signed_in_caller_count_toward_the_limit(server_url):
    maria = await join(server_url, "maria", "laptop")
    transport = StreamableHttpTransport(server_url, auth=BearerAuth(maria),
                                        headers={"X-Forwarded-For": GUESSER})
    async with Client(transport) as client:
        for n in range(FAILURE_LIMIT):
            with pytest.raises(ToolError):
                await client.call_tool("join_team", {"code": f"aistinv_guess{n}"})

    async with httpx.AsyncClient() as http:
        after = await _post_with_bearer(http, server_url, maria, GUESSER)
    assert after.status_code == 429


async def test_a_team_code_answers_a_few_taken_names_and_then_waits(server_url):
    """SEC-08: a refused join leaves the code unused, so it could list every username."""
    dimitris = await join(server_url)
    await call(server_url, dimitris, "create_team", name="acme")
    code = (await call(server_url, dimitris, "invite_to_team", team="acme"))["code"]

    refusals = []
    async with Client(StreamableHttpTransport(server_url, auth=BearerAuth(code))) as client:
        for _ in range(REFUSED_JOIN_LIMIT + 1):
            with pytest.raises(ToolError) as refusal:
                await client.call_tool("join", {"username": "dimitris",
                                                "machine_name": "laptop", "os": "LINUX"})
            refusals.append(str(refusal.value))

    assert all("already taken" in refusal for refusal in refusals[:REFUSED_JOIN_LIMIT])
    assert "Too many joins were refused" in refusals[-1]
    assert "dimitris" not in refusals[-1]


async def test_a_newcomer_on_another_address_still_joins_with_the_servers_code(server_url):
    """The server's code is everyone's, so one address's refused joins hold up that address."""
    await join(server_url)
    guessing = StreamableHttpTransport(server_url, auth=BearerAuth(INVITE_CODE),
                                       headers={"X-Forwarded-For": GUESSER})
    async with Client(guessing) as client:
        for _ in range(REFUSED_JOIN_LIMIT):
            with pytest.raises(ToolError):
                await client.call_tool("join", {"username": "dimitris",
                                                "machine_name": "laptop", "os": "LINUX"})

    assert await join(server_url, "maria", "laptop")


@pytest.fixture(name="server_logging")
def server_logging_fixture():
    """The server's own logging setup, put back afterwards: FastMCP's lines then reach the
    root handler, which is where the real server writes them."""
    import fastmcp

    root = logging.getLogger()
    fastmcp_logger = logging.getLogger("fastmcp")
    echoing = logging.getLogger(ARGUMENT_ECHO_LOGGER)
    saved = (root.level, list(root.handlers), list(fastmcp_logger.handlers),
             fastmcp_logger.propagate, fastmcp_logger.level, list(echoing.filters),
             fastmcp.settings.log_enabled)
    configure_logging("INFO")
    yield
    (root.level, root.handlers, fastmcp_logger.handlers, fastmcp_logger.propagate,
     fastmcp_logger.level, echoing.filters, fastmcp.settings.log_enabled) = saved


@pytest.mark.parametrize("arguments", [
    {"invite_code": "MARKER"},
    {"code": {"value": "MARKER"}},
    {"code": ["MARKER"]},
    {"cod": "MARKER"},
    {"MARKER": "x"},
], ids=["wrong-name", "object", "list", "typo", "as-a-name"])
async def test_a_malformed_join_team_echoes_no_code(server_url, server_logging, caplog,
                                                   arguments):
    """SEC-03: FastMCP quotes a rejected argument in its answer and its log line. Its records
    reach the root logger, and so this capture, only once the server's setup has run."""
    marker = "aistinv_markerQ7bZ"
    arguments = {key.replace("MARKER", marker): value for key, value in arguments.items()}
    arguments = {key: _replaced(value, marker) for key, value in arguments.items()}
    maria = await join(server_url, "maria", "laptop")

    with caplog.at_level(logging.DEBUG):
        async with Client(StreamableHttpTransport(server_url, auth=BearerAuth(maria))) as client:
            result = await client.call_tool("join_team", arguments, raise_on_error=False)

    answer = " ".join(getattr(part, "text", "") for part in result.content)
    assert result.is_error is True
    assert marker not in answer
    assert "It takes: code" in answer
    server_lines = [record for record in caplog.records
                    if not record.name.startswith(("httpx", "mcp.client"))]
    assert "Invalid arguments for tool 'join_team'" in caplog.text
    assert not [record.getMessage() for record in server_lines
                if marker in record.getMessage()]


def _replaced(value, marker):
    if isinstance(value, dict):
        return {key: _replaced(each, marker) for key, each in value.items()}
    if isinstance(value, list):
        return [_replaced(each, marker) for each in value]
    return value.replace("MARKER", marker)
