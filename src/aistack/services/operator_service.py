"""What the person running the server does to its users, computers and teams: the
`aistack admin` commands in docs/OPERATING.md.

No tool and no route reaches this module: its caller is the operator's own command, run
inside the container, so there is no caller to establish a place in a team for. Each change
to a team still takes the team's lock, as every change to a team does (`team_service.lock`).
"""

import logging
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from aistack.commons.exceptions import Conflict, NotFound, ValidationError
from aistack.commons.text import loggable
from aistack.db.models.machine import Machine
from aistack.db.models.machine_harness import MachineHarness
from aistack.db.models.project import Project
from aistack.db.models.skill import Skill
from aistack.db.models.team import Team, TeamKind, TeamMember, TeamRole
from aistack.db.models.timestamps import as_utc
from aistack.db.models.user import User
from aistack.services import onboarding_service, team_service, visibility
from aistack.services.token_service import generate_machine_token, hash_token

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
    user_id = _user(session, username).user_id
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


@dataclass(frozen=True)
class MachineRow:
    username: str
    name: str
    os: str
    created_on: datetime
    # Each harness this computer has synced, and when it last did.
    last_synced: dict[str, datetime | None]


def machines(session: Session, username: str | None = None) -> list[MachineRow]:
    """Every computer on the server, or one user's, by user and then name."""
    query = (select(User.username, Machine).join(Machine, Machine.user_id == User.user_id)
             .order_by(User.username, Machine.name))
    if username is not None:
        query = query.where(User.user_id == _user(session, username).user_id)
    found = session.execute(query).all()
    synced: dict[uuid.UUID, dict[str, datetime | None]] = {}
    for row in session.scalars(select(MachineHarness).where(
            MachineHarness.machine_id.in_([machine.machine_id for _, machine in found]))):
        if row.harness is not None:
            synced.setdefault(row.machine_id, {})[row.harness.value] = (
                None if row.last_synced_on is None else as_utc(row.last_synced_on))
    return [MachineRow(username=name, name=machine.name, os=_value(machine.os),
                       created_on=as_utc(machine.created_on),
                       last_synced=dict(sorted(synced.get(machine.machine_id, {}).items())))
            for name, machine in found]


@dataclass(frozen=True)
class NewToken:
    """A computer's new token, shown once to the operator to hand to its owner."""

    username: str
    machine: str
    token: str = field(repr=False)


def rotate(session: Session, username: str, machine: str) -> NewToken:
    """Give a computer a new token. The old one, and every dashboard session and transfer URL
    it opened, stops working on its next request (ADR-0027). The computer keeps its name and
    its skills."""
    found = _machine(session, username, machine)
    token = generate_machine_token()
    found.token_hash = hash_token(token)
    session.flush()
    logger.info(f"Machine token rotated by the operator. Machine: '{found.machine_id}'. "
                f"User: '{found.user_id}'.")
    return NewToken(username=username, machine=found.name, token=token)


def register_machine(session: Session, username: str, machine: str, os: str) -> NewToken:
    """Register a computer for someone who has none left to add one from, or whose join
    committed and lost its answer (ENT-11)."""
    user = _user(session, username)
    added = onboarding_service.add_machine(session, user.user_id, machine, os)
    logger.info(f"Machine registered by the operator. Machine: '{added.machine.machine_id}'. "
                f"User: '{user.user_id}'.")
    return NewToken(username=username, machine=added.machine.name, token=added.token)


def remove_machine(session: Session, username: str, machine: str) -> None:
    """Take a computer off the server. Unlike its owner, the operator may remove the last
    one: that is how someone leaves. Its placements and sync records go with it."""
    found = _machine(session, username, machine)
    session.delete(found)
    session.flush()
    logger.info(f"Machine removed by the operator. Machine: '{found.machine_id}'. "
                f"User: '{found.user_id}'.")


def offboard(session: Session, username: str,
             successors: dict[str, str] | None = None) -> tuple[list[str], list[str]]:
    """Take someone off the server: out of every team, as `take_out_of_teams` does, and then
    every computer of theirs off it, so no token, session or invite of theirs works. Their
    account and what they pushed stay. Returns the teams and the computers."""
    teams = take_out_of_teams(session, username, successors)
    user_id = _user(session, username).user_id
    removed = session.scalars(select(Machine).where(Machine.user_id == user_id)
                              .order_by(Machine.name)).all()
    for machine in removed:
        session.delete(machine)
    session.flush()
    logger.info(f"User taken off the server by the operator. User: '{user_id}'. "
                f"Machines removed: '{len(removed)}'.")
    return teams, [machine.name for machine in removed]


