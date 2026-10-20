import logging
from inspect import cleandoc
from time import perf_counter
from typing import Literal, TypedDict

from fastmcp.server.dependencies import get_access_token, get_http_request

from aistack.bootstrap.context.application_context import (
    get_failure_limiter,
    get_join_limiter,
    get_session_factory,
)
from aistack.commons.connect_commands import claude_code_command, codex_config
from aistack.commons.exceptions import Conflict, NotFound, TooManyAttempts, ValidationError
from aistack.commons.text import loggable
from aistack.mcp.auth.failure_limiter import client_address, note_failure
from aistack.mcp.auth.policy import ONBOARDING_TAG
from aistack.mcp.auth.principal import current_machine
from aistack.mcp.mcp import mcp
from aistack.mcp.mcp_error_handler import handle_mcp_errors
from aistack.mcp.server_url import mcp_endpoint_url
from aistack.services import computer_codes, onboarding_service
from aistack.services.token_service import hash_token

logger = logging.getLogger(__name__)


class JoinResult(TypedDict, total=False):
    status: str
    machine_id: str
    request_bearer: str
    options: dict
    expires_on: str
    username: str
    machine_name: str
    token: str
    team: str | None


@mcp.tool(
    # The only tool an invite code may reach; the policy reads this tag, not the name.
    tags={ONBOARDING_TAG},
    description=cleandoc("""Join with an invite, or explicitly select computer pairing.

    Legacy invite calls need username, machine_name and os (MACOS, WINDOWS, LINUX),
    with optional full_name. They create an account and first computer and return
    username, machine_name, token and team. Store the token only in agent configuration.

    Computer pairing never creates an account. With a computer code as Authorization
    bearer, pairing=reserve and reported machine_name/os reserve one request and return
    its separate request_bearer, reserved machine_id, options and expiry. With that
    request bearer, pairing=poll waits for approval, then returns a permanent token once.
    An optional fingerprint binds the OS-id digest on completion. pairing=confirm with
    setup={agents: [...], skills: count} reports setup after the token is configured.
    Codes cannot poll or retrieve a token. No credential belongs in a tool argument.
    """))
@handle_mcp_errors
def join(username: str | None = None, machine_name: str | None = None,
         os: Literal["MACOS", "WINDOWS", "LINUX"] | None = None,
         full_name: str | None = None, pairing: Literal["reserve", "poll", "confirm"] | None = None,
         fingerprint: str | None = None, setup: dict | None = None) -> JoinResult:
    bearer = get_access_token()
    kind = bearer.claims.get("pairing")
    if pairing is not None or kind is not None:
        try:
            with get_session_factory().begin() as session:
                if pairing == "reserve" and kind == "computer_code":
                    return computer_codes.reserve(session, bearer.token, machine_name, os)
                if pairing == "poll" and kind == "computer_request":
                    return computer_codes.poll(session, bearer.token, fingerprint)
                if pairing == "confirm" and kind == "computer_request":
                    return computer_codes.confirm(session, bearer.token, setup)
                raise NotFound(computer_codes.REFUSAL)
        except NotFound:
            note_failure(get_failure_limiter(), client_address(get_http_request()), "computer code")
            raise
    if username is None or machine_name is None or os is None:
        raise ValidationError("Joining with an invite needs username, machine_name and os. To add another computer, use Add a computer in the dashboard.")
    started_at = perf_counter()
    logger.debug(
        f"Joining. Username: '{loggable(username)}'. "
        f"Machine: '{loggable(machine_name)}'. OS: '{loggable(os)}'."
    )

    # A team's code is the bearer itself; the claim only says it was one (ADR-0019).
    bearer = get_access_token()
    team_invite = bearer.token if bearer.claims.get("invite") == "team" else None

    # A refused join says a username or team name exists, and leaves a team's code unused, so
    # each address and each team code is good for a few (SEC-08). The server's code is shared
    # by every newcomer, so it is counted by address only: one person's run must not lock out
    # the next person to join.
    limiter = get_join_limiter()
    keys = [f"address:{client_address(get_http_request())}"]
    if team_invite is not None:
        keys.append(f"code:{hash_token(team_invite)}")
    waits = [wait for key in keys if (wait := limiter.retry_after(key)) is not None]
    if waits:
        raise TooManyAttempts(
            f"Too many joins were refused for a name already taken, so this is paused for "
            f"{max(waits) // 60 + 1} minutes. Pick a name nobody on this server uses, then "
            "try again after that.")

    # Commit the user, machine, admin claim, and membership together before returning the token.
    try:
        with get_session_factory().begin() as session:
            joined = onboarding_service.join(session, username, machine_name, os, team_invite,
                                             full_name=full_name)
            result = JoinResult(
                username=joined.user.username,
                machine_name=joined.machine.name,
                token=joined.token,
                team=joined.team,
            )
    except Conflict:
        for key in keys:
            limiter.record(key)
        raise

    # Log identities explicitly; result contains the plaintext token.
    logger.info(
        f"Join completed. Username: '{loggable(joined.user.username)}'. "
        f"Machine: '{loggable(joined.machine.name)}'. OS: '{joined.machine.os.value}'. "
        f"Admin: '{joined.user.is_admin}'. Team: '{loggable(joined.team or '')}'. "
        f"Elapsed: '{(perf_counter() - started_at) * 1000:.0f}ms'."
    )
    return result


