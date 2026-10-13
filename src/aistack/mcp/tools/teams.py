import logging
from time import perf_counter
from typing import TypedDict

from fastmcp.server.dependencies import get_http_request

from aistack.bootstrap.context.application_context import (
    get_session_factory,
    get_ticket_signer,
)
from aistack.mcp.auth.principal import current_machine
from aistack.mcp.mcp import mcp
from aistack.mcp.mcp_error_handler import handle_mcp_errors
from aistack.mcp.server_url import DASHBOARD_LOGIN_PATH, server_base_url
from aistack.services import team_service
from aistack.services.transfer_ticket import DASHBOARD_LINK_LIFETIME_SECONDS

logger = logging.getLogger(__name__)


class TeamEntry(TypedDict):
    name: str
    kind: str
    role: str
    members: int


class ListTeamsResult(TypedDict):
    teams: list[TeamEntry]


@mcp.tool(
    description="""List the teams the user is in.

    Use when the user asks which teams they have, or before share_skill to name one. Every
    user is in the server's own team (kind SERVER), which everyone on this server shares.
    Teams they created or joined have kind SHARED. Their own skills are not a team here:
    list_skills shows those.

    Returns:
        ListTeamsResult containing:
            - teams: one entry per team, by name, each with:
                - name: the team's name, used with share_skill, get_skill, invite_to_team
                - kind: SERVER or SHARED
                - role: ADMIN or MEMBER, the user's role in it
                - members: how many people are in it
    """)
@handle_mcp_errors
def list_teams() -> ListTeamsResult:
    with get_session_factory().begin() as session:
        teams = team_service.list_teams(session, current_machine().user_id)
    return ListTeamsResult(teams=[
        TeamEntry(name=team.name, kind=team.kind.value, role=team.role.value,
                  members=team.members)
        for team in teams
    ])


class CreateTeamResult(TypedDict):
    name: str
    role: str


@mcp.tool(
    description="""Create a team, with the user as its admin.

    Use when the user wants a place to share skills with particular people ("create a team
    called backend"). The team starts with only them in it. To let others in, call
    invite_to_team and give them the code.

    Args:
        name: Lowercase letters and digits joined by single '.', '-' or '_', like 'backend'.
             It must not be taken by another team or by a username.

    Returns:
        CreateTeamResult containing:
            - name: the team that was created
            - role: always ADMIN
    """)
@handle_mcp_errors
def create_team(name: str) -> CreateTeamResult:
    with get_session_factory().begin() as session:
        created = team_service.create_team(session, current_machine().user_id, name)
    return CreateTeamResult(name=created, role="ADMIN")


class InviteResult(TypedDict):
    team: str
    code: str


@mcp.tool(
    description="""Make a new invite code for a team. Only the team's admins can.

    Use when the user wants to let someone into a team they administer. Show the code to
    the user exactly as returned, in a code block, and tell them to send it to the person,
    who then says "join a team with this code" to their own agent. Anyone holding the code
    can join, so it goes to the people meant to have it and nowhere public.

    Each call replaces the previous code, which stops working. That is also how to cancel a
    code that reached the wrong person. The code is shown here and never again: the server
    keeps only a hash of it.

    Args:
        team: A team the user is an admin of.

    Returns:
        InviteResult containing:
            - team: the team the code admits to
            - code: the invite code
    """)
@handle_mcp_errors
def invite_to_team(team: str) -> InviteResult:
    caller = current_machine()
    with get_session_factory().begin() as session:
        code = team_service.new_invite_code(session, caller.user_id, team)
    # The result carries the code, so it is returned and never logged.
    logger.info(f"Team invite issued. User: '{caller.user_id}'.")
    return InviteResult(team=team, code=code)


class JoinTeamResult(TypedDict):
    team: str


@mcp.tool(
    description="""Join a team with an invite code someone gave the user.

    Use when the user has a team invite code (it starts with 'aistinv_') and says to join.
    This is not the server's invite code, which they used once to connect this computer.
    Afterwards the team's skills appear in list_skills; nothing is installed until they
    choose one.

    Args:
        code: The team invite code, exactly as they were given it.

    Returns:
        JoinTeamResult containing:
            - team: the team they are now in
    """)
@handle_mcp_errors
def join_team(code: str) -> JoinTeamResult:
    with get_session_factory().begin() as session:
        team = team_service.join_team(session, current_machine().user_id, code)
    return JoinTeamResult(team=team)


class DashboardResult(TypedDict):
    url: str
    expires_in_seconds: int


@mcp.tool(
    description="""Get a link that opens the user's AIStack dashboard in a browser, signed in.

    Use when the user wants to see or manage their skills and teams on a screen ("open my
    aistack dashboard"): which skills each of their computers has, sharing with a team,
    members, groups, and invites. Give the user the link to click. It signs in whoever
    opens it as this user, so it goes to them and nobody else. It can be used to sign in
    for a few minutes; after that, ask for a new one.

    Returns:
        DashboardResult containing:
            - url: the link to open. A credential: show it to the user only.
            - expires_in_seconds: how long the link can be used to sign in
    """)
@handle_mcp_errors
def open_dashboard() -> DashboardResult:
    started_at = perf_counter()
    caller = current_machine()
    ticket = get_ticket_signer().sign_dashboard_link(caller.user_id)
    # The URL carries the ticket, so it is returned and never logged.
    logger.info(f"Dashboard link issued. User: '{caller.user_id}'. "
                f"Elapsed: '{(perf_counter() - started_at) * 1000:.0f}ms'.")
    return DashboardResult(
        url=f"{server_base_url(get_http_request())}{DASHBOARD_LOGIN_PATH}/{ticket}",
        expires_in_seconds=DASHBOARD_LINK_LIFETIME_SECONDS,
    )