def rename_user(session: Session, username: str, new: str) -> None:
    """Give someone a new username, and their personal team with it. Every revision names
    them by id, so each `pushed_by` shows the new name. Refused when a user or a team already
    has it."""
    user = _user(session, username)
    new = onboarding_service.validated_username(new)
    if not _renamed(session, user, new):
        raise Conflict(f"A user or a team on this server is already called '{new}'. Pick a "
                       "different name. Nothing was changed.")
    logger.info(f"User renamed by the operator. User: '{user.user_id}'.")


def forget(session: Session, username: str,
           successors: dict[str, str] | None = None) -> tuple[str, list[str], list[str]]:
    """Erase someone and keep what other people hold (ADR-0034): `offboard` first, then their
    own Library and projects deleted, their full name cleared, and their username replaced by
    a random pseudonym that every revision they shared into a team now shows. Returns the
    pseudonym, the teams and the computers."""
    if username.startswith(onboarding_service.FORGOTTEN_PREFIX):
        raise ValidationError(f"'{loggable(username)}' has already been forgotten. Nothing "
                              "was changed.")
    teams, removed = offboard(session, username, successors)
    user = _user(session, username)
    personal = visibility.personal_team(session, user.user_id)
    # A teammate's copy is a skill of their own, and a team's copy is the team's: neither is
    # in this team, so both stay.
    team_service._delete_skills(session, select(Skill.skill_id)
                                .where(Skill.team_id == personal.team_id))
    session.execute(delete(Project).where(Project.user_id == user.user_id))
    user.full_name = None
    # Random, never derived from the old name, so it cannot be turned back into one.
    # ponytail: 4 hex is 65536 names; widen it if a server ever forgets that many people.
    for _ in range(100):
        pseudonym = f"{onboarding_service.FORGOTTEN_PREFIX}{secrets.token_hex(2)}"
        if _renamed(session, user, pseudonym):
            break
    else:
        raise Conflict("Could not find a free pseudonym. Nothing was changed.")
    logger.info(f"User forgotten by the operator. User: '{user.user_id}'.")
    return pseudonym, teams, removed


@dataclass(frozen=True)
class TeamRow:
    team: str
    username: str
    role: str


def teams(session: Session) -> list[TeamRow]:
    """Who is in each shared team. Personal teams are left out: each is one person's own."""
    rows = session.execute(
        select(Team.name, User.username, TeamMember.role)
        .join(TeamMember, TeamMember.team_id == Team.team_id)
        .join(User, User.user_id == TeamMember.user_id)
        .where(Team.kind == TeamKind.SHARED)
        .order_by(Team.name, User.username)).all()
    return [TeamRow(team=team, username=username, role=_value(role))
            for team, username, role in rows]


def _renamed(session: Session, user: User, new: str) -> bool:
    """Rename a user and their personal team, or change nothing and say False when a user or
    a team already has the name."""
    # Every user has a personal team of their name, so the team names cover the usernames.
    if session.scalar(select(Team.team_id).where(Team.name == new)) is not None:
        return False
    try:
        # A join that takes the name meanwhile fails one of the two unique names.
        with session.begin_nested():
            user.username = new
            visibility.personal_team(session, user.user_id).name = new
    except IntegrityError:
        return False
    return True


def _value(stored) -> str:
    # A value a newer release wrote reads as None here (ADR-0031).
    return "unknown" if stored is None else stored.value


def _user(session: Session, username: str) -> User:
    user = session.scalar(select(User).where(User.username == username))
    if user is None:
        raise NotFound(f"There is no user named '{loggable(username)}'.")
    return user


def _machine(session: Session, username: str, name: str) -> Machine:
    user = _user(session, username)
    machine = session.scalar(select(Machine).where(Machine.user_id == user.user_id,
                                                   Machine.name == name))
    if machine is None:
        raise NotFound(f"'{loggable(username)}' has no computer named '{loggable(name)}'.")
    return machine


def _team(session: Session, name: str) -> Team:
    team = session.scalar(select(Team).where(Team.name == name, Team.kind == TeamKind.SHARED))
    if team is None:
        raise NotFound(f"There is no team named '{loggable(name)}'.")
    team_service._lock_team(session, team.team_id)
    return team


def _admins(session: Session, team: Team) -> int:
    return len(session.scalars(select(TeamMember.team_member_id).where(
        TeamMember.team_id == team.team_id, TeamMember.role == TeamRole.ADMIN)).all())
