"""What the dashboard shows one user, assembled in one place (ADR-0017).

Everything here is read through `visibility` and `team_service`, so the page is sent exactly
what its user may see and never has to hide anything itself.
"""

import hmac
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from aistack.commons.exceptions import NotFound, SignedOut
from aistack.commons.text import loggable
from aistack.db.models.harness import Harness
from aistack.db.models.machine import Machine
from aistack.db.models.machine_harness import MachineHarness
from aistack.db.models.machine_skill import MachineSkill
from aistack.db.models.skill import Skill
from aistack.db.models.skill_file import SkillFile
from aistack.db.models.skill_version import SkillVersion
from aistack.db.models.team import Team, TeamMember, TeamRole
from aistack.db.models.timestamps import as_utc
from aistack.db.models.user import User
from aistack.db.ordering import bytewise
from aistack.services import skill_service, team_service, visibility
from aistack.services.harnesses import DEFAULT_HARNESS, validated_harness
from aistack.services.transfer_ticket import DashboardHolder, token_prefix


def state(session: Session, user_id: uuid.UUID) -> dict[str, Any]:
    """The user, their computers, their own skills, and each of their teams."""
    team_skills = _team_skills(session, user_id)
    by_id = {skill["id"]: skill for skills in team_skills.values() for skill in skills}
    mine = _my_skills(session, user_id, by_id)
    taken = {skill["source_id"] for skill in mine if skill["source_id"] is not None}

    teams = []
    for team in team_service.list_teams(session, user_id):
        me = session.scalar(
            select(TeamMember)
            .join(Team, Team.team_id == TeamMember.team_id)
            .where(Team.name == team.name, TeamMember.user_id == user_id))
        teams.append({
            "name": team.name,
            "kind": team.kind.value,
            "role": team.role.value,
            "sees_all_groups": me.sees_all_groups,
            "can_invite": me.can_invite,
            "members": [
                {"username": member.username, "full_name": member.full_name,
                 "role": member.role.value,
                 "sees_all_groups": member.sees_all_groups, "can_invite": member.can_invite,
                 "groups": list(member.groups)}
                for member in team_service.members(session, user_id, team.name)
            ],
            "groups": [
                {"path": group.path, "private": group.private, "member": group.member,
                 "subscribed": group.subscribed}
                for group in team_service.groups(session, user_id, team.name)
            ],
            "skills": [
                {key: value for key, value in skill.items() if key != "id"}
                | {"in_library": skill["id"] in taken}
                for skill in team_skills.get(team.name, [])
            ],
            # Every invite to an admin, their own to an inviter, none to anyone else.
            "invites": [
                {"id": invite.invite_id, "created_by": invite.created_by,
                 "created_on": invite.created_on.isoformat(),
                 "expires_on": invite.expires_on.isoformat(), "status": invite.status,
                 "used_by": invite.used_by}
                for invite in team_service.invites(session, user_id, team.name)
            ] if team.role is TeamRole.ADMIN or me.can_invite else [],
        })

    return {
        "user": dict(session.execute(
            select(User.username, User.full_name).where(User.user_id == user_id)).one()._mapping),
        "machines": _machines(session, user_id),
        "skills": [{key: value for key, value in skill.items() if key != "source_id"}
                   for skill in mine],
        "teams": teams,
    }


def username(session: Session, user_id: uuid.UUID) -> str:
    return session.scalar(select(User.username).where(User.user_id == user_id))


def require_its_machine(session: Session, holder: DashboardHolder) -> None:
    """A session is only as good as the computer that opened it (ADR-0027).

    Removing that computer, or giving it a new token after it was lost, ends every session it
    opened, while the person's other computers keep theirs. An operator takes someone off a
    server by deleting their machines (docs/OPERATING.md), which ends all of them.
    """
    token_hash = session.scalar(select(Machine.token_hash).where(
        Machine.machine_id == holder.machine_id, Machine.user_id == holder.user_id))
    if token_hash is None or not hmac.compare_digest(token_prefix(token_hash),
                                                     holder.token_prefix):
        raise SignedOut("The computer that opened this dashboard is no longer connected to "
                        "this server, so the dashboard is closed to it. Ask your coding agent "
                        "on a computer that is connected to \"open my aistack dashboard\".")


@dataclass(frozen=True)
class Placed:
    name: str
    machine_id: uuid.UUID
    harness: str
    enabled: bool


def set_on_machine(session: Session, user_id: uuid.UUID, name: str, machine_id: str,
                   enabled: bool, harness: str | None = None) -> Placed:
    """Switch one of the user's own skills on or off in one harness of one of their computers.

    The decision is recorded; the files move the next time that harness syncs there.
    """
    harness = validated_harness(harness)
    skill = visibility.required_my_skill(session, user_id, name)
    try:
        machine = session.get(Machine, uuid.UUID(machine_id))
    except (ValueError, TypeError, AttributeError):
        machine = None
    # Somebody else's computer is answered like one that does not exist.
    if machine is None or machine.user_id != user_id:
        raise NotFound(f"You have no computer '{loggable(str(machine_id))}'.")
    skill_service.set_enabled(session, machine.machine_id, harness, skill.skill_id,
                              enabled=bool(enabled))
    return Placed(skill.name, machine.machine_id, harness.value, bool(enabled))


