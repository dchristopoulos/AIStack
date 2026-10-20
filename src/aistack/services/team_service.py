"""Teams, their members, and the groups inside them (ADR-0015).

Every function takes the caller's `user_id` from the verified bearer or session, and starts
by establishing the caller's place in the team through `visibility.membership`. A team the
caller is not in is answered like one that does not exist.

Every change to a team starts with `lock`: it locks the team's row for the rest of the
transaction and reads the caller's place again. Two changes to one team then run one after
the other on PostgreSQL, as every transaction already does on SQLite (ADR-0014), so a check
such as "the team keeps an admin" reads what the change before it committed.
"""

import logging
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from aistack.commons.exceptions import Conflict, NotFound, ValidationError
from aistack.commons.text import loggable
from aistack.db.models.invite import INVITE_LIFETIME, Invite
from aistack.db.models.machine import Machine
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
from aistack.db.models.value_set import known
from aistack.db.ordering import bytewise
from aistack.services import visibility
from aistack.services.token_service import TEAM_INVITE_PREFIX, hash_token

logger = logging.getLogger(__name__)

# The username rule. A personal team carries its user's name, so the two share a namespace.
_NAME = re.compile(r"[a-z0-9]+([._-][a-z0-9]+)*")

# How long a used invite still stands as a bearer, for the requests that follow its `join`.
_BEARER_AFTER_USE = timedelta(minutes=5)
# How far back the invite lists go. Every pending invite is younger: they last a week.
_INVITES_SHOWN = timedelta(days=30)

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
    full_name: str | None = None


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
    logger.info(f"Team created. Team: '{team.name}' ({team.team_id}). User: '{user_id}'.")
    return team.name


def new_invite_code(session: Session, user_id: uuid.UUID, team: str) -> str:
    """Make a new invite into the team and return its code (ADR-0022)."""
    return new_invite(session, user_id, team)[0]


def new_invite(session: Session, user_id: uuid.UUID, team: str) -> tuple[str, uuid.UUID]:
    """Make a new invite into the team: its code, and its id, which the page names it by.

    Only its hash is stored, so this is the one moment the code can be read. Every invite is
    its own: one use, seven days, and making another cancels nothing. Admins may, and members
    an admin lets invite (ADR-0019).
    """
    found, _ = _as_inviter(session, user_id, team)
    code = f"{TEAM_INVITE_PREFIX}{secrets.token_urlsafe(24)}"
    now = utc_now()
    invite = Invite(team_id=found.team_id, code_hash=hash_token(code), created_by=user_id,
                    created_on=now, expires_on=now + INVITE_LIFETIME)
    session.add(invite)
    session.flush()
    logger.info(f"Team invite made. Team: '{found.name}' ({found.team_id}). User: '{user_id}'.")
    return code, invite.invite_id


def join_team(session: Session, user_id: uuid.UUID, code: str) -> str:
    """Join the team an invite belongs to, using the invite up.

    Whoever used the invite, while still in its team, may send it again and is told the team,
    as the first time: the answer to a join can be lost after it committed, and the retry is
    no guess. To anyone else a used invite reads like a code that never existed.
    """
    invite = _invite(session, code)
    if invite is not None and invite.used_by == user_id:
        team = session.scalar(
            select(Team.name)
            .join(TeamMember, TeamMember.team_id == Team.team_id)
            .where(Team.team_id == invite.team_id, TeamMember.user_id == user_id))
        if team is not None:
            return team
    return admit(session, _pending(session, invite), user_id)


def invited_to(session: Session, code: str) -> Invite:
    """The pending invite a code belongs to. Resolved by indexed lookup on its hash.

    It also admits a new person at `join` (ADR-0019), so it is read again inside that
    transaction rather than trusted from the moment the bearer was verified.
    """
    return _pending(session, _invite(session, code))


def _invite(session: Session, code: str) -> Invite | None:
    """The invite a code or invite link belongs to, in whatever state, by its hash."""
    if not isinstance(code, str):
        return None
    # The invite link is what people are sent, so it is accepted wherever the code is.
    # The code is its last segment: a token_urlsafe code has no '/' in it.
    code = code.strip().rstrip("/").rsplit("/", 1)[-1]
    if not code.startswith(TEAM_INVITE_PREFIX):
        return None
    return session.scalar(select(Invite).where(Invite.code_hash == hash_token(code)))


