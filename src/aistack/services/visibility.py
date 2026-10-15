"""Who may see which skill (ADR-0015).

Two kinds of place hold skills. A user's personal team is the Library: private, the only
place their machines install from. Every other team holds what its members shared, and a
member sees a team skill when it sits at team level or in a group they may see; `group_access`
has that rule.

This is the only module that decides whether a user may reach a skill, a group, or a team.
Code elsewhere looks a skill up by team and name only after this module has established the
caller's place in that team. Anything the caller may not see is answered exactly like
something that does not exist: same exception, same sentence.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import Select, or_, select
from sqlalchemy.orm import Session

from aistack.commons.exceptions import NotFound
from aistack.commons.text import loggable
from aistack.db.models.skill import Skill
from aistack.db.models.team import (
    GroupMember,
    GroupUnsubscribed,
    Team,
    TeamGroup,
    TeamKind,
    TeamMember,
    TeamRole,
)
from aistack.services.skill_validation import validated_skill_name


def personal_team(session: Session, user_id: uuid.UUID) -> Team:
    return session.scalars(
        select(Team).where(Team.kind == TeamKind.PERSONAL, Team.created_by == user_id)).one()


def my_skills(user_id: uuid.UUID) -> Select[tuple[Skill]]:
    """What is in the user's personal team, removed ones included."""
    return (
        select(Skill)
        .join(Team, Team.team_id == Skill.team_id)
        .where(Team.kind == TeamKind.PERSONAL, Team.created_by == user_id)
    )


def my_skill(session: Session, user_id: uuid.UUID, name: str) -> Skill | None:
    return session.scalar(my_skills(user_id).where(Skill.name == name))


def required_my_skill(session: Session, user_id: uuid.UUID, name: str,
                      removed_too: bool = False) -> Skill:
    """One of the user's own skills. A removed one counts only where the caller is about to
    bring it back or finish removing it."""
    skill = my_skill(session, user_id, validated_skill_name(name))
    if skill is None or (skill.archived and not removed_too):
        # Only teams the caller sees, so naming them reveals nothing a listing would not.
        teams = sorted({row.team for row in session.execute(
            team_skills(session, user_id).where(Skill.name == name))})
        if teams:
            holders = (f"team '{teams[0]}' shares one" if len(teams) == 1 else
                       f"teams {', '.join(repr(team) for team in teams)} share one")
            raise NotFound(f"You have no skill named '{name}' of your own, but {holders}. "
                           f"To install it, call get_skill with team '{teams[0]}'.")
        raise NotFound(f"You have no skill named '{name}'. Call list_skills to see yours and "
                       "your teams'; to take one from a team, call get_skill with its team.")
    return skill


@dataclass(frozen=True)
class GroupAccess:
    """What one user may do with the groups of the teams they are in."""

    # Groups whose skills they may see.
    visible: frozenset[uuid.UUID]
    # Groups they may share a skill into: visible, and they belong to it or to one above it.
    writable: frozenset[uuid.UUID]
    # Groups they have unsubscribed from, and every group under those.
    unsubscribed: frozenset[uuid.UUID]
    # Groups they were added to directly.
    member: frozenset[uuid.UUID]


def group_access(session: Session, user_id: uuid.UUID) -> GroupAccess:
    """Work out the user's groups once, top of each tree first.

    Groups nest, so whether one is visible depends on the ones above it:

    - a private group is seen by the people added to it, and by nobody else;
    - an open group is seen by everyone who sees the group above it, or by the whole team
      when nothing is above it;
    - a member an admin gave sight of every group sees them all.

    A team has a handful of groups, so this is read in two queries and decided here, where
    the rule can be read, instead of in a recursive query on two databases.
    """
    groups = session.execute(
        select(TeamGroup.group_id, TeamGroup.team_id, TeamGroup.path, TeamGroup.private,
               TeamMember.sees_all_groups)
        .join(TeamMember, TeamMember.team_id == TeamGroup.team_id)
        .where(TeamMember.user_id == user_id)
    ).all()
    member = frozenset(session.scalars(
        select(GroupMember.group_id).where(GroupMember.user_id == user_id)))
    turned_off = set(session.scalars(
        select(GroupUnsubscribed.group_id).where(GroupUnsubscribed.user_id == user_id)))

    by_path = {(team_id, path): group_id for group_id, team_id, path, _, _ in groups}
    visible: set[uuid.UUID] = set()
    belongs: set[uuid.UUID] = set()
    unsubscribed: set[uuid.UUID] = set()
    # Shorter paths first, so a group is decided after the one above it.
    for group_id, team_id, path, private, sees_all in sorted(
            groups, key=lambda group: group.path.count("/")):
        above = by_path.get((team_id, path.rpartition("/")[0]))
        if group_id in member or above in belongs:
            belongs.add(group_id)
        if sees_all or (group_id in member if private else above is None or above in visible):
            visible.add(group_id)
        if group_id in turned_off or above in unsubscribed:
            unsubscribed.add(group_id)
    return GroupAccess(visible=frozenset(visible), writable=frozenset(visible & belongs),
                       unsubscribed=frozenset(unsubscribed), member=member)


