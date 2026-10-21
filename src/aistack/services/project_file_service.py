"""A project's Markdown files, and edits to them made on the page (ADR-0036, ADR-0038).

`aistack project add` lists a repository's agent files and every other Markdown file git
tracks; the person ticks which ones the page shows. Each sync on a computer that manages the
project uploads a ticked file's text when its hash changed, so the server never reads a disk.
An edit saved on the page waits for one computer: its next sync writes it into the working
copy if the file still has the text the edit started from, and once committed there shares
it on a branch of its own as a pull request. Every lookup starts from a project
`visibility.my_project` returned, or a ticket whose machine is checked again here.
"""

import difflib
import logging
import re
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from aistack.commons.exceptions import Conflict, NotFound, ValidationError
from aistack.commons.text import loggable
from aistack.db.models.machine import Machine
from aistack.db.models.machine_project import PROJECT_PATH_MAX_LENGTH, MachineProject
from aistack.db.models.project import Project
from aistack.db.models.project_file import (
    PULL_REQUEST_URL_MAX_LENGTH,
    SHARE_NOTE_MAX_LENGTH,
    ProjectFile,
    ProjectFileEdit,
)
from aistack.db.models.timestamps import as_utc, utc_now
from aistack.db.ordering import bytewise
from aistack.services import agent_files, onboarding_service, projects, rule_service, visibility
from aistack.services.content_hash import text_hash
from aistack.services.rule_validation import credential_lines, validated_rule_text
from aistack.services.skill_service import require_registered_machine
from aistack.services.transfer_ticket import ProjectFileEditTicket, ProjectFileUploadTicket

logger = logging.getLogger(__name__)

# Far beyond the Markdown in any repository, and a ceiling on what one sync writes.
MAX_LISTED_FILES = 2000
_DIGEST_LENGTH = 64


# The listing -------------------------------------------------------------------------------

def validated_path(path: object) -> str:
    """A path in a repository, relative to its top level with forward slashes, that cannot
    leave it. Checked again by the program before it reads or writes one."""
    if (not isinstance(path, str) or not path or len(path) > PROJECT_PATH_MAX_LENGTH
            or not path.isprintable() or "\\" in path or path.startswith("/")
            or any(part in ("", ".", "..") for part in path.split("/"))):
        raise ValidationError("A project file is a path inside the repository, relative to its "
                              "top level with forward slashes, as git ls-files prints it. "
                              f"Received: '{loggable(path)}'.")
    return path


def validated_listing(raw: object) -> list[tuple[str, int]]:
    """The files `aistack project add` listed, as (path, size). Pure; called before the
    transaction. Only Markdown, and the agent files the table knows, are taken."""
    if not isinstance(raw, list):
        raise ValidationError("project_files is a list of files, each with path and size.")
    if len(raw) > MAX_LISTED_FILES:
        raise ValidationError(f"project_files lists {len(raw)} files, and the limit is "
                              f"{MAX_LISTED_FILES}.")
    listed: dict[str, int] = {}
    for entry in raw:
        if not isinstance(entry, dict):
            raise ValidationError("Each project file is an object with path and size.")
        path, size = validated_path(entry.get("path")), entry.get("size")
        if type(size) is not int or size < 0:
            raise ValidationError(f"The size of {loggable(path)} is a whole number of bytes.")
        if path in listed:
            raise ValidationError(f"project_files lists {loggable(path)} twice.")
        listed[path] = size
    read = agent_files.all_readers(list(listed))
    for path in listed:
        if not path.endswith(".md") and path not in read:
            raise ValidationError(f"{loggable(path)} is neither Markdown nor an agent's file, "
                                  "so it is not listed.")
    return list(listed.items())


