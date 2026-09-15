import pytest
from fastmcp.tools import FunctionTool

from aistack.mcp.auth.scopes import BOOTSTRAP_SCOPE, MACHINE_SCOPE
from aistack.mcp.mcp import mcp
from tests.conftest import INVITE_CODE
from tests.mcp.conftest import client_for

# FastMCP's per-component authorization is opt-in: a tool registered without `auth=` carries no
# check at all, so it is listed and callable for every authenticated principal — including the
# bootstrap one, whose bearer is a static code shared with the whole team. AGENTS.md says
# `machine` on everything except `join`, and one forgotten keyword is all it takes to break
# that. Nothing else in the suite fails when a tool omits it.

pytestmark = pytest.mark.anyio

# join is bootstrap-only by design (ADR-0003). Every other tool is machine scope. Adding a name
# here should mean deciding that a tool is reachable with nothing but the invite code.
BOOTSTRAP_ONLY_TOOLS = {"join"}


async def test_every_registered_tool_declares_an_authorization_check():
    unguarded = [tool.name for tool in await mcp.local_provider.list_tools() if tool.auth is None]

    assert not unguarded, (
        f"These tools carry no auth check, so any authenticated principal can list and call "
        f"them: {unguarded}. Declare auth=require_scopes(MACHINE_SCOPE) on the tool, or "
        f"BOOTSTRAP_SCOPE if it is genuinely part of onboarding."
    )


async def test_only_the_onboarding_tools_are_reachable_with_the_invite_code(server_url):
    """The scope rule from the caller's side, which is the side that matters.

    The test above proves a check exists. This proves the check is the right one: a bearer that
    is only the invite code sees onboarding and nothing else, whatever the tool modules grow to.
    """
    async with client_for(server_url, INVITE_CODE) as client:
        reachable = {tool.name for tool in await client.list_tools()}

    assert reachable == BOOTSTRAP_ONLY_TOOLS


async def test_a_tool_that_forgets_its_scope_is_caught(server_url):
    """The guard above is only worth having if it fails on the mistake it describes."""
    def forgot_its_scope() -> dict:
        return {}

    mcp.add_tool(FunctionTool.from_function(forgot_its_scope, name="forgot_its_scope"))
    try:
        unguarded = [tool.name for tool in await mcp.local_provider.list_tools()
                     if tool.auth is None]
        assert unguarded == ["forgot_its_scope"]

        # And it really is reachable with nothing but the invite code, which is why the guard
        # is a build failure rather than a note.
        async with client_for(server_url, INVITE_CODE) as client:
            assert "forgot_its_scope" in {tool.name for tool in await client.list_tools()}
    finally:
        mcp.local_provider.remove_tool("forgot_its_scope")


def test_the_two_scopes_are_distinct():
    assert BOOTSTRAP_SCOPE != MACHINE_SCOPE
