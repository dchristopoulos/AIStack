import logging
from time import perf_counter
from typing import Literal, TypedDict

from fastmcp.server.dependencies import get_access_token, get_http_request

from aistack.bootstrap.context.application_context import get_session_factory
from aistack.commons.text import loggable
from aistack.mcp.auth.policy import ONBOARDING_TAG
from aistack.mcp.auth.principal import current_machine
from aistack.mcp.mcp import mcp
from aistack.mcp.mcp_error_handler import handle_mcp_errors
from aistack.mcp.server_url import mcp_endpoint_url
from aistack.services import onboarding_service

logger = logging.getLogger(__name__)


class JoinResult(TypedDict):
    username: str
    machine_name: str
    token: str
    team: str | None


@mcp.tool(
    # The only tool an invite code may reach; the policy reads this tag, not the name.
    tags={ONBOARDING_TAG},
    description="""Register a new user and their first machine on this AIStack server.

    Call this once per person, from the machine they are setting up, while connected with an
    invite code as the bearer token: the server's own, or a team's (it starts with 'aistinv_'),
    which also makes them a member of that team. It returns that machine's permanent token,
    which goes into the MCP configuration and authenticates every later connection.
    Registering another computer for someone who has already joined is add_machine, not this.

    Args:
        username: A lowercase handle (letters, digits, single . - _), up to 64 characters. It is
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
            - team: the team they joined with its invite code, or null for the server's code.
    """)
@handle_mcp_errors
def join(username: str, machine_name: str, os: Literal["MACOS", "WINDOWS", "LINUX"]) -> JoinResult:
    started_at = perf_counter()
    logger.debug(
        f"Joining. Username: '{loggable(username)}'. "
        f"Machine: '{loggable(machine_name)}'. OS: '{loggable(os)}'."
    )

    # A team's code is the bearer itself; the claim only says it was one (ADR-0019).
    bearer = get_access_token()
    team_invite = bearer.token if bearer.claims.get("invite") == "team" else None

    # Commit the user, machine, admin claim, and membership together before returning the token.
    with get_session_factory().begin() as session:
        joined = onboarding_service.join(session, username, machine_name, os, team_invite)
        result = JoinResult(
            username=joined.user.username,
            machine_name=joined.machine.name,
            token=joined.token,
            team=joined.team,
        )

    # Log identities explicitly; result contains the plaintext token.
    logger.info(
        f"Join completed. Username: '{loggable(joined.user.username)}'. "
        f"Machine: '{loggable(joined.machine.name)}'. OS: '{joined.machine.os.value}'. "
        f"Admin: '{joined.user.is_admin}'. Team: '{loggable(joined.team or '')}'. "
        f"Elapsed: '{(perf_counter() - started_at) * 1000:.0f}ms'."
    )
    return result


class AddMachineResult(TypedDict):
    machine_name: str
    os: str
    command: str


@mcp.tool(
    description="""Register another computer for the user who is already connected.

    Call this from a machine that has joined, when the user wants AIStack on a second computer
    ("add my Windows PC"). It returns one command for them to paste into a terminal on that
    other computer. There is nothing to redeem and the invite code is not involved.

    Args:
        name: What the new computer is called, up to 64 characters, unique among this user's
             machines (e.g. "windows-pc", "work-laptop").
        os: The new computer's operating system: MACOS, WINDOWS, or LINUX. Ask the user if it
           is not obvious from what they said — it is the other computer's, not this one's.

    Returns:
        AddMachineResult containing:
            - machine_name: the registered machine name
            - os: its operating system
            - command: a complete `claude mcp add` command carrying the new machine's
                      permanent token. Show it to the user exactly as returned, in a code
                      block, and tell them to run it on the other computer and then start
                      Claude Code there. It is shown exactly here and never again — the
                      server stores only a hash of the token.
    """)
@handle_mcp_errors
def add_machine(name: str, os: Literal["MACOS", "WINDOWS", "LINUX"]) -> AddMachineResult:
    started_at = perf_counter()
    caller = current_machine()
    logger.debug(
        f"Adding machine. Machine: '{loggable(name)}'. OS: '{loggable(os)}'. "
        f"User: '{caller.user_id}'."
    )

    # Resolve the address first: a server that cannot say where it lives should refuse
    # before it has registered a machine nobody can connect.
    endpoint = mcp_endpoint_url(get_http_request())

    with get_session_factory().begin() as session:
        added = onboarding_service.add_machine(session, caller.user_id, name, os)
        result = AddMachineResult(
            machine_name=added.machine.name,
            os=added.machine.os.value,
            command=_connect_command(endpoint, added.token),
        )

    # Log identities explicitly; result contains the plaintext token.
    logger.info(
        f"Machine added. Machine: '{loggable(added.machine.name)}'. "
        f"OS: '{added.machine.os.value}'. User: '{caller.user_id}'. "
        f"Elapsed: '{(perf_counter() - started_at) * 1000:.0f}ms'."
    )
    return result


def _connect_command(endpoint: str, token: str) -> str:
    """The one line that turns another computer into a registered machine.

    `--scope user` because Claude Code's default scope is a single project, and a vault that
    only answers in the folder where it was set up is not the product. Double quotes around
    the header are read the same way by sh, PowerShell, and cmd.
    """
    return (f"claude mcp add --transport http --scope user aistack {endpoint} "
            f'--header "Authorization: Bearer {token}"')