def record_listing(session: Session, project: Project, listing: list[tuple[str, int]]) -> int:
    """Keep the files of `project`, which `visibility.my_project` returned, as listed. An
    agent's file is ticked when it is first listed and every other file is not; a tick the
    person changed stays. A file no longer listed goes, with its edits. Returns how many."""
    paths = [path for path, _ in listing]
    listing_paths = set(paths)
    rows ={row.path: row for row in session.scalars(
        select(ProjectFile).where(ProjectFile.project_id == project.project_id))}
    read = agent_files.all_readers(paths)
    for path, size in listing:
        readers = read.get(path, ())
        row = rows.get(path)
        if row is None:
            try:
                with session.begin_nested():
                    session.add(ProjectFile(project_id=project.project_id, path=path,
                                            agent=readers[0] if readers else None,
                                            ticked=bool(readers), size=size))
            except IntegrityError:
                # Listed by two computers at once: the other one's row stands.
                continue
        else:
            row.size = size
            row.agent = readers[0] if readers else None
    gone = [row.project_file_id for path, row in rows.items() if path not in listing_paths]
    if gone:
        session.execute(delete(ProjectFile).where(ProjectFile.project_file_id.in_(gone))
                        .execution_options(synchronize_session=False))
    logger.info(f"Project files listed. Files: '{len(listing)}'. Removed: '{len(gone)}'. "
                f"Project: '{project.project_id}'.")
    return len(listing)


# What a computer does at sync ----------------------------------------------------------------

@dataclass(frozen=True)
class TickedFile:
    project_file_id: uuid.UUID
    path: str
    # The hash of the text last uploaded, or None before the first upload.
    content_hash: str | None


@dataclass(frozen=True)
class PendingEdit:
    project_file_edit_id: uuid.UUID
    path: str
    base_hash: str
    content_hash: str
    # Set once the person pressed Commit…: share it. None: write it into the working copy.
    note: str | None


@dataclass(frozen=True)
class Work:
    files: tuple[TickedFile, ...]
    edits: tuple[PendingEdit, ...]
    # Shared, and shown as shared until the working copy's own history has the shared text.
    shared: tuple[PendingEdit, ...] = ()


def work(session: Session, machine_id: uuid.UUID, project: Project) -> Work:
    """What a computer that manages `project` does with its files at this sync: upload the
    ticked ones that changed, write the edits made for it, and share those committed."""
    files = tuple(TickedFile(*row) for row in session.execute(
        select(ProjectFile.project_file_id, ProjectFile.path, ProjectFile.content_hash)
        .where(ProjectFile.project_id == project.project_id, ProjectFile.ticked.is_(True))
        .order_by(bytewise(ProjectFile.path))))
    edits = tuple(PendingEdit(*row) for row in session.execute(
        select(ProjectFileEdit.project_file_edit_id, ProjectFile.path,
               ProjectFileEdit.base_hash, ProjectFileEdit.content_hash, ProjectFileEdit.note)
        .join(ProjectFile, ProjectFile.project_file_id == ProjectFileEdit.project_file_id)
        .where(ProjectFile.project_id == project.project_id,
               ProjectFileEdit.machine_id == machine_id,
               ProjectFileEdit.cancelled_on.is_(None), ProjectFileEdit.shared_on.is_(None),
               # Not yet written, or written and committed on the page.
               ProjectFileEdit.written_on.is_(None) | ProjectFileEdit.note.is_not(None))
        .order_by(bytewise(ProjectFile.path), ProjectFileEdit.created_on)))
    shared = tuple(PendingEdit(*row) for row in session.execute(
        select(ProjectFileEdit.project_file_edit_id, ProjectFile.path,
               ProjectFileEdit.base_hash, ProjectFileEdit.content_hash, ProjectFileEdit.note)
        .join(ProjectFile, ProjectFile.project_file_id == ProjectFileEdit.project_file_id)
        .where(ProjectFile.project_id == project.project_id,
               ProjectFileEdit.machine_id == machine_id,
               ProjectFileEdit.cancelled_on.is_(None), ProjectFileEdit.shared_on.is_not(None),
               ProjectFileEdit.settled_on.is_(None))
        .order_by(bytewise(ProjectFile.path), ProjectFileEdit.created_on)))
    return Work(files, edits, shared)


@dataclass(frozen=True)
class Snapshot:
    path: str
    saved: bool
    credential_lines: list[int]