def _pending(session: Session, invite: Invite | None) -> Invite:
    if invite is None or not _usable(session, invite):
        # Used, cancelled, expired and unknown read alike, and the code is never repeated: a
        # near-miss of a real one is still a secret.
        raise NotFound(_NOT_AN_INVITE)
    return invite


def is_open_invite(session: Session, code: str) -> bool:
    """Whether a code may stand as a bearer: an invite `invited_to` would still accept.

    A code used moments ago still may, though it reaches only `join`, which refuses it: the
    client that used it sends more requests on the same connection after `join` returns, and
    a 401 there reads to the agent as a failed join. After that, a used code answers the same
    401 as a cancelled, expired or unknown one.
    """
    if not (isinstance(code, str) and code.startswith(TEAM_INVITE_PREFIX)):
        return False
    invite = session.scalar(select(Invite).where(Invite.code_hash == hash_token(code)))
    if invite is None:
        return False
    if invite.used_on is not None:
        return utc_now() - as_utc(invite.used_on) < _BEARER_AFTER_USE
    return _usable(session, invite)


def _usable(session: Session, invite: Invite) -> bool:
    """Pending, and its maker may still invite into its team and is still on the server.

    Losing the right to invite cancels a person's invites as it happens. This covers the
    operator's way of taking someone off the server, which deletes their machines and
    leaves their teams alone.
    """
    if _status(invite) != "PENDING":
        return False
    maker = session.scalar(select(TeamMember).where(TeamMember.team_id == invite.team_id,
                                                    TeamMember.user_id == invite.created_by))
    if maker is None or (maker.role is not TeamRole.ADMIN and not maker.can_invite):
        return False
    return session.scalar(select(Machine.machine_id).where(
        Machine.user_id == invite.created_by).limit(1)) is not None


def invited_team(session: Session, code: str) -> str:
    """The name of the team a pending invite is for. The invite page shows it to the holder."""
    return session.get(Team, invited_to(session, code).team_id).name


def admit(session: Session, invite: Invite, user_id: uuid.UUID) -> str:
    """Make `user_id` a member of the invite's team, and mark the invite used by them.

    Someone already in the team leaves the invite for whoever it was meant for.
    """
    team = _lock_team(session, invite.team_id)
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
    logger.info(f"Team joined. Team: '{team.name}' ({team.team_id}). User: '{user_id}'.")
    return team.name


def invites(session: Session, user_id: uuid.UUID, team: str) -> list[InviteSummary]:
    """The team's recent invites, newest first: every one to an admin, their own to an
    inviter."""
    found, me = _as_inviter(session, user_id, team, locked=False)
    return _invites_to(session, user_id, {found.team_id: me}).get(found.team_id, [])


def _invites_to(session: Session, user_id: uuid.UUID,
                places: dict[uuid.UUID, TeamMember]) -> dict[uuid.UUID, list[InviteSummary]]:
    """The invites of each team the caller may see invites of, newest first.

    Only those made in the last `_INVITES_SHOWN`: every pending one is younger than that, and
    the rest are history that would otherwise grow without end.
    """
    every = [team_id for team_id, me in places.items() if me.role is TeamRole.ADMIN]
    own = [team_id for team_id, me in places.items()
           if me.role is not TeamRole.ADMIN and me.can_invite]
    if not every and not own:
        return {}
    creator, user = aliased(User), aliased(User)
    rows = session.execute(
        select(Invite, creator.username, user.username)
        .join(creator, creator.user_id == Invite.created_by)
        .outerjoin(user, user.user_id == Invite.used_by)
        .where(or_(Invite.team_id.in_(every),
                   and_(Invite.team_id.in_(own), Invite.created_by == user_id)),
               Invite.created_on >= utc_now() - _INVITES_SHOWN)
        .order_by(Invite.created_on.desc())).all()
    result: dict[uuid.UUID, list[InviteSummary]] = {}
    for invite, made_by, used_by in rows:
        result.setdefault(invite.team_id, []).append(InviteSummary(
            invite_id=str(invite.invite_id), created_by=made_by,
            created_on=as_utc(invite.created_on), expires_on=as_utc(invite.expires_on),
            status=_status(invite), used_by=used_by))
    return result