class AddMachineResult(TypedDict, total=False):
    id: str
    code: str
    status: str
    options: dict
    expires_on: str
    requested_on: str | None
    request: dict | None
    machine_id: str | None
    operator_issued: bool
    powershell_command: str
    machine_name: str
    os: str
    command: str
    codex_config: str


@mcp.tool(
    description=cleandoc("""Add another computer to the connected user's account.

    Prefer computer_code=true: returns a one-use code and join command, approval on by
    default. Options: name (otherwise hostname), expires_hours (1, 24, 168), agents
    (find, claude-code, codex), skills (library, empty), hook and approval (booleans).
    No permanent token accompanies a code. The dashboard can edit unused options,
    cancel the code and approve or deny its reported request.

    Legacy calls with name and os still return machine_name, os, a paste-ready command
    and codex_config, each carrying a permanent token. Ask which agent the computer
    uses, then show its result exactly. Tell the person that it holds a permanent key for that computer:
    paste it only there, and delete it from anywhere it was carried. If it leaks,
    revoke the computer. Create the skills folder first (mkdir -p ~/.claude/skills for
    Claude Code, ~/.agents/skills for Codex), restart the agent and say "sync aistack".
    Legacy token fields stay until an owner-approved minor release.
    """))
@handle_mcp_errors
def add_machine(name: str | None = None, os: Literal["MACOS", "WINDOWS", "LINUX"] | None = None,
                computer_code: bool = False, options: dict | None = None) -> AddMachineResult:
    if computer_code:
        caller = current_machine()
        base = mcp_endpoint_url(get_http_request())
        with get_session_factory().begin() as session:
            return computer_codes.commands(
                computer_codes.create(
                    session,
                    caller.user_id,
                    caller.machine_id,
                    caller.token_prefix,
                    options,
                ),
                base,
            )
    if name is None or os is None:
        raise ValidationError("Legacy add_machine needs name and os. Use computer_code=true for a one-use code with approval.")
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
        added = onboarding_service.add_machine(session, caller.user_id, name, os,
                                               added_by=caller.machine_id)
        result = AddMachineResult(
            machine_name=added.machine.name,
            os=added.machine.os.value,
            command=claude_code_command(endpoint, added.token),
            codex_config=codex_config(endpoint, added.token),
        )

    # Log identities explicitly; result contains the plaintext token.
    logger.info(
        f"Machine added. Machine: '{loggable(added.machine.name)}'. "
        f"OS: '{added.machine.os.value}'. User: '{caller.user_id}'. "
        f"Elapsed: '{(perf_counter() - started_at) * 1000:.0f}ms'."
    )
    return result