def store_snapshot(session: Session, ticket: ProjectFileUploadTicket, text: str) -> Snapshot:
    """Keep the text a computer read of a ticked file, as what the page shows. Text that
    looks like it holds a credential is not kept: the page then shows the file without it."""
    machine = require_registered_machine(session, ticket.machine_id, None, ticket.token_prefix)
    row = session.get(ProjectFile, ticket.project_file_id)
    # Checked again here: the URL outlives the sync that minted it.
    if row is None or not row.ticked or not _manages(session, machine, row.project_id):
        raise NotFound("This file is no longer ticked in a project this computer manages, so "
                       "nothing was stored.")
    lines = credential_lines(text)
    if lines:
        return Snapshot(row.path, False, lines)
    row.text, row.content_hash = text, text_hash(text)
    row.size = len(text.encode("utf-8"))
    row.snapshot_machine_id, row.snapshot_on = machine.machine_id, utc_now()
    return Snapshot(row.path, True, [])


def edit_text(session: Session, ticket: ProjectFileEditTicket) -> tuple[str, str]:
    """The path and text of the edit a URL names, for the computer it was made for."""
    edit, row = _ticketed_edit(session, ticket)
    return row.path, edit.text


def record_outcome(session: Session, ticket: ProjectFileEditTicket, outcome: object) -> str:
    """What became of an edit on its computer: `written` into the working copy, `shared`
    with the pull request's address, `cancelled` by the person there, or, once shared,
    `settled`: the working copy's commit has the shared text, so the page stops showing it."""
    if not isinstance(outcome, dict) or outcome.get("outcome") not in (
            "written", "shared", "cancelled", "settled"):
        raise ValidationError("Say what became of the edit: outcome is written, shared, "
                              "cancelled or settled.")
    kind = outcome["outcome"]
    address = outcome.get("pull_request_url")
    # None where the program could not tell where a pull request is opened.
    if address is not None and (kind != "shared" or not isinstance(address, str)
                                or not address.startswith("https://")
                                or len(address) > PULL_REQUEST_URL_MAX_LENGTH
                                or not address.isprintable() or " " in address):
        raise ValidationError("A shared edit comes with the https address of its pull "
                              "request, or none.")
    edit, row = _ticketed_edit(session, ticket, shared=kind == "settled")
    now = utc_now()
    if kind == "settled":
        if edit.shared_on is None:
            raise Conflict("This edit was not shared, so it cannot be settled.")
        edit.settled_on = now
    elif kind == "written":
        edit.written_on = edit.written_on or now
    elif kind == "shared":
        if edit.written_on is None or edit.note is None:
            raise Conflict("This edit was not committed on the page, so it was not shared.")
        edit.shared_on, edit.pull_request_url = now, address
    else:
        edit.cancelled_on = now
    logger.info(f"Project file edit {kind}. Edit: '{edit.project_file_edit_id}'. "
                f"Machine: '{ticket.machine_id}'.")
    return kind


def _ticketed_edit(session: Session, ticket: ProjectFileEditTicket,
                   shared: bool = False) -> tuple[ProjectFileEdit, ProjectFile]:
    """The edit a URL names, still waiting on its computer; with `shared`, also one shared
    and not settled."""
    machine = require_registered_machine(session, ticket.machine_id, None, ticket.token_prefix)
    edit = session.get(ProjectFileEdit, ticket.project_file_edit_id)
    row = None if edit is None else session.get(ProjectFile, edit.project_file_id)
    if (row is None or edit.machine_id != machine.machine_id or edit.cancelled_on is not None
            or edit.settled_on is not None or (edit.shared_on is not None and not shared)
            or not _manages(session, machine, row.project_id)):
        raise NotFound("This edit is no longer waiting for this computer. Run aistack sync "
                       "again.")
    return edit, row


def _manages(session: Session, machine: Machine, project_id: uuid.UUID) -> bool:
    project = session.get(Project, project_id)
    return project is not None and project.user_id == machine.user_id and session.scalar(
        select(MachineProject.machine_project_id).where(
            MachineProject.machine_id == machine.machine_id,
            MachineProject.project_id == project_id).limit(1)) is not None


# The page -------------------------------------------------------------------------------------

def set_ticked(session: Session, user_id: uuid.UUID, key: str, path: str,
               ticked: bool) -> None:
    """Show a file on the page, and keep its text current, or stop."""
    row = my_file(session, user_id, key, path)
    row.ticked = bool(ticked)
    if not row.ticked:
        # Only a ticked file is read again; what was read of it goes with the tick.
        row.text = row.content_hash = row.snapshot_machine_id = row.snapshot_on = None


