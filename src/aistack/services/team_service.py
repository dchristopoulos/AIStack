"""Teams, their members, and the groups inside them (ADR-0015).

Every function takes the caller's `user_id` from the verified bearer or session, and starts
by establishing the caller's place in the team through `visibility.membership`. A team the
caller is not in is answered like one that does not exist.
"""

import logging
import re
import secrets
import uuid
from dataclasses import dataclass

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from aistack.commons.exceptions import Conflict, NotFound, ValidationError
from aistack.commons.text import loggable
from aistack.db.models.skill import Skill
from aistack.db.models.skill_file import SkillFile
from aistack.db.models.skill_version import SkillVersion
from aistack.db.models.team import (
    GROUP_MAX_DEPTH,
    GROUP_NAME_MAX_LENGTH,
    GROUP_PATH_MAX_LENGTH,
    TEAM_NAME_MAX_LENGTH,
    GroupMember,
    GroupUnsubscribed,
    Team,
    TeamGroup,
    TeamKind,
    TeamMember,
    TeamRole,
)
from aistack.db.models.user import User
from aistack.services import visibility
from aistack.services.token_service import TEAM_INVITE_PREFIX, hash_token

logger = logging.getLogger(__name__)

# The username rule. A personal team carries its user's name, so the two share a namespace.
_NAME = re.compile(r"[a-z0-9]+([._-][a-z0-9]+)*")



@dataclass(frozen=True)
class TeamSummary:
    name: str
    kind: TeamKind
    role: TeamRole
    members: int


@dataclass(frozen=True)
class MemberSummary:
    username: str
    role: TeamRole
    sees_all_groups: bool
    groups: tuple[str, ...]


@dataclass(frozen=True)
class GroupSummary:
    # 'backend/aistack': the group's name with every group above it.
    path: str
    private: bool
    # Added to it directly.
    member: bool
    # Hears about changes to its skills. Unsubscribing from a group covers those under it.
    subscribed: bool


def create_team(session: Session, user_id: uuid.UUID, name: str) -> str:
    """Create a team with the caller as its admin."""
    name = _validated(name, "team name", TEAM_NAME_MAX_LENGTH)
    team = Team(name=name, kind=TeamKind.SHARED, created_by=user_id)
    try:
        with session.begin_nested():
            session.add(team)
    except IntegrityError as error:
        raise Conflict(f"The name '{name}' is already taken by a team or a user. Pick a "
                       "different one.") from error
    session.add(TeamMember(team_id=team.team_id, user_id=user_id, role=TeamRole.ADMIN))
    session.flush()
    logger.info(f"Team created. Team: '{team.team_id}'. User: '{user_id}'.")
    return team.name


def new_invite_code(session: Session, user_id: uuid.UUID, team: str) -> str:
    """Replace the team's invite code and return the new one. Admins only.

    Only its hash is stored, so this is the one moment the code can be read. Asking again
    makes a new code and the old one stops working, which is also how a leaked one is revoked.
    """
    found, _ = _as_admin(session, user_id, team)
    if found.kind is not TeamKind.SHARED:
        raise ValidationError(
            f"'{found.name}' is the server's own team: everyone who joins this server is in "
            "it already. Create a team to invite people to."
        )
    code = f"{TEAM_INVITE_PREFIX}{secrets.token_urlsafe(24)}"
    found.invite_hash = hash_token(code)
    logger.info(f"Team invite code replaced. Team: '{found.team_id}'. User: '{user_id}'.")
    return code


def join_team(session: Session, user_id: uuid.UUID, code: str) -> str:
    """Join the team an invite code belongs to."""
    team = invited_to(session, code)
    try:
        with session.begin_nested():
            session.add(TeamMember(team_id=team.team_id, user_id=user_id,
                                   role=TeamRole.MEMBER))
    except IntegrityError:
        pass  # Already a member: joining again is not an error.
    logger.info(f"Team joined. Team: '{team.team_id}'. User: '{user_id}'.")
    return team.name


