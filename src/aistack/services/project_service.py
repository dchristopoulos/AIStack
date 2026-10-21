"""Project folders and the skills placed in them (ADR-0026).

A `machine_project` row is the opt-in: a computer manages a project's folder for one harness
once it exists, and every decision in that folder is a `machine_project_skill` row, as
`machine_skill` is for a global folder. Callers pass a key `projects.project_key` produced
and a path `projects.validated_here` checked; nothing here logs either.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from aistack.commons.exceptions import NotFound
from aistack.commons.text import loggable
from aistack.db.models.harness import Harness
from aistack.db.models.machine_project import MachineProject
from aistack.db.models.machine_project_skill import MachineProjectSkill
from aistack.db.models.project import Project
from aistack.db.models.skill import Skill
from aistack.db.models.timestamps import utc_now
from aistack.db.ordering import bytewise
from aistack.services import visibility


@dataclass(frozen=True)
class Registered:
    folder: MachineProject
    # This folder had never synced on this computer. Of two first syncs at once, only one
    # says so.
    first_sync: bool


def register_folder(session: Session, user_id: uuid.UUID, machine_id: uuid.UUID, key: str,
                    name: str, harness: Harness, path: str | None) -> Registered:
    """Create or refresh this computer's folder in a project, adding the project to the
    user's own when it is new. This is what a project folder's sync writes, and all it
    writes."""
    folder = _managed(session, machine_id, listed_project(session, user_id, key, name), harness)
    now = utc_now()
    # Conditional, so a folder the dashboard added reports its first sync once even when two
    # syncs find it unsynced together: the second waits on the row and then matches nothing.
    first = session.execute(
        update(MachineProject)
        .where(MachineProject.machine_project_id == folder.machine_project_id,
               MachineProject.last_synced_on.is_(None))
        .values(last_synced_on=now, path=path)
        .execution_options(synchronize_session=False)
    ).rowcount == 1
    if first:
        session.refresh(folder)
    else:
        folder.last_synced_on = now
        folder.path = path
    return Registered(folder, first)


def add_folder(session: Session, user_id: uuid.UUID, machine_id: uuid.UUID, key: str,
               harness: Harness) -> MachineProject:
    """Start managing one of the user's projects on one of their computers, from the
    dashboard. The caller has resolved `machine_id` to one of the user's own. The path stays
    unknown until that folder syncs."""
    return _managed(session, machine_id, visibility.required_my_project(session, user_id, key),
                    harness)


def folder_in(session: Session, user_id: uuid.UUID, machine_id: uuid.UUID, key: str,
              name: str, harness: Harness) -> MachineProject:
    """This computer's folder in a project, made if it is missing, without counting as a
    sync: where replaying a push into a project places it, whatever replayed before."""
    return _managed(session, machine_id, listed_project(session, user_id, key, name), harness)


def remove_folder(session: Session, user_id: uuid.UUID, machine_id: uuid.UUID, key: str,
                  harness: Harness | None = None) -> int:
    """Stop managing a project on one computer, in one harness or in all of them, and return
    how many folders that was. Their placements go with them; the Library, the files on
    disk and the other computers are untouched."""
    project = visibility.required_my_project(session, user_id, key)
    removed = delete(MachineProject).where(MachineProject.machine_id == machine_id,
                                           MachineProject.project_id == project.project_id)
    if harness is not None:
        removed = removed.where(MachineProject.harness == harness)
    count = session.execute(removed.execution_options(synchronize_session=False)).rowcount
    if count == 0:
        raise NotFound(_NOT_MANAGED.format(key=loggable(key)))
    session.expire_all()
    return count


def folder_by_id(session: Session, machine_id: uuid.UUID, project_id: uuid.UUID,
                 harness: Harness) -> MachineProject:
    """The folder an upload URL was minted for, still managed by its computer. One removed
    since refuses the upload before anything is stored."""
    folder = _folder(session, machine_id, project_id, harness)
    if folder is None:
        raise NotFound("This project is no longer managed on this computer, so nothing was "
                       "stored.")
    return folder


def required_folder(session: Session, user_id: uuid.UUID, machine_id: uuid.UUID, key: str,
                    harness: Harness) -> MachineProject:
    """A folder this computer manages. An unknown project, another user's, and one this
    computer does not manage all answer alike."""
    project = visibility.my_project(session, user_id, key)
    folder = None if project is None else _folder(session, machine_id, project.project_id,
                                                  harness)
    if folder is None:
        raise NotFound(_NOT_MANAGED.format(key=loggable(key)))
    return folder


def set_enabled(session: Session, folder: MachineProject, skill_id: uuid.UUID, enabled: bool,
                revision: int | None = None) -> bool:
    """Record a decision about a skill in a project folder, keeping exactly one row per folder
    and skill. True when it differs from the one stored."""
    decision = _decision(session, folder.machine_project_id, skill_id)
    if decision is None:
        try:
            with session.begin_nested():
                session.add(MachineProjectSkill(machine_project_id=folder.machine_project_id,
                                                skill_id=skill_id, enabled=enabled,
                                                revision=revision))
            return True
        except IntegrityError:
            decision = _decision(session, folder.machine_project_id, skill_id)
    changed = decision.enabled != enabled or (revision is not None
                                              and decision.revision != revision)
    decision.enabled = enabled
    if revision is not None:
        decision.revision = revision
    return changed


def disable(session: Session, folder: MachineProject, skill_id: uuid.UUID) -> bool:
    """Record that this folder should not have the skill. False when it never had a
    decision here, which leaves nothing to disable."""
    decision = _decision(session, folder.machine_project_id, skill_id)
    if decision is None:
        return False
    decision.enabled = False
    return True


def decisions(session: Session, folder: MachineProject) -> dict[str, tuple[bool, int | None]]:
    """Every skill decided about in this folder, as `sync_service` reads a global one: True
    enabled, False explicitly disabled, with the revision last installed or pushed there."""
    rows = session.execute(
        select(Skill.name, MachineProjectSkill.enabled, MachineProjectSkill.revision,
               Skill.archived)
        .join(MachineProjectSkill, MachineProjectSkill.skill_id == Skill.skill_id)
        .where(MachineProjectSkill.machine_project_id == folder.machine_project_id)
    ).all()
    return {name: (removed_reads_disabled(enabled, archived), revision)
            for name, enabled, revision, archived in rows}


def removed_reads_disabled(enabled: bool, archived: bool) -> bool:
    """A skill removed from the Library is wanted in no folder, whatever its row says.

    Removing disables every row it knows, so in a global folder this changes nothing. It is
    for project folders: a release from before them removes a skill without touching their
    rows (ADR-0026).
    """
    return enabled and not archived


def placed_elsewhere(session: Session, user_id: uuid.UUID, project_id: uuid.UUID,
                     machine_id: uuid.UUID) -> list[str]:
    """The skills enabled in this project on the user's other computers, in any harness, and
    still in the Library: what a first sync here offers."""
    return list(session.scalars(
        select(Skill.name)
        .join(MachineProjectSkill, MachineProjectSkill.skill_id == Skill.skill_id)
        .join(MachineProject, MachineProject.machine_project_id
              == MachineProjectSkill.machine_project_id)
        .join(Project, Project.project_id == MachineProject.project_id)
        .where(Project.project_id == project_id, Project.user_id == user_id,
               MachineProject.machine_id != machine_id,
               MachineProjectSkill.enabled.is_(True), Skill.archived.is_(False))
        .group_by(Skill.name)
        .order_by(bytewise(Skill.name))
    ))


def folder_paths(session: Session, user_id: uuid.UUID, machine_id: uuid.UUID,
                 key: str) -> list[str]:
    """Where one computer last saw one of the user's projects, in any harness: for
    `aistack start` on that computer, which checks each on disk before using it."""
    project = visibility.my_project(session, user_id, key)
    if project is None:
        return []
    return list(dict.fromkeys(session.scalars(
        select(MachineProject.path)
        .where(MachineProject.machine_id == machine_id,
               MachineProject.project_id == project.project_id,
               MachineProject.path.is_not(None))
        .order_by(MachineProject.harness)
    )))


_NOT_MANAGED = ("This computer does not manage a project '{key}'. Sync from inside the "
                "repository first, or add it on the dashboard.")


def listed_project(session: Session, user_id: uuid.UUID, key: str, name: str) -> Project:
    """One of the user's projects, added to their own when it is new."""
    project = visibility.my_project(session, user_id, key)
    if project is None:
        try:
            with session.begin_nested():
                project = Project(user_id=user_id, key=key, name=name)
                session.add(project)
        except IntegrityError:
            project = visibility.my_project(session, user_id, key)
    return project


def _managed(session: Session, machine_id: uuid.UUID, project: Project,
             harness: Harness) -> MachineProject:
    folder = _folder(session, machine_id, project.project_id, harness)
    if folder is None:
        try:
            # A savepoint, so two first syncs at once cost a re-read and not the report.
            with session.begin_nested():
                folder = MachineProject(machine_id=machine_id, project_id=project.project_id,
                                        harness=harness)
                session.add(folder)
        except IntegrityError:
            folder = _folder(session, machine_id, project.project_id, harness)
    return folder


def _folder(session: Session, machine_id: uuid.UUID, project_id: uuid.UUID,
            harness: Harness) -> MachineProject | None:
    return session.scalar(select(MachineProject).where(
        MachineProject.machine_id == machine_id,
        MachineProject.project_id == project_id,
        MachineProject.harness == harness,
    ))


def _decision(session: Session, machine_project_id: uuid.UUID,
              skill_id: uuid.UUID) -> MachineProjectSkill | None:
    return session.scalar(select(MachineProjectSkill).where(
        MachineProjectSkill.machine_project_id == machine_project_id,
        MachineProjectSkill.skill_id == skill_id,
    ))