def cancel_invite(session: Session, user_id: uuid.UUID, team: str, invite_id: str) -> None:
    """Cancel a pending invite: one's own, or any of the team's for an admin.

    It takes no team lock: the conditional update below is what decides a race with a join.
    """
    found, me = _as_inviter(session, user_id, team, locked=False)
    try:
        invite = session.get(Invite, uuid.UUID(invite_id))
    except (ValueError, TypeError, AttributeError):
        invite = None
    # Another team's invite, or another inviter's to a member, reads like one that is not there.
    if (invite is None or invite.team_id != found.team_id
            or (me.role is not TeamRole.ADMIN and invite.created_by != user_id)):
        raise NotFound(f"Team '{found.name}' has no invite '{loggable(str(invite_id))}' of "
                       "yours to cancel.")
    if invite.used_on is None and invite.cancelled_on is None:
        # Conditional, as `admit` is: a join that commits after the read above wins, and the
        # cancel then reports the truth instead of a success that kept nobody out.
        cancelled = session.execute(
            update(Invite)
            .where(Invite.invite_id == invite.invite_id, Invite.used_on.is_(None),
                   Invite.cancelled_on.is_(None))
            .values(cancelled_on=utc_now())
            .execution_options(synchronize_session=False))
        if cancelled.rowcount != 1:
            session.refresh(invite)
    if invite.used_on is not None:
        raise ValidationError("That invite was already used, so there is nothing to cancel. "
                              "Remove the member instead if they should not be in the team.")
    logger.info(f"Team invite cancelled. Team: '{found.name}' ({found.team_id}). "
                f"User: '{user_id}'.")


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
    places = visibility.memberships(session, user_id)
    sizes = dict(session.execute(
        select(TeamMember.team_id, func.count())
        .where(TeamMember.team_id.in_([team.team_id for team, _ in places]))
        .group_by(TeamMember.team_id)).all())
    return [TeamSummary(team.name, team.kind, me.role, sizes[team.team_id])
            for team, me in places]


@dataclass(frozen=True)
class TeamOverview:
    """One of the caller's teams, as the dashboard shows it."""

    summary: TeamSummary
    sees_all_groups: bool
    can_invite: bool
    members: list[MemberSummary]
    groups: list[GroupSummary]
    # Every recent invite to an admin, their own to an inviter, none to anyone else.
    invites: list[InviteSummary]


def overview(session: Session, user_id: uuid.UUID,
             access: visibility.GroupAccess | None = None) -> list[TeamOverview]:
    """Every team the caller is in, with what `members`, `groups` and `invites` say of each.

    Read in the same few statements however many teams, members and groups there are:
    the dashboard asks on every page load, and on SQLite it holds the write lock meanwhile.
    `access` is `visibility.group_access` for the caller, for one who already has it.
    """
    places = visibility.memberships(session, user_id)
    if not places:
        return []
    if access is None:
        access = visibility.group_access(session, user_id)
    by_team = {team.team_id: me for team, me in places}
    members_of = _members_of(session, access, by_team)
    groups_of = _groups_in(access, by_team, _team_groups(session, list(by_team)))
    invites_of = _invites_to(session, user_id, by_team)
    return [TeamOverview(
        summary=TeamSummary(team.name, team.kind, me.role, len(members_of[team.team_id])),
        sees_all_groups=me.sees_all_groups,
        can_invite=me.can_invite,
        members=members_of[team.team_id],
        groups=groups_of[team.team_id],
        invites=invites_of.get(team.team_id, []),
    ) for team, me in places]


def members(session: Session, user_id: uuid.UUID, team: str) -> list[MemberSummary]:
    """Who is in the team. Any member may see this, as in any team's member list.

    A member's groups are shown only where `visibility.shows_membership` says so: never a
    private group, or one under it, to someone outside it.
    """
    found, me = visibility.membership(session, user_id, team)
    access = visibility.group_access(session, user_id)
    return _members_of(session, access, {found.team_id: me})[found.team_id]


