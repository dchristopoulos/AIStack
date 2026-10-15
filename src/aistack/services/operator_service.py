"""What the person running the server does to teams, from the scripts in docs/OPERATING.md.

No tool and no route reaches this module: its callers are the operator's own scripts, run
inside the container, so there is no caller to establish a place in a team for. Each function
still takes the team's lock, as every change to a team does (`team_service.lock`).
"""

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from aistack.commons.exceptions import NotFound, ValidationError
from aistack.commons.text import loggable
from aistack.db.models.team import Team, TeamKind, TeamMember, TeamRole
from aistack.db.models.user import User
from aistack.services import team_service

logger = logging.getLogger(__name__)


def name_admin(session: Session, team: str, username: str) -> None:
    """Make a member of a team its admin, for a team whose admins are all gone (ADR-0028)."""
    found = _team(session, team)
    member = team_service._member(session, found, username)
    member.role = TeamRole.ADMIN
    logger.info(f"Team admin named by the operator. Team: '{found.team_id}'. "
                f"Member: '{member.user_id}'.")


def take_out_of_teams(session: Session, username: str,
                      successors: dict[str, str] | None = None) -> list[str]:
    """Take someone out of every team they are in, before their computers are deleted.

    A team they are the only admin of needs a successor, named in `successors` as team to
    username, and is refused without one, before anything changes. A team they are the only
    member of is deleted. Their invites into each team are cancelled. Returns the teams.
    """
    successors = successors or {}
    user_id = session.scalar(select(User.user_id).where(User.username == username))
    if user_id is None:
        raise NotFound(f"There is no user named '{loggable(username)}'.")
    teams = session.scalars(
        select(Team).join(TeamMember, TeamMember.team_id == Team.team_id)
        .where(TeamMember.user_id == user_id, Team.kind == TeamKind.SHARED)
        .order_by(Team.name)).all()
    # By name, so two scripts locking the same teams cannot each wait for the other.
    for team in teams:
        team_service._lock_team(session, team.team_id)

    leaving = []
    for team in teams:
        them = team_service._member(session, team, username)
        alone = team_service._members_besides(session, team, user_id) == 0
        if not alone and them.role is TeamRole.ADMIN and _admins(session, team) == 1:
            if successors.get(team.name) in (None, username):
                raise ValidationError(
                    f"'{loggable(username)}' is the only admin of team '{team.name}'. Name "
                    f"another member to take it over, as successors={{'{team.name}': "
                    "'<username>'}.")
            team_service._member(session, team, successors[team.name]).role = TeamRole.ADMIN
        leaving.append((team, alone))

    for team, alone in leaving:
        if alone:
            team_service._delete_team(session, team)
        else:
            team_service._drop_member(session, team.team_id, user_id)
        logger.info(f"Taken out of a team by the operator. Team: '{team.team_id}'. "
                    f"User: '{user_id}'. Team deleted: '{alone}'.")
    return [team.name for team, _ in leaving]


def _team(session: Session, name: str) -> Team:
    team = session.scalar(select(Team).where(Team.name == name, Team.kind == TeamKind.SHARED))
    if team is None:
        raise NotFound(f"There is no team named '{loggable(name)}'.")
    team_service._lock_team(session, team.team_id)
    return team


def _admins(session: Session, team: Team) -> int:
    return len(session.scalars(select(TeamMember.team_member_id).where(
        TeamMember.team_id == team.team_id, TeamMember.role == TeamRole.ADMIN)).all())
