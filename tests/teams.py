"""Helpers for tests that need a second person to see a skill.

A push lands in the pusher's own skills, which nobody else sees. Tests written for one shared
vault keep their meaning by sharing with the server's team, which every user is in.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from aistack.db.models.machine import Machine
from aistack.services import skill_service, team_service, visibility

SERVER_TEAM = "everyone"


def user_of(session: Session, machine_id: uuid.UUID) -> uuid.UUID:
    return session.get(Machine, machine_id).user_id


def share_with_everyone(session: Session, user_id: uuid.UUID, name: str) -> None:
    skill_service.share(session, user_id, name, SERVER_TEAM)


def enable(session: Session, machine_id: uuid.UUID, name: str):
    """Install `name` on a machine: the user's own if they have it, else the server team's."""
    user_id = user_of(session, machine_id)
    own = visibility.my_skill(session, user_id, name)
    team = None if own is not None and not own.archived else SERVER_TEAM
    return skill_service.get_skill(session, machine_id, user_id, name, team)


def make_team(session: Session, name: str, admin: uuid.UUID, *members: uuid.UUID) -> None:
    """A team created by `admin`, with `members` joined through its invite code."""
    team_service.create_team(session, admin, name)
    code = team_service.new_invite_code(session, admin, name)
    for member in members:
        team_service.join_team(session, member, code)


def machines_of_one_user(session: Session, count: int, username: str = "pusher") -> list:
    """`count` machines of one user. Only they can push to the same skill at once: a push
    lands in the pusher's own skills, so different users never contend for a revision."""
    from types import SimpleNamespace

    from aistack.services import onboarding_service

    first = onboarding_service.join(session, username, "box-0", "LINUX")
    others = [onboarding_service.add_machine(session, first.user.user_id, f"box-{index}",
                                             "LINUX")
              for index in range(1, count)]
    return [SimpleNamespace(user=first.user, machine=joined.machine)
            for joined in (first, *others)]