def may_share_over(access: GroupAccess, skill: Skill) -> bool:
    """Whether a member may share over an existing team skill (ADR-0029).

    At team level any member may. In a group it takes what sharing a new skill into that
    group takes: seeing a group is reading and taking it, not writing to it.
    """
    return skill.group_id is None or skill.group_id in access.writable


def shows_membership(access: GroupAccess, viewer: TeamMember, group_id: uuid.UUID,
                     private: bool) -> bool:
    """Whether the team's member list shows the viewer that someone is in this group.

    An admin sees every membership, to manage them. Anyone else sees a group they can see,
    and a private one only from inside it: an open group under a private one would
    otherwise name the private one in its path.
    """
    if viewer.role is TeamRole.ADMIN:
        return True
    return group_id in access.visible and (not private or group_id in access.member)


def team_skills(session: Session, user_id: uuid.UUID) -> Select[tuple[Skill, str, str | None]]:
    """Every team skill `user_id` may see, with its team's name and its group's path, if any."""
    return (
        select(Skill, Team.name.label("team"), TeamGroup.path.label("group"))
        .join(Team, Team.team_id == Skill.team_id)
        .join(TeamMember, TeamMember.team_id == Team.team_id)
        .outerjoin(TeamGroup, TeamGroup.group_id == Skill.group_id)
        .where(
            TeamMember.user_id == user_id,
            Team.kind != TeamKind.PERSONAL,
            or_(Skill.group_id.is_(None),
                Skill.group_id.in_(group_access(session, user_id).visible)),
        )
    )


def team_skill(session: Session, user_id: uuid.UUID, name: str, team: str) -> Skill:
    """The skill called `name` in `team`, if the user may see it."""
    name = validated_skill_name(name)
    found = session.execute(
        team_skills(session, user_id).where(Skill.name == name, Team.name == team)).first()
    if found is None:
        raise NotFound(f"Team '{loggable(team)}' has no skill named '{name}' that you can "
                       "reach. Call list_skills to see what your teams hold; names are exact.")
    return found[0]


def can_see_team_skill(session: Session, user_id: uuid.UUID, skill_id: uuid.UUID) -> bool:
    return session.execute(
        team_skills(session, user_id).where(Skill.skill_id == skill_id)).first() is not None


def membership(session: Session, user_id: uuid.UUID, team: str) -> tuple[Team, TeamMember]:
    """The named team and the caller's place in it.

    A team the caller is not in is answered like one that does not exist. A personal team is
    nobody's to name: it is reached as the Library, never as a team.
    """
    found = session.execute(
        select(Team, TeamMember)
        .join(TeamMember, TeamMember.team_id == Team.team_id)
        .where(Team.name == team, Team.kind != TeamKind.PERSONAL,
               TeamMember.user_id == user_id)
        # Read as committed, not as this session last saw it: `team_service.lock` reads it
        # again after waiting for another change to the team.
        .execution_options(populate_existing=True)
    ).first()
    if found is None:
        raise NotFound(f"You are not in a team named '{loggable(team)}'. Call list_teams to "
                       "see the teams you are in.")
    return found[0], found[1]


def is_my_skill(session: Session, user_id: uuid.UUID, skill_id: uuid.UUID) -> bool:
    return session.scalar(my_skills(user_id).where(Skill.skill_id == skill_id)) is not None
