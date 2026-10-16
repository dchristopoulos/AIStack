"""What the dashboard shows one user, assembled in one place (ADR-0017).

Everything here is read through `visibility` and `team_service`, so the page is sent exactly
what its user may see and never has to hide anything itself.
"""

import difflib
import hmac
import logging
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from aistack.commons.exceptions import SignedOut
from aistack.db.models.harness import Harness
from aistack.db.models.machine import Machine
from aistack.db.models.machine_harness import MachineHarness
from aistack.db.models.machine_project import MachineProject
from aistack.db.models.machine_project_skill import MachineProjectSkill
from aistack.db.models.machine_skill import MachineSkill
from aistack.db.models.project import Project
from aistack.db.models.skill import Skill
from aistack.db.models.skill_file import SkillFile
from aistack.db.models.skill_version import SkillVersion
from aistack.db.models.timestamps import as_utc
from aistack.db.models.user import User
from aistack.db.models.value_set import known
from aistack.db.ordering import bytewise
from aistack.services import (
    onboarding_service,
    project_service,
    projects,
    revisions,
    skill_service,
    team_service,
    visibility,
)
from aistack.services.harnesses import validated_harness
from aistack.services.transfer_ticket import DashboardHolder, token_prefix

logger = logging.getLogger(__name__)


def state(session: Session, user_id: uuid.UUID) -> dict[str, Any]:
    """The user, their computers, their own skills, and each of their teams.

    Read in the same few statements however many skills, teams and members there are: the
    page asks on every load, and on SQLite this holds the write lock while it reads.
    """
    access = visibility.group_access(session, user_id)
    team_skills = _team_skills(session, user_id, access)
    by_id = {skill["id"]: skill for skills in team_skills.values() for skill in skills}
    mine = _my_skills(session, user_id, by_id)
    taken = {skill["source_id"] for skill in mine if skill["source_id"] is not None}

    teams = []
    for team in team_service.overview(session, user_id, access):
        teams.append({
            "name": team.summary.name,
            "kind": team.summary.kind.value,
            "role": team.summary.role.value,
            "sees_all_groups": team.sees_all_groups,
            "can_invite": team.can_invite,
            "members": [
                {"username": member.username, "full_name": member.full_name,
                 "role": member.role.value,
                 "sees_all_groups": member.sees_all_groups, "can_invite": member.can_invite,
                 "groups": list(member.groups)}
                for member in team.members
            ],
            "groups": [
                {"path": group.path, "private": group.private, "member": group.member,
                 "subscribed": group.subscribed}
                for group in team.groups
            ],
            "skills": [
                {key: value for key, value in skill.items() if key not in ("id", "muted")}
                | {"in_library": skill["id"] in taken}
                for skill in team_skills.get(team.summary.name, [])
            ],
            # Every recent invite to an admin, their own to an inviter, none to anyone else.
            "invites": [
                {"id": invite.invite_id, "created_by": invite.created_by,
                 "created_on": invite.created_on.isoformat(),
                 "expires_on": invite.expires_on.isoformat(), "status": invite.status,
                 "used_by": invite.used_by}
                for invite in team.invites
            ],
        })

    return {
        "user": dict(session.execute(
            select(User.username, User.full_name).where(User.user_id == user_id)).one()._mapping),
        "machines": _machines(session, user_id),
        "skills": [{key: value for key, value in skill.items() if key != "source_id"}
                   for skill in mine],
        # Removed from the Library, by name: what Bring back can return (PH-11).
        "removed": list(session.scalars(
            visibility.my_skills(user_id).with_only_columns(Skill.name)
            .where(Skill.archived.is_(True)).order_by(bytewise(Skill.name)))),
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
                   enabled: bool, harness: str | None = None,
                   project: str | None = None) -> Placed:
    """Switch one of the user's own skills on or off in one harness of one of their computers,
    or in a project folder that computer manages (ADR-0026).

    The decision is recorded; the files move the next time that folder syncs there.
    """
    harness = validated_harness(harness)
    skill = visibility.required_my_skill(session, user_id, name)
    machine = onboarding_service.own_machine(session, user_id, machine_id)
    if project is None:
        skill_service.set_enabled(session, machine.machine_id, harness, skill.skill_id,
                                  enabled=bool(enabled))
    else:
        folder = project_service.required_folder(session, user_id, machine.machine_id,
                                                 projects.validated_key(project), harness)
        project_service.set_enabled(session, folder, skill.skill_id, enabled=bool(enabled))
    logger.info(f"Skill {'placed' if enabled else 'taken off'} on the dashboard. "
                f"Skill: '{skill.name}'. Machine: '{machine.machine_id}'. "
                f"Harness: '{harness.value}'. In a project: '{project is not None}'. "
                f"User: '{user_id}'.")
    return Placed(skill.name, machine.machine_id, harness.value, bool(enabled))


