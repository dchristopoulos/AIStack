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
from datetime import datetime

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from aistack.commons.exceptions import Conflict, NotFound, ValidationError
from aistack.commons.text import loggable
from aistack.db.models.invite import INVITE_LIFETIME, Invite
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
from aistack.db.models.timestamps import as_utc, utc_now
from aistack.db.models.user import User
from aistack.services import visibility
from aistack.services.token_service import TEAM_INVITE_PREFIX, hash_token

logger = logging.getLogger(__name__)

# The username rule. A personal team carries its user's name, so the two share a namespace.
_NAME = re.compile(r"[a-z0-9]+([._-][a-z0-9]+)*")

_NOT_AN_INVITE = ("That is not a team invite code that works. An invite admits one person and "
                  "lasts seven days; ask someone in the team for a new one.")



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
    can_invite: bool
    groups: tuple[str, ...]


@dataclass(frozen=True)
class InviteSummary:
    """One invite as its team's admins and its maker see it. Never the code (ADR-0022)."""

    invite_id: str
    created_by: str
    created_on: datetime
    expires_on: datetime
    # PENDING, ACCEPTED, CANCELLED, or EXPIRED.
    status: str
    used_by: str | None


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
    """Make a new invite into the team and return its code (ADR-0022).

    Only its hash is stored, so this is the one moment the code can be read. Every invite is
    its own: one use, seven days, and making another cancels nothing. Admins may, and members
    an admin lets invite (ADR-0019).
    """
    found, _ = _as_inviter(session, user_id, team)
    code = f"{TEAM_INVITE_PREFIX}{secrets.token_urlsafe(24)}"
    now = utc_now()
    session.add(Invite(team_id=found.team_id, code_hash=hash_token(code), created_by=user_id,
                       created_on=now, expires_on=now + INVITE_LIFETIME))
    session.flush()
    logger.info(f"Team invite made. Team: '{found.team_id}'. User: '{user_id}'.")
    return code


def join_team(session: Session, user_id: uuid.UUID, code: str) -> str:
    """Join the team an invite belongs to, using the invite up."""
    return admit(session, invited_to(session, code), user_id)


def invited_to(session: Session, code: str) -> Invite:
    """The pending invite a code belongs to. Resolved by indexed lookup on its hash.

    It also admits a new person at `join` (ADR-0019), so it is read again inside that
    transaction rather than trusted from the moment the bearer was verified.
    """
    invite = None
    if isinstance(code, str) and code.strip().startswith(TEAM_INVITE_PREFIX):
        invite = session.scalar(select(Invite).where(Invite.code_hash == hash_token(code.strip())))
    if invite is None or _status(invite) != "PENDING":
        # Used, cancelled, expired and unknown read alike, and the code is never repeated: a
        # near-miss of a real one is still a secret.
        raise NotFound(_NOT_AN_INVITE)
    return invite


def is_open_invite(session: Session, code: str) -> bool:
    """Whether a code may stand as a bearer: an invite not cancelled and not expired.

    A used one still may, though it reaches only `join`, which refuses it: the client that
    used it sends one more request on the same connection after `join` returns.
    """
    if not (isinstance(code, str) and code.startswith(TEAM_INVITE_PREFIX)):
        return False
    invite = session.scalar(select(Invite).where(Invite.code_hash == hash_token(code)))
    return invite is not None and _status(invite) in ("PENDING", "ACCEPTED")


def invited_team(session: Session, code: str) -> str:
    """The name of the team a pending invite is for. The invite page shows it to the holder."""
    return session.get(Team, invited_to(session, code).team_id).name


def admit(session: Session, invite: Invite, user_id: uuid.UUID) -> str:
    """Make `user_id` a member of the invite's team, and mark the invite used by them.

    Someone already in the team leaves the invite for whoever it was meant for.
    """
    team = session.get(Team, invite.team_id)
    if session.scalar(select(TeamMember.team_member_id).where(
            TeamMember.team_id == team.team_id, TeamMember.user_id == user_id)) is not None:
        return team.name

    # Conditional on still being pending: of two people using one code at once, the second
    # waits for the first's row lock and then matches nothing.
    used = session.execute(
        update(Invite)
        .where(Invite.invite_id == invite.invite_id, Invite.used_on.is_(None),
               Invite.cancelled_on.is_(None))
        .values(used_by=user_id, used_on=utc_now())
        .execution_options(synchronize_session=False))
    if used.rowcount != 1:
        raise NotFound(_NOT_AN_INVITE)
    session.add(TeamMember(team_id=team.team_id, user_id=user_id, role=TeamRole.MEMBER))
    session.flush()
    logger.info(f"Team joined. Team: '{team.team_id}'. User: '{user_id}'.")
    return team.name