def _members_of(session: Session, access: visibility.GroupAccess,
                places: dict[uuid.UUID, TeamMember]) -> dict[uuid.UUID, list[MemberSummary]]:
    """The members of each team the caller is in, with the groups the caller may see them in.

    `places` is the caller's own membership of each, from `visibility`.
    """
    shown: dict[tuple[uuid.UUID, uuid.UUID], list[str]] = {}
    for team_id, member_id, group_id, path, private in session.execute(
            select(TeamGroup.team_id, GroupMember.user_id, TeamGroup.group_id, TeamGroup.path,
                   TeamGroup.private)
            .join(GroupMember, GroupMember.group_id == TeamGroup.group_id)
            .where(TeamGroup.team_id.in_(list(places)))).all():
        if visibility.shows_membership(access, places[team_id], group_id, private):
            shown.setdefault((team_id, member_id), []).append(path)
    result: dict[uuid.UUID, list[MemberSummary]] = {team_id: [] for team_id in places}
    for team_id, member_id, username, role, sees_all, can_invite, full_name in session.execute(
            select(TeamMember.team_id, User.user_id, User.username, TeamMember.role,
                   TeamMember.sees_all_groups, TeamMember.can_invite, User.full_name)
            .join(TeamMember, TeamMember.user_id == User.user_id)
            .where(TeamMember.team_id.in_(list(places)), known(TeamMember.role))
            .order_by(bytewise(User.username))).all():
        result[team_id].append(MemberSummary(
            username, role, sees_all, can_invite,
            tuple(sorted(shown.get((team_id, member_id), ()))), full_name))
    return result


def groups(session: Session, user_id: uuid.UUID, team: str) -> list[GroupSummary]:
    """The team's groups the caller may see. An admin sees them all, to manage them.

    A private group is not listed for someone outside it: its name alone can say too much.
    """
    found, me = visibility.membership(session, user_id, team)
    access = visibility.group_access(session, user_id)
    return _groups_in(access, {found.team_id: me},
                      _team_groups(session, [found.team_id]))[found.team_id]


def _team_groups(session: Session,
                 team_ids: list[uuid.UUID]) -> list[tuple[uuid.UUID, uuid.UUID, str, bool]]:
    return list(session.execute(
        select(TeamGroup.team_id, TeamGroup.group_id, TeamGroup.path, TeamGroup.private)
        .where(TeamGroup.team_id.in_(team_ids)).order_by(bytewise(TeamGroup.path))).all())


def _groups_in(access: visibility.GroupAccess, places: dict[uuid.UUID, TeamMember],
               rows: list[tuple[uuid.UUID, uuid.UUID, str, bool]]
               ) -> dict[uuid.UUID, list[GroupSummary]]:
    result: dict[uuid.UUID, list[GroupSummary]] = {team_id: [] for team_id in places}
    for team_id, group_id, path, private in rows:
        if places[team_id].role is TeamRole.ADMIN or group_id in access.visible:
            result[team_id].append(GroupSummary(path, private, group_id in access.member,
                                                group_id not in access.unsubscribed))
    return result


def set_subscribed(session: Session, user_id: uuid.UUID, team: str, group: str,
                   subscribed: bool) -> None:
    """Start or stop hearing about changes in a group and the groups under it.

    Anyone who can see the group may. It hides nothing; it only decides whether sync offers
    the group's updates.
    """
    found, _ = visibility.membership(session, user_id, team)
    # Looked up among the groups the caller sees, so a hidden one costs what a missing one does.
    target = session.scalar(select(TeamGroup).where(
        TeamGroup.team_id == found.team_id, TeamGroup.path == group,
        TeamGroup.group_id.in_(visibility.group_access(session, user_id).visible)))
    if target is None:
        raise NotFound(f"Team '{found.name}' has no group '{loggable(group)}'.")
    session.execute(delete(GroupUnsubscribed).where(GroupUnsubscribed.group_id == target.group_id,
                                                    GroupUnsubscribed.user_id == user_id))
    if not subscribed:
        try:
            with session.begin_nested():
                session.add(GroupUnsubscribed(group_id=target.group_id, user_id=user_id))
        except IntegrityError:
            pass  # The same choice, made at the same moment from somewhere else.
    logger.info(f"Group {'subscribed' if subscribed else 'unsubscribed'}. "
                f"Team: '{found.name}' ({found.team_id}). Group: '{target.path}'. "
                f"User: '{user_id}'.")