def history(session: Session, user_id: uuid.UUID, name: str) -> dict[str, Any]:
    """Every revision of one of the user's own skills, newest first: what Restore can bring
    back (PH-08)."""
    skill = visibility.required_my_skill(session, user_id, name)
    rows = session.execute(
        select(SkillVersion.revision, User.username, SkillVersion.created_on,
               revisions.file_count(SkillVersion.skill_version_id))
        .join(User, User.user_id == SkillVersion.pushed_by)
        .where(SkillVersion.skill_id == skill.skill_id)
        .order_by(SkillVersion.revision.desc())).all()
    return {"revisions": [{"revision": revision, "pushed_by": pushed_by,
                           "pushed_on": as_utc(pushed_on).isoformat(), "files": files}
                          for revision, pushed_by, pushed_on, files in rows]}


# A diff longer than this is cut, and says so: a page shows it, and nobody reads further.
_DIFF_MAX_CHARACTERS = 200_000


def update_changes(session: Session, user_id: uuid.UUID, team: str,
                   name: str) -> dict[str, Any]:
    """What taking a team's latest revision would change in the user's own copy, file by
    file, as unified diffs (IMP-08). It shows only what the user may already take."""
    # The team's first, so a skill the caller cannot reach is refused like an unknown one.
    source = visibility.team_skill(session, user_id, name, team)
    mine = visibility.required_my_skill(session, user_id, source.name)
    theirs, yours = _newest_version(session, source), _newest_version(session, mine)
    before, after = _files_of(session, yours), _files_of(session, theirs)
    files, left, truncated = [], _DIFF_MAX_CHARACTERS, False
    for path in sorted(before.keys() | after.keys()):
        if before.get(path) == after.get(path):
            continue
        diff = "".join(difflib.unified_diff(
            _lines(before.get(path, "")), _lines(after.get(path, "")),
            f"yours r{yours.revision}/{path}", f"{team} r{theirs.revision}/{path}"))
        truncated = truncated or len(diff) > left
        files.append({"path": path,
                      "change": ("added" if path not in before
                                 else "removed" if path not in after else "changed"),
                      "diff": diff[:max(left, 0)]})
        left -= len(diff)
    return {"from_revision": yours.revision, "to_revision": theirs.revision,
            "pushed_by": username(session, theirs.pushed_by), "files": files,
            "truncated": truncated}


def _lines(text: str) -> list[str]:
    # A last line without a newline would run into the diff's next line.
    return [line if line.endswith("\n") else line + "\n" for line in text.splitlines(True)]


def _newest_version(session: Session, skill: Skill) -> SkillVersion:
    return session.scalar(select(SkillVersion).where(SkillVersion.skill_id == skill.skill_id)
                          .order_by(SkillVersion.revision.desc()).limit(1))


def _files_of(session: Session, version: SkillVersion) -> dict[str, str]:
    return dict(session.execute(
        select(SkillFile.path, SkillFile.content)
        .where(SkillFile.skill_version_id == version.skill_version_id)).all())


def add_project(session: Session, user_id: uuid.UUID, machine_id: str, project: str,
                harness: str | None) -> None:
    """Start managing one of the user's projects on one of their computers. Its path stays
    unknown until that folder syncs there."""
    machine = onboarding_service.own_machine(session, user_id, machine_id)
    project_service.add_folder(session, user_id, machine.machine_id,
                               projects.validated_key(project), validated_harness(harness))
    logger.info(f"Project folder added. Machine: '{machine.machine_id}'. User: '{user_id}'.")