def invites(session: Session, user_id: uuid.UUID, team: str) -> list[InviteSummary]:
    """The team's invites, newest first: every one to an admin, their own to an inviter."""
    found, me = _as_inviter(session, user_id, team)
    creator, user = aliased(User), aliased(User)
    query = (select(Invite, creator.username, user.username)
             .join(creator, creator.user_id == Invite.created_by)
             .outerjoin(user, user.user_id == Invite.used_by)
             .where(Invite.team_id == found.team_id)
             .order_by(Invite.created_on.desc()))
    if me.role is not TeamRole.ADMIN:
        query = query.where(Invite.created_by == user_id)
    return [InviteSummary(invite_id=str(invite.invite_id), created_by=made_by,
                          created_on=as_utc(invite.created_on),
                          expires_on=as_utc(invite.expires_on), status=_status(invite),
                          used_by=used_by)
            for invite, made_by, used_by in session.execute(query).all()]


def cancel_invite(session: Session, user_id: uuid.UUID, team: str, invite_id: str) -> None:
    """Cancel a pending invite: one's own, or any of the team's for an admin."""
    found, me = _as_inviter(session, user_id, team)
    try:
        invite = session.get(Invite, uuid.UUID(invite_id))
    except (ValueError, TypeError, AttributeError):
        invite = None
    # Another team's invite, or another inviter's to a member, reads like one that is not there.
    if (invite is None or invite.team_id != found.team_id
            or (me.role is not TeamRole.ADMIN and invite.created_by != user_id)):
        raise NotFound(f"Team '{found.name}' has no invite '{loggable(str(invite_id))}' of "
                       "yours to cancel.")
    if invite.used_on is not None:
        raise ValidationError("That invite was already used, so there is nothing to cancel. "
                              "Remove the member instead if they should not be in the team.")
    if invite.cancelled_on is None:
        invite.cancelled_on = utc_now()
    logger.info(f"Team invite cancelled. Team: '{found.team_id}'. User: '{user_id}'.")


def _status(invite: Invite) -> str:
    if invite.used_on is not None:
        return "ACCEPTED"
    if invite.cancelled_on is not None:
        return "CANCELLED"
    if as_utc(invite.expires_on) <= utc_now():
        return "EXPIRED"
    return "PENDING"


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
        select(User.user_id, User.username, TeamMember.role, TeamMember.sees_all_groups,
               TeamMember.can_invite)
        .join(TeamMember, TeamMember.user_id == User.user_id)
        .where(TeamMember.team_id == found.team_id)
        .order_by(User.username)
    ).all()
    mine = _groups_of(session, found.team_id, user_id)
    result = []
    for member_id, username, role, sees_all, can_invite in rows:
        theirs = _groups_of(session, found.team_id, member_id)
        shown = tuple(sorted(
            name for name, private in theirs.items()
            if not private or me.role is TeamRole.ADMIN or name in mine))
        result.append(MemberSummary(username, role, sees_all, can_invite, shown))
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
    _keep_an_admin(session, found, me, leaving=True)
    _drop_member(session, found.team_id, user_id)
    return found.name


def remove_member(session: Session, user_id: uuid.UUID, team: str, username: str) -> None:
    """Remove someone from a team. Admins only."""
    found, _ = _as_admin(session, user_id, team)
    their = _member(session, found, username)
    _keep_an_admin(session, found, their, leaving=True)
    _drop_member(session, found.team_id, their.user_id)
    logger.info(f"Team member removed. Team: '{found.team_id}'. Member: '{their.user_id}'. "
                f"By: '{user_id}'.")


def set_member(session: Session, user_id: uuid.UUID, team: str, username: str,
               role: str | None = None, sees_all_groups: bool | None = None,
               can_invite: bool | None = None) -> None:
    """Change a member's role, whether they see every group, or whether they may invite.

    Admins only.
    """
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
    if can_invite is not None:
        their.can_invite = bool(can_invite)
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


def _as_inviter(session: Session, user_id: uuid.UUID, team: str) -> tuple[Team, TeamMember]:
    found, me = visibility.membership(session, user_id, team)
    if me.role is not TeamRole.ADMIN and not me.can_invite:
        raise ValidationError(f"Only an admin of team '{found.name}', or a member an admin "
                              "lets invite, can do that. Ask one of its admins.")
    return found, me


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
