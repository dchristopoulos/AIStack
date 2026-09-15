"""The one rule that says which principal may reach which tool.

ADR-0003 gives the server exactly two principals, so the policy is a single branch rather
than a table. It lives in middleware rather than on each tool because FastMCP's
per-component `auth=` is opt-in: a tool registered without it carries no check at all and is
listed and callable by every authenticated principal, including the bootstrap one, whose
bearer is a static code the whole team holds. Attached here the default falls the other way.
"""

from fastmcp.exceptions import AuthorizationError
from fastmcp.server.auth import AuthContext

from aistack.mcp.auth.scopes import BOOTSTRAP_SCOPE, MACHINE_SCOPE

# Tag a tool with this to move it into the onboarding half of the rule.
ONBOARDING_TAG = "onboarding"


def authorize(ctx: AuthContext) -> bool:
    """Onboarding tools take the invite code; every other tool takes a machine token."""
    # Keyed on a tag rather than a tool name: a rename carries its tag along, and a new tool
    # that declares nothing falls to MACHINE_SCOPE — the scope that denies the invite code.
    required = BOOTSTRAP_SCOPE if ONBOARDING_TAG in ctx.component.tags else MACHINE_SCOPE
    if ctx.token is not None and required in ctx.token.scopes:
        return True

    # Raised, not returned: on tools/call this is the text the agent reads, and on tools/list
    # the middleware swallows it and omits the tool, so the raise costs no disclosure there.
    raise AuthorizationError(_denial(required, ctx.component.name, ctx.token))


def _denial(required: str, tool_name: str, token) -> str:
    """Name the bearer the tool wants and the caller's next move — never a bearer itself.

    The caller's own scope is safe to state back: it describes the credential they just
    presented, not its value. `tool_name` is a registered component's name, not a caller
    string, so nothing here crosses a trust boundary on the way to the message.
    """
    if token is None:
        return f"'{tool_name}' requires a bearer token and this connection has none."

    if required == BOOTSTRAP_SCOPE:
        return (
            f"'{tool_name}' is an onboarding tool and takes the team invite code as its "
            f"bearer. This connection is authenticated as a registered machine, which has "
            f"already joined — registering another computer is add_machine."
        )

    return (
        f"'{tool_name}' takes a machine token as its bearer. This connection is "
        f"authenticated with the team invite code, which may only call 'join'. Call 'join' "
        f"first, then reconnect with the token it returns."
    )
