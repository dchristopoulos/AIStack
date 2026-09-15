from contextlib import suppress

import httpx
import pytest
from fastmcp.exceptions import ToolError
from fastmcp.server.auth import require_scopes
from fastmcp.server.dependencies import get_access_token
from fastmcp.tools import FunctionTool
from pydantic import SecretStr
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from aistack.mcp.auth.aistack_token_verifier import AIStackTokenVerifier
from aistack.mcp.auth.scopes import BOOTSTRAP_SCOPE, MACHINE_SCOPE
from aistack.mcp.mcp import mcp
from aistack.services import onboarding_service
from aistack.db.models.machine import Machine
from aistack.services.token_service import hash_token
from tests.conftest import INVITE_CODE
from tests.mcp.conftest import client_for

# The verifier resolves a bearer to machine_id and user_id so that no tool ever re-queries
# identity. join is the one tool that needs neither — it runs as the bootstrap principal — so
# without these tests the claims path ships written, populated, and read by nothing until the
# first machine-scope tool in a later ticket.
pytestmark = pytest.mark.anyio

PROBE_TOOL_NAME = "claims_probe"


@pytest.fixture(name="verifier")
def verifier_fixture(session_factory: sessionmaker[Session]) -> AIStackTokenVerifier:
    return AIStackTokenVerifier(SecretStr(INVITE_CODE), session_factory)


@pytest.fixture(name="joined")
def joined_fixture(session_factory: sessionmaker[Session]):
    with session_factory.begin() as session:
        return onboarding_service.join(session, "dimitris", "macbook", "MACOS")


async def test_a_machine_token_resolves_to_its_machine_and_user(verifier, joined):
    access_token = await verifier.verify_token(joined.token)

    assert access_token.scopes == [MACHINE_SCOPE]
    assert access_token.token == joined.token
    assert joined.token not in repr(access_token)
    assert joined.token not in str(access_token)
    assert access_token.claims == {"machine_id": str(joined.machine.machine_id),
                                   "user_id": str(joined.user.user_id)}


async def test_the_bootstrap_principal_carries_no_identity(verifier):
    access_token = await verifier.verify_token(INVITE_CODE)

    assert access_token.scopes == [BOOTSTRAP_SCOPE]
    assert access_token.token == INVITE_CODE
    assert INVITE_CODE not in repr(access_token)
    assert INVITE_CODE not in str(access_token)
    # A bootstrap bearer has no machine and no user yet. An identity claim appearing here would
    # mean a tool could act as somebody, on a bearer anyone holding the invite code can present.
    assert access_token.claims == {}


async def test_an_unrecognized_bearer_resolves_to_nothing(verifier, joined):
    assert await verifier.verify_token("aist_not-a-real-token") is None
    assert await verifier.verify_token(joined.token[:-1]) is None
    assert await verifier.verify_token(INVITE_CODE[:-1]) is None


@pytest.fixture(name="claims_probe")
def claims_probe_fixture():
    """Register a machine-scope tool that reports its caller, then take it away again.

    A later ticket's first machine-scope tool is the real consumer of the claims. This stands in
    for it so the path is proven now, and is removed afterwards because
    test_join_over_http.py asserts the server offers exactly one tool.
    """
    def claims_probe() -> dict:
        return dict(get_access_token().claims)

    mcp.add_tool(FunctionTool.from_function(claims_probe, name=PROBE_TOOL_NAME,
                                            auth=require_scopes(MACHINE_SCOPE)))
    yield
    mcp.local_provider.remove_tool(PROBE_TOOL_NAME)


async def test_a_machine_scope_tool_reads_its_caller_from_the_claims(server_url, claims_probe,
                                                                  session_factory):
    """The whole path: bearer on the wire, verifier, request scope, tool."""
    async with client_for(server_url, INVITE_CODE) as client:
        joined = [(await client.call_tool("join", {"username": username,
                                                   "machine_name": "macbook",
                                                   "os": "MACOS"})).structured_content
                  for username in ("dimitris", "maria")]

    for result in joined:
        with session_factory() as session:
            machine = session.scalar(select(Machine).where(
                Machine.token_hash == hash_token(result["token"])))
            expected = {"machine_id": str(machine.machine_id), "user_id": str(machine.user_id)}
        async with client_for(server_url, result["token"]) as client:
            claims = (await client.call_tool(PROBE_TOOL_NAME, {})).structured_content
        assert claims == expected


async def test_the_bootstrap_principal_cannot_reach_a_machine_scope_tool(server_url,
                                                                        claims_probe):
    async with client_for(server_url, INVITE_CODE) as client:
        assert PROBE_TOOL_NAME not in {tool.name for tool in await client.list_tools()}
        with pytest.raises(ToolError):
            await client.call_tool(PROBE_TOOL_NAME, {})


async def test_revocation_rejects_the_next_call_in_an_existing_session(server_url, claims_probe,
                                                                      session_factory):
    async with client_for(server_url, INVITE_CODE) as client:
        joined = (await client.call_tool("join", {"username": "review", "machine_name": "box",
                                                 "os": "LINUX"})).structured_content
    rejection = None
    # The SDK can report the same failed HTTP request again during transport cleanup.
    with suppress(httpx.HTTPStatusError):
        async with client_for(server_url, joined["token"]) as client:
            await client.call_tool(PROBE_TOOL_NAME, {})
            with session_factory.begin() as session:
                session.execute(delete(Machine).where(Machine.token_hash == hash_token(joined["token"])))
            with pytest.raises(Exception) as rejection:
                await client.call_tool(PROBE_TOOL_NAME, {})
    assert rejection is not None
    assert "401" in str(rejection.value)
    assert joined["token"] not in str(rejection.value)