def set_turned_off(session: Session, user_id: uuid.UUID, key: str, path: str,
                   turned_off: bool) -> None:
    """Turn a repository's agent file off for this person, or on again. Each computer that
    manages the project does it in the agent's own settings at its next sync; the file itself
    is never touched."""
    row = my_file(session, user_id, key, path)
    reason = _no_turn_off(row.agent)
    if reason is not None:
        raise ValidationError(f"{loggable(path)} cannot be turned off for you. {reason}")
    row.turned_off = bool(turned_off)


def _no_turn_off(agent) -> str | None:
    if agent is None:
        return "No coding agent reads it."
    files = agent_files.AGENT_FILES[agent]
    return files.no_turn_off_reason if files.turn_off is None else None


def save_edit(session: Session, user_id: uuid.UUID, key: str, path: str, text: str,
              base_hash: str, machine_id: str, confirmed: bool = False) -> rule_service.Saved:
    """Keep new text for a repository file, to be written into the working copy of one of
    the person's computers that manages the project. It replaces an edit of the same file
    that has not been shared yet."""
    text = validated_rule_text(text)
    if not isinstance(base_hash, str) or len(base_hash) != _DIGEST_LENGTH:
        raise ValidationError("base_hash is the content hash of the text the edit started "
                              "from, as /api/state lists it.")
    lines = credential_lines(text)
    if lines and not confirmed:
        return rule_service.Saved(path, saved=False, credential_lines=lines)
    row = my_file(session, user_id, key, path)
    if row.content_hash is None or row.content_hash != base_hash:
        raise Conflict(f"{loggable(path)} changed since you opened it. Open it again to edit "
                       "its current text.")
    machine = onboarding_service.own_machine(session, user_id, machine_id)
    if not _manages(session, machine, row.project_id):
        raise ValidationError(f"{machine.name} does not have this project, so it cannot write "
                              "the edit. Choose a computer that does.")
    if text_hash(text) == base_hash:
        return rule_service.Saved(path, saved=True, credential_lines=lines, unchanged=True)
    session.execute(update(ProjectFileEdit)
                    .where(ProjectFileEdit.project_file_id == row.project_file_id,
                           ProjectFileEdit.cancelled_on.is_(None),
                           ProjectFileEdit.shared_on.is_(None))
                    .values(cancelled_on=utc_now())
                    .execution_options(synchronize_session=False))
    session.add(ProjectFileEdit(project_file_id=row.project_file_id,
                                machine_id=machine.machine_id, text=text,
                                content_hash=text_hash(text), base_hash=base_hash,
                                base_text=row.text))
    logger.info(f"Project file edit saved. Machine: '{machine.machine_id}'. "
                f"User: '{user_id}'.")
    return rule_service.Saved(path, saved=True, credential_lines=lines)


def validated_note(note: object) -> str:
    if not isinstance(note, str) or not note.strip():
        raise ValidationError("Say what this change is about: it becomes the commit message.")
    note = note.strip().replace("\r\n", "\n")
    if len(note) > SHARE_NOTE_MAX_LENGTH:
        raise ValidationError(f"The note is {len(note)} characters, and the limit is "
                              f"{SHARE_NOTE_MAX_LENGTH}.")
    if any(not (character.isprintable() or character in "\n\t") for character in note):
        raise ValidationError("The note has a control character in it. Write it as plain "
                              "text.")
    return note


def commit(session: Session, user_id: uuid.UUID, key: str, path: str, note: str) -> str:
    """Ask the computer that wrote an edit to share it as a pull request, with `note` as the
    commit message. It does so at its next sync."""
    note = validated_note(note)
    row = my_file(session, user_id, key, path)
    edit = session.scalar(select(ProjectFileEdit).where(
        ProjectFileEdit.project_file_id == row.project_file_id,
        ProjectFileEdit.cancelled_on.is_(None), ProjectFileEdit.shared_on.is_(None),
        ProjectFileEdit.written_on.is_not(None)).order_by(ProjectFileEdit.created_on.desc())
        .limit(1))
    if edit is None:
        raise Conflict(f"No edit of {loggable(path)} has been written on a computer yet, so "
                       "there is nothing to commit. Sync that computer first.")
    edit.note = note
    logger.info(f"Project file edit committed. Edit: '{edit.project_file_edit_id}'. "
                f"User: '{user_id}'.")
    return note