def invited_to(session: Session, code: str) -> Team:
    """The team a working invite code belongs to. Resolved by indexed lookup on its hash.

    It also admits a new person at `join` (ADR-0019), so it is read again inside that
    transaction rather than trusted from the moment the bearer was verified.
    """
    team = None
    if isinstance(code, str) and code.strip().startswith(TEAM_INVITE_PREFIX):
        team = session.scalar(select(Team).where(Team.invite_hash == hash_token(code.strip())))
    if team is None:
        # Never echoes what was presented: a near-miss of a real code is still a secret.
        raise NotFound("That is not a team invite code that works. Ask a team admin for a "
                       "new one; a code stops working when a newer one is made.")
    return team


def list_teams(session: Session, user_id: uuid.UUID) -> list[TeamSummary]:
    """The teams the caller is in, their own personal team left out."""
    sizes = (
        select(TeamMember.team_id, func.count().label("members"))
        .group_by(TeamMember.team_id).subquery()
    )
    rows = session.execute(
        select(Team.name, Team.kind, TeamMember.role, sizes.c.members)
        .join(TeamMember, TeamMember.team_id == Team.team_id)
        .join(sizes, sizes.c.team_id == Team.team_id)
        .where(TeamMember.user_id == user_id, Team.kind != TeamKind.PERSONAL)
        .order_by(Team.name)
    ).all()
    return [TeamSummary(*row) for row in rows]


def members(session: Session, user_id: uuid.UUID, team: str) -> list[MemberSummary]:
    """Who is in the team. Any member may see this, as in any team's member list.

    A member's private groups are shown only to admins and to people in those groups.
    """
    found, me = visibility.membership(session, user_id, team)
    rows = session.execute(
        select(User.user_id, User.username, TeamMember.role, TeamMember.sees_all_groups)
        .join(TeamMember, TeamMember.user_id == User.user_id)
        .where(TeamMember.team_id == found.team_id)
        .order_by(User.username)
    ).all()
    mine = _groups_of(session, found.team_id, user_id)
    result = []
    for member_id, username, role, sees_all in rows:
        theirs = _groups_of(session, found.team_id, member_id)
        shown = tuple(sorted(
            name for name, private in theirs.items()
            if not private or me.role is TeamRole.ADMIN or name in mine))
        result.append(MemberSummary(username, role, sees_all, shown))
    return result


def groups(session: Session, user_id: uuid.UUID, team: str) -> list[GroupSummary]:
    """The team's groups the caller may see. An admin sees them all, to manage them.

    A private group is not listed for someone outside it: its name alone can say too much.
    """
    found, me = visibility.membership(session, user_id, team)
    access = visibility.group_access(session, user_id)
    rows = session.execute(
        select(TeamGroup.group_id, TeamGroup.path, TeamGroup.private)
        .where(TeamGroup.team_id == found.team_id).order_by(TeamGroup.path)).all()
    return [GroupSummary(path, private, group_id in access.member,
                         group_id not in access.unsubscribed)
            for group_id, path, private in rows
            if me.role is TeamRole.ADMIN or group_id in access.visible]


def set_subscribed(session: Session, user_id: uuid.UUID, team: str, group: str,
                   subscribed: bool) -> None:
    """Start or stop hearing about changes in a group and the groups under it.

    Anyone who can see the group may. It hides nothing; it only decides whether sync offers
    the group's updates.
    """
    found, _ = visibility.membership(session, user_id, team)
    target = _group(session, found, group)
    if target.group_id not in visibility.group_access(session, user_id).visible:
        raise NotFound(f"Team '{found.name}' has no group '{loggable(group)}'.")
    session.execute(delete(GroupUnsubscribed).where(GroupUnsubscribed.group_id == target.group_id,
                                                    GroupUnsubscribed.user_id == user_id))
    if not subscribed:
        session.add(GroupUnsubscribed(group_id=target.group_id, user_id=user_id))


def leave_team(session: Session, user_id: uuid.UUID, team: str) -> str:
    """Leave a team. The skills already taken from it stay in the caller's own skills."""
    found, me = visibility.membership(session, user_id, team)
    if found.kind is not TeamKind.SHARED:
        raise ValidationError(f"'{found.name}' is the server's own team; everyone on this "
                              "server is in it. There is nothing to leave.")
    _keep_an_admin(session, found, me, leaving=True)
    _drop_member(session, found.team_id, user_id)
    return found.name