def leave_team(session: Session, user_id: uuid.UUID, team: str) -> str:
    """Leave a team. The skills already taken from it stay in the caller's own skills.

    The last member leaving deletes the team (ADR-0028): nobody is kept in one.
    """
    found, me = lock(session, user_id, team)
    if _members_besides(session, found, user_id) == 0:
        _delete_team(session, found)
        logger.info(f"Team deleted by its last member leaving. "
                    f"Team: '{found.name}' ({found.team_id}). "
                    f"User: '{user_id}'.")
        return found.name
    _keep_an_admin(session, found, me, leaving=True)
    _drop_member(session, found.team_id, user_id)
    logger.info(f"Team left. Team: '{found.name}' ({found.team_id}). User: '{user_id}'.")
    return found.name


def delete_team(session: Session, user_id: uuid.UUID, team: str) -> str:
    """Delete a team with its copies of its skills, its groups and its invites. Admins only.

    Every copy a member took stays theirs, in their Library and on their computers, because
    a machine installs only from the Library (ADR-0015, ADR-0028). The name is free again.
    """
    found, _ = _as_admin(session, user_id, team)
    _delete_team(session, found)
    logger.info(f"Team deleted. Team: '{found.name}' ({found.team_id}). By: '{user_id}'.")
    return found.name