def remove_project(session: Session, user_id: uuid.UUID, machine_id: str, project: str,
                   harness: str | None) -> int:
    """Stop managing a project on one computer, in one harness or in all. The Library, the
    files on disk and the other computers are untouched."""
    machine = onboarding_service.own_machine(session, user_id, machine_id)
    removed = project_service.remove_folder(
        session, user_id, machine.machine_id, projects.validated_key(project),
        None if harness is None else validated_harness(harness))
    logger.info(f"Project folders removed. Count: '{removed}'. Machine: '{machine.machine_id}'. "
                f"User: '{user_id}'.")
    return removed


def _machines(session: Session, user_id: uuid.UUID) -> list[dict[str, Any]]:
    """The user's computers, oldest first, each with its harnesses: those that have synced
    there and those holding a decision about a skill.

    A computer with neither has never synced, and is shown with none, so nothing is placed in a
    folder no agent there syncs (UX-07). Each says when it was added and from which
    computer, and when each harness last synced, so a computer nobody recognises, or one that
    stopped syncing, stands out (ADR-0027).
    """
    harnesses_of: dict[uuid.UUID, set[Harness]] = {}
    # A harness used only in a project folder is still one of the computer's agents.
    for table in (MachineHarness, MachineSkill, MachineProject):
        for machine_id, harness in session.execute(
                select(table.machine_id, table.harness).distinct()
                .join(Machine, Machine.machine_id == table.machine_id)
                .where(Machine.user_id == user_id, known(table.harness))).all():
            harnesses_of.setdefault(machine_id, set()).add(harness)
    synced: dict[tuple[uuid.UUID, Harness], str | None] = {
        (machine_id, harness): None if at is None else as_utc(at).isoformat()
        for machine_id, harness, at in session.execute(
            select(MachineHarness.machine_id, MachineHarness.harness,
                   MachineHarness.last_synced_on)
            .join(Machine, Machine.machine_id == MachineHarness.machine_id)
            .where(Machine.user_id == user_id, known(MachineHarness.harness))).all()
    }
    names = dict(session.execute(
        select(Machine.machine_id, Machine.name).where(Machine.user_id == user_id)).all())
    projects_of: dict[uuid.UUID, dict[str, dict[str, Any]]] = {}
    for machine_id, key, name, harness, path, at in session.execute(
            select(MachineProject.machine_id, Project.key, Project.name, MachineProject.harness,
                   MachineProject.path, MachineProject.last_synced_on)
            .join(Project, Project.project_id == MachineProject.project_id)
            .where(Project.user_id == user_id, known(MachineProject.harness))
            .order_by(bytewise(Project.name), bytewise(Project.key),
                      MachineProject.harness)).all():
        shown_project = projects_of.setdefault(machine_id, {}).setdefault(
            key, {"key": key, "name": name, "folders": []})
        shown_project["folders"].append({
            "harness": harness.value, "path": path,
            "last_synced_on": None if at is None else as_utc(at).isoformat()})
    shown = []
    for machine_id, name, os, created_on, added_by in session.execute(
            select(Machine.machine_id, Machine.name, Machine.os, Machine.created_on,
                   Machine.added_by_machine_id)
            .where(Machine.user_id == user_id, known(Machine.os))
            .order_by(Machine.created_on)).all():
        harnesses = [harness for harness in Harness
                     if harness in harnesses_of.get(machine_id, set())]
        shown.append({
            "id": str(machine_id), "name": name, "os": os.value,
            "harnesses": [harness.value for harness in harnesses],
            "added_on": as_utc(created_on).isoformat(),
            # None for a first computer; "added_by_removed" for one added from a computer
            # that has since been removed.
            "added_by": names.get(added_by),
            "added_by_removed": added_by is not None and added_by not in names,
            "last_synced": {harness.value: synced.get((machine_id, harness))
                            for harness in harnesses},
            "projects": list(projects_of.get(machine_id, {}).values()),
        })
    return shown


def _newest(skill_ids: Any) -> Any:
    """The latest revision of each chosen skill, with who pushed it, when, and its files."""
    latest = revisions.latest(skill_ids)
    return (
        select(latest.c.skill_id, latest.c.revision, User.username.label("pushed_by"),
               latest.c.created_on,
               revisions.file_count(latest.c.skill_version_id).label("files"))
        .join(User, User.user_id == latest.c.pushed_by)
        .subquery()
    )