def _machines(session: Session, user_id: uuid.UUID) -> list[dict[str, Any]]:
    """The user's computers, oldest first, each with its harnesses: those that have synced
    there and those holding a decision about a skill.

    A computer with neither has not synced since harnesses existed, and is shown with Claude
    Code, the only harness there was before.
    """
    known: dict[uuid.UUID, set[Harness]] = {}
    for table in (MachineHarness, MachineSkill):
        for machine_id, harness in session.execute(
                select(table.machine_id, table.harness).distinct()
                .join(Machine, Machine.machine_id == table.machine_id)
                .where(Machine.user_id == user_id)).all():
            known.setdefault(machine_id, set()).add(harness)
    return [
        {"id": str(machine_id), "name": name, "os": os.value,
         "harnesses": [harness.value for harness in Harness
                       if harness in known.get(machine_id, {DEFAULT_HARNESS})]}
        for machine_id, name, os in session.execute(
            select(Machine.machine_id, Machine.name, Machine.os)
            .where(Machine.user_id == user_id).order_by(Machine.created_on)).all()
    ]


def _newest() -> Any:
    """Each skill's latest revision, with who pushed it and when."""
    latest = (
        select(SkillVersion.skill_id, func.max(SkillVersion.revision).label("revision"))
        .group_by(SkillVersion.skill_id).subquery()
    )
    files = (
        select(SkillFile.skill_version_id, func.count().label("files"))
        .group_by(SkillFile.skill_version_id).subquery()
    )
    return (
        select(SkillVersion.skill_id, SkillVersion.revision, User.username.label("pushed_by"),
               SkillVersion.created_on, files.c.files)
        .join(latest, (latest.c.skill_id == SkillVersion.skill_id)
              & (latest.c.revision == SkillVersion.revision))
        .join(User, User.user_id == SkillVersion.pushed_by)
        .join(files, files.c.skill_version_id == SkillVersion.skill_version_id)
        .subquery()
    )


def _team_skills(session: Session, user_id: uuid.UUID) -> dict[str, list[dict[str, Any]]]:
    """Every team skill the user may see, by team, each with its latest revision."""
    visible = visibility.team_skills(session, user_id).subquery()
    newest = _newest()
    rows = session.execute(
        select(visible.c.skill_id, visible.c.name, visible.c.description, visible.c.team,
               visible.c.group, newest.c.revision, newest.c.pushed_by, newest.c.created_on)
        .join(newest, newest.c.skill_id == visible.c.skill_id)
        .order_by(bytewise(visible.c.team), bytewise(visible.c.group), bytewise(visible.c.name))
    ).all()
    by_team: dict[str, list[dict[str, Any]]] = {}
    for skill_id, name, description, team, group, revision, pushed_by, pushed_on in rows:
        by_team.setdefault(team, []).append({
            "id": skill_id, "name": name, "description": description, "team": team,
            "group": group, "revision": revision, "pushed_by": pushed_by,
            "updated_on": as_utc(pushed_on).isoformat(),
        })
    return by_team


def _my_skills(session: Session, user_id: uuid.UUID,
               team_skills: dict[uuid.UUID, dict[str, Any]]) -> list[dict[str, Any]]:
    mine = visibility.my_skills(user_id).where(Skill.archived.is_(False)).subquery()
    newest = _newest()
    rows = session.execute(
        select(mine.c.skill_id, mine.c.name, mine.c.description, mine.c.source_skill_id,
               mine.c.source_revision, newest.c.revision, newest.c.pushed_by,
               newest.c.created_on, newest.c.files)
        .join(newest, newest.c.skill_id == mine.c.skill_id)
        .order_by(bytewise(mine.c.name))
    ).all()
    placements: dict[uuid.UUID, list[dict[str, str]]] = {}
    for skill_id, machine_id, harness in session.execute(
            select(MachineSkill.skill_id, MachineSkill.machine_id, MachineSkill.harness)
            .join(Machine, Machine.machine_id == MachineSkill.machine_id)
            .where(Machine.user_id == user_id, MachineSkill.enabled.is_(True))
            .order_by(Machine.created_on, Machine.machine_id, MachineSkill.harness)).all():
        placements.setdefault(skill_id, []).append({"machine": str(machine_id),
                                                    "harness": harness.value})

    skills = []
    for (skill_id, name, description, source_id, source_revision, revision, pushed_by,
         pushed_on, files) in rows:
        # A source the user can no longer see is no source: the copy is simply theirs.
        source = team_skills.get(source_id)
        skills.append({
            "name": name,
            "description": description,
            "revision": revision,
            "pushed_by": pushed_by,
            "updated_on": as_utc(pushed_on).isoformat(),
            "files": files,
            "placements": placements.get(skill_id, []),
            "source_id": None if source is None else source_id,
            "source": None if source is None else {
                "team": source["team"],
                "group": source["group"],
                "revision": source_revision,
                "latest_revision": source["revision"],
                "latest_pushed_by": source["pushed_by"],
                "update_available": source["revision"] > source_revision,
            },
        })
    return skills