def remove_member(session: Session, user_id: uuid.UUID, team: str, username: str) -> None:
    """Remove someone from a team. Admins only."""
    found, _ = _as_admin(session, user_id, team)
    if found.kind is not TeamKind.SHARED:
        raise ValidationError(f"Nobody can be removed from '{found.name}': it is the "
                              "server's own team. Revoking a person's machines is an "
                              "operator task; see docs/OPERATING.md.")
    their = _member(session, found, username)
    _keep_an_admin(session, found, their, leaving=True)
    _drop_member(session, found.team_id, their.user_id)
    logger.info(f"Team member removed. Team: '{found.team_id}'. Member: '{their.user_id}'. "
                f"By: '{user_id}'.")


def set_member(session: Session, user_id: uuid.UUID, team: str, username: str,
               role: str | None = None, sees_all_groups: bool | None = None) -> None:
    """Change a member's role or whether they see every group. Admins only."""
    found, _ = _as_admin(session, user_id, team)
    their = _member(session, found, username)
    if role is not None:
        try:
            new_role = TeamRole(role)
        except ValueError as error:
            raise ValidationError(f"role must be ADMIN or MEMBER. Received: "
                                  f"'{loggable(role)}'.") from error
        if new_role is TeamRole.MEMBER:
            _keep_an_admin(session, found, their, leaving=True)
        their.role = new_role
    if sees_all_groups is not None:
        their.sees_all_groups = bool(sees_all_groups)
    logger.info(f"Team member changed. Team: '{found.team_id}'. Member: '{their.user_id}'. "
                f"By: '{user_id}'.")


def create_group(session: Session, user_id: uuid.UUID, team: str, name: str,
                 parent: str | None = None, private: bool = False) -> str:
    """Create a group in a team, optionally inside another, with its creator in it.

    Admins only. Returns the new group's path.
    """
    found, _ = _as_admin(session, user_id, team)
    name = _validated(name, "group name", GROUP_NAME_MAX_LENGTH)
    path = name if parent is None else f"{_group(session, found, parent).path}/{name}"
    if path.count("/") >= GROUP_MAX_DEPTH or len(path) > GROUP_PATH_MAX_LENGTH:
        raise ValidationError(f"Groups nest at most {GROUP_MAX_DEPTH} deep, and '{path}' "
                              "would be deeper or longer than a path may be.")
    group = TeamGroup(team_id=found.team_id, path=path, private=bool(private))
    try:
        # A savepoint, so a taken name is a sentence and the caller's transaction survives.
        with session.begin_nested():
            session.add(group)
    except IntegrityError as error:
        raise Conflict(f"Team '{found.name}' already has a group '{path}'.") from error
    session.add(GroupMember(group_id=group.group_id, user_id=user_id))
    session.flush()
    return path


def set_group(session: Session, user_id: uuid.UUID, team: str, group: str,
              private: bool) -> None:
    """Make a group private or open. Admins only."""
    found, _ = _as_admin(session, user_id, team)
    _group(session, found, group).private = bool(private)


def set_group_member(session: Session, user_id: uuid.UUID, team: str, group: str,
                     username: str, member: bool) -> None:
    """Add someone to a group or take them out. Admins only; the person must be in the team."""
    found, _ = _as_admin(session, user_id, team)
    target = _group(session, found, group)
    their = _member(session, found, username)
    if member:
        try:
            with session.begin_nested():
                session.add(GroupMember(group_id=target.group_id, user_id=their.user_id))
        except IntegrityError:
            pass  # Already in it.
    else:
        session.execute(delete(GroupMember).where(GroupMember.group_id == target.group_id,
                                                  GroupMember.user_id == their.user_id))


def move_skill(session: Session, user_id: uuid.UUID, team: str, name: str,
               group: str | None) -> None:
    """Put a team skill in a group, or back at team level. Admins only.

    Nothing on any computer changes: where a skill sits decides who sees it in the team.
    """
    found, _ = _as_admin(session, user_id, team)
    skill = _skill(session, found, name)
    skill.group_id = None if group is None else _group(session, found, group).group_id