def _team_skills(session: Session, user_id: uuid.UUID,
                 access: visibility.GroupAccess) -> dict[str, list[dict[str, Any]]]:
    """Every team skill the user may see, by team, each with its latest revision."""
    visible = visibility.team_skills(session, user_id, access).subquery()
    newest = _newest(select(visible.c.skill_id))
    rows = session.execute(
        select(visible.c.skill_id, visible.c.name, visible.c.description, visible.c.team,
               visible.c.group, visible.c.group_id, newest.c.revision, newest.c.pushed_by,
               newest.c.created_on)
        .join(newest, newest.c.skill_id == visible.c.skill_id)
        # Team level first, then by group: PostgreSQL sorts a NULL group last and SQLite
        # first, and the page must read the same on both.
        .order_by(bytewise(visible.c.team), visible.c.group.is_not(None),
                  bytewise(visible.c.group), bytewise(visible.c.name))
    ).all()
    by_team: dict[str, list[dict[str, Any]]] = {}
    for (skill_id, name, description, team, group, group_id, revision, pushed_by,
         pushed_on) in rows:
        by_team.setdefault(team, []).append({
            "id": skill_id, "name": name, "description": description, "team": team,
            "group": group, "revision": revision, "pushed_by": pushed_by,
            "updated_on": as_utc(pushed_on).isoformat(),
            # In a group the user unsubscribed from: its updates are offered nowhere, as in
            # sync (IMP-02).
            "muted": group_id in access.unsubscribed,
        })
    return by_team


def _my_skills(session: Session, user_id: uuid.UUID,
               team_skills: dict[uuid.UUID, dict[str, Any]]) -> list[dict[str, Any]]:
    mine = visibility.my_skills(user_id).where(Skill.archived.is_(False)).subquery()
    newest = _newest(select(mine.c.skill_id))
    rows = session.execute(
        select(mine.c.skill_id, mine.c.name, mine.c.description, mine.c.source_skill_id,
               mine.c.source_revision, newest.c.revision, newest.c.pushed_by,
               newest.c.created_on, newest.c.files)
        .join(newest, newest.c.skill_id == mine.c.skill_id)
        .order_by(bytewise(mine.c.name))
    ).all()
    placements: dict[uuid.UUID, list[dict[str, Any]]] = {}
    for skill_id, machine_id, harness, installed in session.execute(
            select(MachineSkill.skill_id, MachineSkill.machine_id, MachineSkill.harness,
                   MachineSkill.revision)
            .join(Machine, Machine.machine_id == MachineSkill.machine_id)
            .where(Machine.user_id == user_id, MachineSkill.enabled.is_(True),
                   known(MachineSkill.harness))
            .order_by(Machine.created_on, Machine.machine_id, MachineSkill.harness)).all():
        # `revision` is what was last installed or pushed there; None until it syncs.
        placements.setdefault(skill_id, []).append({"machine": str(machine_id),
                                                    "harness": harness.value,
                                                    "revision": installed, "project": None})
    for skill_id, machine_id, harness, installed, key in session.execute(
            select(MachineProjectSkill.skill_id, MachineProject.machine_id,
                   MachineProject.harness, MachineProjectSkill.revision, Project.key)
            .join(MachineProject, MachineProject.machine_project_id
                  == MachineProjectSkill.machine_project_id)
            .join(Project, Project.project_id == MachineProject.project_id)
            .join(Machine, Machine.machine_id == MachineProject.machine_id)
            .where(Project.user_id == user_id, MachineProjectSkill.enabled.is_(True),
                   known(MachineProject.harness))
            .order_by(Machine.created_on, Machine.machine_id, bytewise(Project.key),
                      MachineProject.harness)).all():
        placements.setdefault(skill_id, []).append({"machine": str(machine_id),
                                                    "harness": harness.value,
                                                    "revision": installed, "project": key})

    copies = [(row.skill_id, row.source_skill_id, row.source_revision) for row in rows
              if row.source_skill_id in team_skills]
    changed = skill_service.changed_since_taken(session, copies)
    replaced = skill_service.replaced_since_taken(session, copies)
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
                "update_available": (source["revision"] > source_revision
                                     and not source["muted"]),
                # Taking the team's latest would replace the user's edits since they took it.
                "own_changes": skill_id in changed,
                # A share put a different skill of the same name over the one they took.
                "different_skill": skill_id in replaced,
            },
        })
    return skills
