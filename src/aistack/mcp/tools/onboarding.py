import logging
from time import perf_counter
from typing import Literal, TypedDict

from fastmcp.server.auth import require_scopes

from aistack.bootstrap.context.application_context import get_session_factory
from aistack.mcp.auth.scopes import BOOTSTRAP_SCOPE
from aistack.mcp.mcp import mcp
from aistack.mcp.mcp_error_handler import handle_mcp_errors
from aistack.services import onboarding_service

logger = logging.getLogger(__name__)


class JoinResult(TypedDict):
    username: str
    machine_name: str
    token: str


@mcp.tool(
    # Authorization is FastMCP's own, evaluated before the handler runs and again when tools
    # are listed — so a machine token does not merely fail to call `join`, it never sees it.
    auth=require_scopes(BOOTSTRAP_SCOPE),
    description="""Register a new user and their first machine on this AIStack server.

    Call this once per person, from the machine they are setting up, while connected with the
    team invite code as the bearer token. It returns that machine's permanent token, which
    goes into the MCP configuration and authenticates every later connection. Registering
    another computer for someone who has already joined is add_machine, not this.

    Args:
        username: The name this person is known by in the vault, up to 64 characters. It is
                 shown as the pusher of every skill revision they upload, so a recognizable
                 handle beats a display name.
        machine_name: What this computer is called, up to 64 characters, unique among that
                     user's machines (e.g. "macbook", "work-laptop", "desktop").
        os: This machine's operating system: MACOS, WINDOWS, or LINUX. Required — the server
           cannot observe the client's platform, so state it.

    Returns:
        JoinResult containing:
            - username: the registered username
            - machine_name: the registered machine name
            - token: this machine's permanent token. Write it into the MCP configuration and
                    tell the user to restart their harness once. It is shown exactly here and
                    never again — the server stores only a hash of it.
    """)
@handle_mcp_errors()
def join(username: str, machine_name: str, os: Literal["MACOS", "WINDOWS", "LINUX"]) -> JoinResult:
    started_at = perf_counter()
    logger.debug(f"Joining. Username: '{username}'. Machine: '{machine_name}'. OS: '{os}'.")

    # One MCP call is one transaction: the user, the machine, and the admin claim land
    # together or not at all. The session is opened here and passed down; services never open
    # one of their own.
    with get_session_factory().begin() as session:
        joined = onboarding_service.join(session, username, machine_name, os)
        to_return = JoinResult(username=joined.user.username,
                               machine_name=joined.machine.name,
                               token=joined.token)

    # The token is absent from this line by design, and from every other line: the tool result
    # above is the only place it exists after this call returns.
    logger.info(f"Join completed. Username: '{joined.user.username}'. "
                f"Machine: '{joined.machine.name}'. OS: '{joined.machine.os.value}'. "
                f"Elapsed: '{(perf_counter() - started_at) * 1000:.0f}ms'.")
    return to_return