def remove_skill(session: Session, user_id: uuid.UUID, team: str, name: str) -> None:
    """Take a skill out of a team. Admins only.

    Copies people already took stay in their own skills: a machine never ran the team's copy.
    """
    found, _ = _as_admin(session, user_id, team)
    skill = _skill(session, found, name)
    versions = select(SkillVersion.skill_version_id).where(
        SkillVersion.skill_id == skill.skill_id)
    session.execute(delete(SkillFile).where(SkillFile.skill_version_id.in_(versions)))
    session.execute(delete(SkillVersion).where(SkillVersion.skill_id == skill.skill_id))
    session.delete(skill)
    logger.info(f"Team skill removed. Team: '{found.team_id}'. Skill: '{skill.name}'. "
                f"By: '{user_id}'.")


def _as_admin(session: Session, user_id: uuid.UUID, team: str) -> tuple[Team, TeamMember]:
    found, me = visibility.membership(session, user_id, team)
    if me.role is not TeamRole.ADMIN:
        raise ValidationError(f"Only an admin of team '{found.name}' can do that. Ask one "
                              "of its admins.")
    return found, me


def _member(session: Session, team: Team, username: str) -> TeamMember:
    found = session.scalar(
        select(TeamMember)
        .join(User, User.user_id == TeamMember.user_id)
        .where(TeamMember.team_id == team.team_id, User.username == username)
    )
    if found is None:
        raise NotFound(f"Team '{team.name}' has no member named '{loggable(username)}'.")
    return found


def _group(session: Session, team: Team, name: str) -> TeamGroup:
    found = session.scalar(select(TeamGroup).where(TeamGroup.team_id == team.team_id,
                                                   TeamGroup.path == name))
    if found is None:
        raise NotFound(f"Team '{team.name}' has no group '{loggable(name)}'.")
    return found


def _skill(session: Session, team: Team, name: str) -> Skill:
    found = session.scalar(select(Skill).where(Skill.team_id == team.team_id,
                                               Skill.name == name))
    if found is None:
        raise NotFound(f"Team '{team.name}' has no skill named '{loggable(name)}'.")
    return found


def _groups_of(session: Session, team_id: uuid.UUID, user_id: uuid.UUID) -> dict[str, bool]:
    """The groups of this team that a user was added to, as path → private."""
    return dict(session.execute(
        select(TeamGroup.path, TeamGroup.private)
        .join(GroupMember, GroupMember.group_id == TeamGroup.group_id)
        .where(TeamGroup.team_id == team_id, GroupMember.user_id == user_id)).all())


def _keep_an_admin(session: Session, team: Team, member: TeamMember, leaving: bool) -> None:
    """Refuse the change that would leave a team with nobody able to manage it."""
    if member.role is not TeamRole.ADMIN or not leaving:
        return
    admins = session.scalar(
        select(func.count()).select_from(TeamMember)
        .where(TeamMember.team_id == team.team_id, TeamMember.role == TeamRole.ADMIN))
    if admins <= 1:
        raise Conflict(f"That would leave team '{team.name}' with no admin. Make someone "
                       "else an admin first.")


def _drop_member(session: Session, team_id: uuid.UUID, user_id: uuid.UUID) -> None:
    in_team = select(TeamGroup.group_id).where(TeamGroup.team_id == team_id)
    session.execute(delete(GroupMember).where(GroupMember.user_id == user_id,
                                              GroupMember.group_id.in_(in_team)))
    session.execute(delete(TeamMember).where(TeamMember.team_id == team_id,
                                             TeamMember.user_id == user_id))


def _validated(name: str, field: str, max_length: int) -> str:
    if not isinstance(name, str) or not _NAME.fullmatch(name.strip()):
        shown = loggable(name) if isinstance(name, str) else type(name).__name__
        raise ValidationError(
            f"A {field} is lowercase letters and digits, joined by single '.', '-' or '_', "
            f"like 'backend' or 'acme-design'. Received: '{shown}'."
        )
    name = name.strip()
    if len(name) > max_length:
        raise ValidationError(f"The {field} is {len(name)} characters long, and the limit "
                              f"is {max_length}.")
    return name