def my_file(session: Session, user_id: uuid.UUID, key: str, path: str) -> ProjectFile:
    project = visibility.required_my_project(session, user_id, projects.validated_key(key))
    path = validated_path(path)
    row = session.scalar(select(ProjectFile).where(ProjectFile.project_id == project.project_id,
                                                   ProjectFile.path == path))
    if row is None:
        raise NotFound(f"The project has no file {loggable(path)} listed. Add the project "
                       "again on a computer to list its files.")
    return row


def all_files(session: Session, user_id: uuid.UUID) -> list[dict[str, Any]]:
    """Every listed file of the user's projects, as the page reads them: the ticked ones with
    their text, and each file's latest edit that is neither cancelled nor settled."""
    rows = session.execute(
        select(ProjectFile, Project.key, Project.name)
        .join(Project, Project.project_id == ProjectFile.project_id)
        .where(Project.user_id == user_id)
        .order_by(bytewise(Project.key), bytewise(ProjectFile.path))).all()
    ids = [row.project_file_id for row, _, _ in rows]
    edits: dict[uuid.UUID, ProjectFileEdit] = {}
    for edit in session.scalars(select(ProjectFileEdit).where(
            ProjectFileEdit.project_file_id.in_(ids), ProjectFileEdit.cancelled_on.is_(None),
            ProjectFileEdit.settled_on.is_(None))
            .order_by(ProjectFileEdit.created_on)):
        edits[edit.project_file_id] = edit
    listed: dict[str, list[str]] = {}
    for row, key, _ in rows:
        listed.setdefault(key, []).append(row.path)
    read = {key: agent_files.all_readers(paths) for key, paths in listed.items()}
    shown = []
    for row, key, name in rows:
        edit = edits.get(row.project_file_id)
        # An agent this release does not know reads as None (ValueSet).
        agent = row.agent
        shown.append({
            "project": key, "project_name": name, "path": row.path,
            "agent": None if agent is None else agent.value,
            "agents": [reader.value for reader in read[key].get(row.path, ())],
            "ticked": row.ticked, "turned_off": row.turned_off, "size": row.size,
            # Why it cannot be turned off for this person, or null when it can.
            "turn_off_unavailable": _no_turn_off(agent),
            "text": row.text if row.ticked else None, "content_hash": row.content_hash,
            "updated_on": None if row.snapshot_on is None else as_utc(row.snapshot_on).isoformat(),
            "edit": None if edit is None else {
                "machine": None if edit.machine_id is None else str(edit.machine_id),
                "text": edit.text, "content_hash": edit.content_hash,
                "diff": _diff(edit.base_text, edit.text),
                "saved_on": as_utc(edit.created_on).isoformat(),
                "written_on": _when(edit.written_on), "note": edit.note,
                "shared_on": _when(edit.shared_on), "pull_request_url": edit.pull_request_url,
                "branch": None if edit.shared_on is None else branch_name(row.path,
                                                                          edit.content_hash),
            },
        })
    return shown


def branch_name(path: str, content_hash: str) -> str:
    """The branch an edit is shared on: one per file and text."""
    slug = re.sub(r"[^a-z0-9]+", "-", path.lower()).strip("-")[:40].strip("-") or "file"
    return f"aistack/{slug}-{content_hash[:8]}"


def _diff(before: str | None, after: str) -> str | None:
    """The lines an edit adds and removes, as a unified diff without its file headers, or
    None when the text it started from was not kept."""
    if before is None:
        return None
    def lines(text: str) -> list[str]:
        # A last line without a newline would run into the diff's next line.
        return [line if line.endswith("\n") else line + "\n" for line in text.splitlines(True)]

    # Its first two lines are the --- and +++ file headers; the page names the file already.
    return "".join(list(difflib.unified_diff(lines(before), lines(after)))[2:])


def _when(at) -> str | None:
    return None if at is None else as_utc(at).isoformat()
