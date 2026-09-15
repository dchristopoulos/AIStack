import pytest
from fastmcp.exceptions import AuthorizationError
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


def _context(tags, scopes):
    component = FunctionTool.from_function(lambda: None, name="component", tags=tags)
    token = None if scopes is None else type("Token", (), {"scopes": scopes})()
    return AuthContext(token=token, component=component)


async def test_the_denial_an_agent_reads_names_its_next_move_and_no_secret(server_url):
    """The message over the wire, from both principals.

    A richer denial is a new place for a credential to leak: it is written on the rejection
    path, where the caller is by definition holding a bearer the server just refused.
    """
    def machine_only() -> dict:
        return {}

    mcp.add_tool(FunctionTool.from_function(machine_only, name="machine_only"))
    try:
        async with client_for(server_url, INVITE_CODE) as bootstrap:
            joined = (await bootstrap.call_tool("join", {"username": "reviewer",
                                                         "machine_name": "laptop",
                                                         "os": "LINUX"})).structured_content
            refused = await bootstrap.call_tool("machine_only", {}, raise_on_error=False)
        to_bootstrap = refused.content[0].text

        async with client_for(server_url, joined["token"]) as machine:
            refused = await machine.call_tool("join", {"username": "second",
                                                       "machine_name": "two",
                                                       "os": "LINUX"}, raise_on_error=False)
        to_machine = refused.content[0].text
    finally:
        mcp.local_provider.remove_tool("machine_only")

    # Each principal is told what that tool wants and what to do about it, not a scope name.
    assert "machine token" in to_bootstrap and "Call 'join'" in to_bootstrap
    assert "invite code" in to_machine and "add_machine" in to_machine

    for message in (to_bootstrap, to_machine):
        assert INVITE_CODE not in message
        assert joined["token"] not in message


@pytest.mark.parametrize(("tags", "scopes"), [
    ({ONBOARDING_TAG}, [BOOTSTRAP_SCOPE]),
    (set(), [MACHINE_SCOPE]),
])
def test_the_policy_admits_the_principal_the_tag_calls_for(tags, scopes):
    assert authorize(_context(tags, scopes)) is True


@pytest.mark.parametrize(("tags", "scopes"), [
    ({ONBOARDING_TAG}, [MACHINE_SCOPE]),
    (set(), [BOOTSTRAP_SCOPE]),
    (set(), []),
    ({ONBOARDING_TAG}, []),
    (set(), None),
    ({ONBOARDING_TAG}, None),
])
def test_the_policy_denies_every_other_pairing(tags, scopes):
    """The crossed pairs, the empty scope list, and the unauthenticated caller.

    `scopes=None` stands for no token at all: `required in None.scopes` would raise, and
    `run_auth_checks` masks an unexpected exception into a plain denial — so a regression
    there would deny correctly and silently, and no other assertion would notice.
    """
    with pytest.raises(AuthorizationError):
        authorize(_context(tags, scopes))


@pytest.mark.parametrize(("tags", "scopes", "expected"), [
    (set(), [BOOTSTRAP_SCOPE], "Call 'join'"),
    ({ONBOARDING_TAG}, [MACHINE_SCOPE], "add_machine"),
    (set(), None, "has none"),
])
def test_a_denial_says_what_to_present_instead(tags, scopes, expected):
    """Error text is agent-facing UX: the bearer the tool wants, and the next move."""
    with pytest.raises(AuthorizationError) as denial:
        authorize(_context(tags, scopes))

    assert expected in str(denial.value)
    assert "component" in str(denial.value)


def test_the_two_scopes_are_distinct():
    """Collapse these to one string and every check passes for every principal, silently."""
    assert BOOTSTRAP_SCOPE != MACHINE_SCOPE
