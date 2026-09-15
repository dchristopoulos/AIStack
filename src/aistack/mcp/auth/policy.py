"""The one rule that says which principal may reach which tool.

ADR-0003 gives the server exactly two principals, so the policy is a single branch rather
than a table. It lives in middleware rather than on each tool because FastMCP's
per-component `auth=` is opt-in: a tool registered without it carries no check at all and is
listed and callable by every authenticated principal, including the bootstrap one, whose
bearer is a static code the whole team holds. Attached here the default falls the other way.
"""

from fastmcp.server.auth import AuthContext

from aistack.mcp.auth.scopes import BOOTSTRAP_SCOPE, MACHINE_SCOPE

# Tag a tool with this to move it into the onboarding half of the rule.
ONBOARDING_TAG = "onboarding"


def authorize(ctx: AuthContext) -> bool:
    """Onboarding tools take the invite code; every other tool takes a machine token."""
    # Keyed on a tag rather than a tool name: a rename carries its tag along, and a new tool
    # that declares nothing falls to MACHINE_SCOPE — the scope that denies the invite code.
    required = BOOTSTRAP_SCOPE if ONBOARDING_TAG in ctx.component.tags else MACHINE_SCOPE
    return ctx.token is not None and required in ctx.token.scopes
