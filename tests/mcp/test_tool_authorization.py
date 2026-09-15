import pytest
from fastmcp.server.auth import AuthContext
from fastmcp.tools import FunctionTool

from aistack.mcp.auth.policy import ONBOARDING_TAG, authorize
from aistack.mcp.auth.scopes import BOOTSTRAP_SCOPE, MACHINE_SCOPE
from aistack.mcp.mcp import mcp
from tests.conftest import INVITE_CODE
from tests.mcp.conftest import client_for

# One AuthMiddleware carries the whole rule, so a tool cannot opt out of authorization by
# omitting a keyword. What can still go wrong is the rule itself: a policy that reads the wrong
# half of the branch, or a default that admits instead of denies. That is what this file pins.

pytestmark = pytest.mark.anyio

# join is bootstrap-only by design (ADR-0003). Every other tool is machine scope. Adding a name
# here should mean deciding that a tool is reachable with nothing but the invite code.
BOOTSTRAP_ONLY_TOOLS = {"join"}


async def test_only_the_onboarding_tools_are_reachable_with_the_invite_code(server_url):
    """The scope rule from the caller's side, which is the side that matters."""
    async with client_for(server_url, INVITE_CODE) as client:
        reachable = {tool.name for tool in await client.list_tools()}

    assert reachable == BOOTSTRAP_ONLY_TOOLS


async def test_a_tool_that_declares_nothing_requires_a_machine_token(server_url):
    """The reason the rule sits in middleware: forgetting is safe, and provably so.

    Under per-component `auth=`, this tool would carry no check and the invite code would list
    and call it. The assertion is the inverse of that: untagged falls to the scope the invite
    code does not hold, and the machine token does.
    """
    def declared_nothing() -> dict:
        return {}

    mcp.add_tool(FunctionTool.from_function(declared_nothing, name="declared_nothing"))
    try:
        async with client_for(server_url, INVITE_CODE) as bootstrap:
            joined = (await bootstrap.call_tool("join", {"username": "reviewer",
                                                         "machine_name": "laptop",
                                                         "os": "LINUX"})).structured_content
            assert "declared_nothing" not in {tool.name for tool in await bootstrap.list_tools()}

        async with client_for(server_url, joined["token"]) as machine:
            assert "declared_nothing" in {tool.name for tool in await machine.list_tools()}
            assert (await machine.call_tool("declared_nothing", {})).structured_content == {}
    finally:
        mcp.local_provider.remove_tool("declared_nothing")


@pytest.mark.parametrize(("tags", "scopes", "allowed"), [
    ({ONBOARDING_TAG}, [BOOTSTRAP_SCOPE], True),
    ({ONBOARDING_TAG}, [MACHINE_SCOPE], False),
    (set(), [MACHINE_SCOPE], True),
    (set(), [BOOTSTRAP_SCOPE], False),
    (set(), [], False),
    ({ONBOARDING_TAG}, [], False),
])
def test_the_policy_branches_on_the_tag(tags, scopes, allowed):
    """Both halves of the branch, including the crossed pairs that must not pass."""
    component = FunctionTool.from_function(lambda: None, name="component", tags=tags)
    token = type("Token", (), {"scopes": scopes})()

    assert authorize(AuthContext(token=token, component=component)) is allowed


def test_an_unauthenticated_caller_is_denied_whatever_the_tag():
    """`ctx.token` is None on any transport without a bearer; `in None.scopes` would raise."""
    for tags in (set(), {ONBOARDING_TAG}):
        component = FunctionTool.from_function(lambda: None, name="component", tags=tags)
        assert authorize(AuthContext(token=None, component=component)) is False


def test_the_two_scopes_are_distinct():
    """Collapse these to one string and every check passes for every principal, silently."""
    assert BOOTSTRAP_SCOPE != MACHINE_SCOPE