def remove_member(session: Session, user_id: uuid.UUID, team: str, username: str) -> None:
    """Remove someone from a team. Admins only."""
    found, _ = _as_admin(session, user_id, team)
    their = _member(session, found, username)
    _keep_an_admin(session, found, their, leaving=True)
    _drop_member(session, found.team_id, their.user_id)
    logger.info(f"Team member removed. Team: '{found.name}' ({found.team_id}). "
                f"Member: '{their.user_id}'. "
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
    if their.role is not TeamRole.ADMIN and not their.can_invite:
        # Invites die with the right to make them.
        _cancel_invites_by(session, found.team_id, their.user_id)
    logger.info(f"Team member changed. Team: '{found.name}' ({found.team_id}). "
                f"Member: '{their.user_id}'. "
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
    logger.info(f"Group created. Team: '{found.name}' ({found.team_id}). Group: '{path}'. "
                f"Private: '{bool(private)}'. By: '{user_id}'.")
    return path


def set_group(session: Session, user_id: uuid.UUID, team: str, group: str,
              private: bool) -> None:
    """Make a group private or open. Admins only."""
    found, _ = _as_admin(session, user_id, team)
    target = _group(session, found, group)
    was, target.private = target.private, bool(private)
    logger.info(f"Group privacy set. Team: '{found.name}' ({found.team_id}). "
                f"Group: '{target.path}'. Private: '{was}' to '{target.private}'. "
                f"By: '{user_id}'.")


def rename_group(session: Session, user_id: uuid.UUID, team: str, group: str,
                 name: str) -> str:
    """Give a group a new name in the same place. The groups under it follow, and its
    skills, members and subscriptions stay with it. Admins only. Returns the new path."""
    found, _ = _as_admin(session, user_id, team)
    target = _group(session, found, group)
    name = _validated(name, "group name", GROUP_NAME_MAX_LENGTH)
    parent, _, _ = target.path.rpartition("/")
    new_path = f"{parent}/{name}" if parent else name
    moving = [row for row in _all_groups(session, found)
              if row.path == target.path or row.path.startswith(f"{target.path}/")]
    longest = max(len(new_path) + len(row.path) - len(target.path) for row in moving)
    if longest > GROUP_PATH_MAX_LENGTH:
        raise ValidationError(f"With that name a group under '{target.path}' would have a "
                              f"path longer than {GROUP_PATH_MAX_LENGTH} characters.")
    old_path = target.path
    try:
        # A savepoint, so a taken name is a sentence and the caller's transaction survives.
        with session.begin_nested():
            for row in moving:
                row.path = new_path + row.path[len(old_path):]
            session.flush()
    except IntegrityError as error:
        raise Conflict(f"Team '{found.name}' already has a group '{new_path}'.") from error
    logger.info(f"Group renamed. Team: '{found.name}' ({found.team_id}). "
                f"Group: '{old_path}' to '{new_path}' ({target.group_id}). "
                f"By: '{user_id}'.")
    return new_path


def delete_group(session: Session, user_id: uuid.UUID, team: str, group: str) -> None:
    """Delete an empty group. Admins only.

    One that still holds a skill or a group is refused: moving a private group's skills up
    would show them to people it kept them from, and deleting them is a separate choice.
    """
    found, _ = _as_admin(session, user_id, team)
    target = _group(session, found, group)
    if any(row.path.startswith(f"{target.path}/") for row in _all_groups(session, found)):
        raise Conflict(f"Group '{target.path}' has groups inside it. Delete or rename those "
                       "first.")
    if session.scalar(select(Skill.skill_id).where(Skill.group_id == target.group_id)
                      .limit(1)) is not None:
        raise Conflict(f"Group '{target.path}' still has skills. Move them to another group "
                       "or remove them from the team first.")
    # Its members and subscriptions go with it, by cascade.
    session.execute(delete(TeamGroup).where(TeamGroup.group_id == target.group_id))
    session.expunge(target)
    logger.info(f"Group deleted. Team: '{found.name}' ({found.team_id}). "
                f"Group: '{target.path}' ({target.group_id}). "
                f"By: '{user_id}'.")


def _all_groups(session: Session, team: Team) -> list[TeamGroup]:
    return list(session.scalars(select(TeamGroup).where(TeamGroup.team_id == team.team_id)))


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
    logger.info(f"Group member {'added' if member else 'removed'}. "
                f"Team: '{found.name}' ({found.team_id}). Group: '{target.path}'. "
                f"Member: '{their.user_id}'. By: '{user_id}'.")


def move_skill(session: Session, user_id: uuid.UUID, team: str, name: str,
               group: str | None) -> None:
    """Put a team skill in a group, or back at team level. Admins only.

    Nothing on any computer changes: where a skill sits decides who sees it in the team.
    """
    found, _ = _as_admin(session, user_id, team)
    skill = _skill(session, found, name, user_id)
    skill.group_id = None if group is None else _group(session, found, group).group_id
    logger.info(f"Team skill moved. Team: '{found.name}' ({found.team_id}). "
                f"Skill: '{skill.name}'. Group: '{group or 'team level'}'. By: '{user_id}'.")


def remove_skill(session: Session, user_id: uuid.UUID, team: str, name: str) -> None:
    """Take a skill out of a team. Admins only.

    Copies people already took stay in their own skills: a machine never ran the team's copy.
    """
    found, _ = _as_admin(session, user_id, team)
    skill = _skill(session, found, name, user_id)
    _delete_skills(session, select(Skill.skill_id).where(Skill.skill_id == skill.skill_id))
    logger.info(f"Team skill removed. Team: '{found.name}' ({found.team_id}). "
                f"Skill: '{skill.name}'. "
                f"By: '{user_id}'.")


def lock(session: Session, user_id: uuid.UUID, team: str,
         shared: bool = False) -> tuple[Team, TeamMember]:
    """The named team and the caller's place in it, read again once the team is locked.

    `shared` lets other readers that lock it through: taking a team's skill changes nothing
    in the team, but must not interleave with a change to it.
    """
    found, _ = visibility.membership(session, user_id, team)
    _lock_team(session, found.team_id, shared=shared)
    return visibility.membership(session, user_id, team)


def _lock_team(session: Session, team_id: uuid.UUID, shared: bool = False) -> Team:
    # SQLite renders no FOR UPDATE: its BEGIN IMMEDIATE already holds the one write lock.
    return session.scalar(select(Team).where(Team.team_id == team_id)
                          .with_for_update(read=shared)
                          .execution_options(populate_existing=True))


def _as_inviter(session: Session, user_id: uuid.UUID, team: str,
                locked: bool = True) -> tuple[Team, TeamMember]:
    found, me = (lock if locked else visibility.membership)(session, user_id, team)
    if me.role is not TeamRole.ADMIN and not me.can_invite:
        raise ValidationError(f"Only an admin of team '{found.name}', or a member an admin "
                              "lets invite, can do that. Ask one of its admins.")
    return found, me


def _as_admin(session: Session, user_id: uuid.UUID, team: str) -> tuple[Team, TeamMember]:
    found, me = lock(session, user_id, team)
    if me.role is not TeamRole.ADMIN:
        raise ValidationError(f"Only an admin of team '{found.name}' can do that. Ask one "
                              "of its admins.")
    return found, me


def _member(session: Session, team: Team, username: str) -> TeamMember:
    found = session.scalar(
        select(TeamMember)
        .join(User, User.user_id == TeamMember.user_id)
        .where(TeamMember.team_id == team.team_id, User.username == username)
        .execution_options(populate_existing=True)
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


def _skill(session: Session, team: Team, name: str, user_id: uuid.UUID) -> Skill:
    """A team skill the caller may see. An admin outside a private group may not either."""
    found = session.scalar(select(Skill).where(Skill.team_id == team.team_id,
                                               Skill.name == name))
    if found is None or not visibility.can_see_team_skill(session, user_id, found.skill_id):
        raise NotFound(f"Team '{team.name}' has no skill named '{loggable(name)}'.")
    return found


def _keep_an_admin(session: Session, team: Team, member: TeamMember, leaving: bool) -> None:
    """Refuse the change that would leave a team with nobody able to manage it."""
    if member.role is not TeamRole.ADMIN or not leaving:
        return
    admins = session.scalar(
        select(func.count()).select_from(TeamMember)
        .where(TeamMember.team_id == team.team_id, TeamMember.role == TeamRole.ADMIN))
    if admins > 1:
        return
    if _members_besides(session, team, member.user_id) == 0:
        raise Conflict(f"You are the only member of team '{team.name}'. Leave it or delete "
                       "it instead; either removes the team.")
    raise Conflict(f"That would leave team '{team.name}' with no admin. Make someone "
                   "else an admin first.")


def _members_besides(session: Session, team: Team, user_id: uuid.UUID) -> int:
    return session.scalar(select(func.count()).select_from(TeamMember).where(
        TeamMember.team_id == team.team_id, TeamMember.user_id != user_id))


def _delete_team(session: Session, team: Team) -> None:
    """The team's skills, then the team; its members, groups and invites go with it.

    A member's own copy of a team skill points at it with ON DELETE SET NULL, so it stays.
    """
    _delete_skills(session, select(Skill.skill_id).where(Skill.team_id == team.team_id))
    session.execute(delete(Team).where(Team.team_id == team.team_id))
    session.expunge(team)


def _delete_skills(session: Session, skill_ids) -> None:
    versions = select(SkillVersion.skill_version_id).where(SkillVersion.skill_id.in_(skill_ids))
    session.execute(delete(SkillFile).where(SkillFile.skill_version_id.in_(versions)))
    session.execute(delete(SkillVersion).where(SkillVersion.skill_id.in_(skill_ids)))
    session.execute(delete(Skill).where(Skill.skill_id.in_(skill_ids)))


def _drop_member(session: Session, team_id: uuid.UUID, user_id: uuid.UUID) -> None:
    _cancel_invites_by(session, team_id, user_id)
    # The membership first: a group can only be given to a member, so once this row is gone
    # nothing can add the person to one of the team's groups again.
    session.execute(delete(TeamMember).where(TeamMember.team_id == team_id,
                                             TeamMember.user_id == user_id))
    in_team = select(TeamGroup.group_id).where(TeamGroup.team_id == team_id)
    session.execute(delete(GroupMember).where(GroupMember.user_id == user_id,
                                              GroupMember.group_id.in_(in_team)))
    # Mutes go with the membership: someone who comes back starts hearing everything (DB-13).
    session.execute(delete(GroupUnsubscribed).where(GroupUnsubscribed.user_id == user_id,
                                                    GroupUnsubscribed.group_id.in_(in_team)))


def _cancel_invites_by(session: Session, team_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """Cancel the pending invites a person made into a team. Admins then see them Cancelled."""
    session.execute(
        update(Invite)
        .where(Invite.team_id == team_id, Invite.created_by == user_id,
               Invite.used_on.is_(None), Invite.cancelled_on.is_(None))
        .values(cancelled_on=utc_now())
        .execution_options(synchronize_session=False))


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
