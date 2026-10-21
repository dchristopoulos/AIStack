"""The log of changes a local mode Library is built from, for sharing through GitHub (ADR-0025).

Every change local mode makes is recorded as an event in the same transaction, and replaying
the events through `apply`, in `sort_key` order, builds the same Library on any computer. An
event carries what other computers must agree on (the computer's and the user's ids) and
nothing that is minted per computer (a token, a session, a revision number).
"""

import base64
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from aistack.commons.exceptions import (
    AIStackError,
    Conflict,
    NeedsNewerRelease,
    NotFound,
    ValidationError,
)
from aistack.commons.release import UPDATE_AND_RESTART
from aistack.commons.text import loggable
from aistack.db.models import Base
from aistack.db.models.library_event import LibraryEvent
from aistack.db.models.machine import MACHINE_NAME_MAX_LENGTH, Machine
from aistack.db.models.user import User
from aistack.services import (
    onboarding_service,
    project_file_service,
    project_service,
    projects,
    rule_service,
    skill_service,
    sync_service,
    visibility,
)
from aistack.services.harnesses import validated_harness
from aistack.services.skill_archive import read_archive
from aistack.services.skill_validation import ValidatedSkill, validated_skill

MACHINE_ADDED = "machine_added"
SKILL_PUSHED = "skill_pushed"
SKILL_PLACED = "skill_placed"
SKILL_REMOVED = "skill_removed"
FOLDER_SYNCED = "folder_synced"
# Replayed by this release and recorded by none yet: a release that records them reaches
# computers that have not updated, and they must read them first (ADR-0024).
MACHINE_REMOVED = "machine_removed"
MACHINE_RENAMED = "machine_renamed"
PROJECT_FOLDER_ADDED = "project_folder_added"
PROJECT_FOLDER_REMOVED = "project_folder_removed"
SKILL_PLACED_IN_PROJECT = "skill_placed_in_project"
SKILL_PUSHED_TO_PROJECT = "skill_pushed_to_project"
# Refused by `record`, so this release replays them and writes none. The release that records
# them ships a week after it at the soonest, once every computer has updated itself (ADR-0026).
_PROJECT_KINDS = {
    PROJECT_FOLDER_ADDED,
    PROJECT_FOLDER_REMOVED,
    SKILL_PLACED_IN_PROJECT,
    SKILL_PUSHED_TO_PROJECT,
}
# Where `aistack move` says the Library went (AUTO-05), under the same rule. It names the place
# and never a secret: the kind, and the repository, or the host and database.
LIBRARY_MOVED = "library_moved"
# Rules kept in the Library (ADR-0036), recorded in the release that replays them first
# (ADR-0039). Each names the rule and, for a project's rule, the project's key in `project`
# (None for a rule for every project). A rule's text travels in the event, as a push's files
# do: `text` on a creation and an edit.
RULE_CREATED = "rule_created"  # name, project, text, agents
RULE_EDITED = "rule_edited"  # name, project, text
RULE_RENAMED = "rule_renamed"  # name, project, new_name
RULE_REMOVED = "rule_removed"  # name, project
RULE_AGENTS_SET = "rule_agents_set"  # name, project, agents
_RULE_KINDS = {RULE_CREATED, RULE_EDITED, RULE_RENAMED, RULE_REMOVED, RULE_AGENTS_SET}
# A project's own files (ADR-0036), also recorded in the release that adds them (ADR-0039).
# `path` is the folder the project was listed from on the computer that recorded it, which
# only that computer reads back (`listed_from`).
PROJECT_FILES_LISTED = "project_files_listed"  # project, project_name, path, files, ticked
PROJECT_FILE_TICKED = "project_file_ticked"  # project, path, ticked
PROJECT_FILE_TURNED_OFF = "project_file_turned_off"  # project, path, turned_off
_PROJECT_FILE_KINDS = {PROJECT_FILES_LISTED, PROJECT_FILE_TICKED, PROJECT_FILE_TURNED_OFF}
_REPLAY_ONLY = {*_PROJECT_KINDS, LIBRARY_MOVED}
_KINDS = {MACHINE_ADDED, SKILL_PUSHED, SKILL_PLACED, SKILL_REMOVED, FOLDER_SYNCED,
          MACHINE_REMOVED, MACHINE_RENAMED, LIBRARY_MOVED, *_PROJECT_KINDS, *_RULE_KINDS,
          *_PROJECT_FILE_KINDS}
_AT_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"
# Clocks disagree, but not by this much. A later time would sort every new event before it,
# and each would rebuild the copy.
_FUTURE_ALLOWED = timedelta(days=1)
# The smallest step the text form of a time can show.
_TICK = timedelta(microseconds=1)


@dataclass(frozen=True)
class Event:
    event_id: uuid.UUID
    # UTC, fixed width, so the text sorts as the time does.
    at: str
    machine_id: uuid.UUID
    kind: str
    data: dict[str, Any]

    @property
    def sort_key(self) -> str:
        return f"{self.at}|{self.machine_id}|{self.event_id}"

    @property
    def path(self) -> str:
        """Where the event lives in the log: under its computer's folder, named by its time
        and id. No ':' in the name, which Windows refuses; the order is still the time's."""
        compact = self.at.replace("-", "").replace(":", "")
        return f"{self.machine_id}/{compact}-{self.event_id}.json"

    def to_json(self) -> str:
        return json.dumps({"event_id": str(self.event_id), "at": self.at,
                           "machine_id": str(self.machine_id), "kind": self.kind,
                           "data": self.data}, sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_json(cls, text: str | bytes) -> "Event":
        # Anything can be in a repository, so any failure here is the one refusal: invalid
        # UTF-8, nesting deep enough to exhaust the parser, a field of the wrong type.
        try:
            raw = json.loads(text)
            event = cls(uuid.UUID(raw["event_id"]), str(raw["at"]),
                        uuid.UUID(raw["machine_id"]), str(raw["kind"]), dict(raw["data"]))
            at = datetime.strptime(event.at, _AT_FORMAT).replace(tzinfo=UTC)
        except Exception as error:
            raise ValidationError("A file in the Library's log is not an AIStack event. "
                                  "Remove what was added to the repository by hand.") from error
        if at > datetime.now(UTC) + _FUTURE_ALLOWED:
            raise ValidationError(f"A change in the Library's log is dated {event.at}, in the "
                                  f"future. Remove what was added to the repository by hand.")
        return event


def new_event(session: Session, machine_id: uuid.UUID, kind: str, **data: Any) -> Event:
    """An event made on this computer, timed by a hybrid logical clock (ADR-0032): the wall
    clock, or just after the newest event this copy holds when that is later. A change made
    after reading another computer's then sorts after it, however far ahead that clock ran."""
    at = datetime.now(UTC)
    last = applied_through(session)
    if last is not None:
        newest = datetime.strptime(last.split("|", 1)[0], _AT_FORMAT).replace(tzinfo=UTC)
        at = max(at, newest + _TICK)
    return Event(uuid.uuid4(), at.strftime(_AT_FORMAT), machine_id, kind, data)


def pushed(session: Session, machine_id: uuid.UUID, name: str, origin: str | None,
           harness: str, archive: bytes) -> Event:
    """A revision, with its files as the archive push validated."""
    return new_event(session, machine_id, SKILL_PUSHED, name=name, origin=origin, harness=harness,
                     archive=base64.b64encode(archive).decode("ascii"))


def record(session: Session, event: Event, published: bool = False) -> None:
    """Add `event` to this Library's log, in the caller's transaction."""
    if event.kind in _REPLAY_ONLY:
        raise AssertionError(f"This release replays '{event.kind}' changes and records none.")
    _store_event(session, event, published)


def _store_event(session: Session, event: Event, published: bool) -> None:
    """Remember an incoming event even when this release cannot create its kind yet."""
    session.add(LibraryEvent(
        event_id=event.event_id,
        sort_key=event.sort_key,
        kind=event.kind,
        body=event.to_json(),
        published=published,
    ))


# Pushes' archives read ahead of a transaction, by event id: each as the text in its event,
# and the skill it validated to.
Prepared = dict[uuid.UUID, tuple[str, ValidatedSkill]]


def prepared(events: list[Event]) -> Prepared:
    """The archives of the pushes among `events`, read and validated, by event id: done before
    a transaction, so replaying them holds SQLite's write lock only for the writes.

    One that fails is left out, and `apply` reads it again, so the refusal names its file."""
    validated = {}
    for event in events:
        if event.kind not in (SKILL_PUSHED, SKILL_PUSHED_TO_PROJECT):
            continue
        try:
            archive = event.data["archive"]
            validated[event.event_id] = (archive, validated_skill(
                event.data["name"], read_archive(base64.b64decode(archive))))
        except Exception:
            continue
    return validated


def apply(session: Session, event: Event,
          uploaded: ValidatedSkill | None = None) -> Any:
    """Make the change `event` describes, through the call the tool that recorded it made.
    `uploaded` is a push's archive as `prepared` validated it."""
    # Asked first: a newer release's change may also name a computer this one cannot place.
    if event.kind not in _KINDS:
        raise NeedsNewerRelease(f"The Library's log has a change of a kind this release does "
                                f"not know, '{event.kind}'. {UPDATE_AND_RESTART}")
    if event.kind == MACHINE_ADDED:
        return _add_machine(session, event)
    if event.kind == LIBRARY_MOVED:
        # It changes nothing in the Library: recorded, it makes every tool say where it went.
        return None
    machine = _author(session, event.machine_id)
    data = event.data
    if event.kind == SKILL_PUSHED:
        if uploaded is not None:
            return skill_service.store(session, machine.machine_id, machine.user_id, uploaded,
                                       data.get("origin"), data["harness"])
        return skill_service.push(session, machine.machine_id, machine.user_id, data["name"],
                                  data.get("origin"), base64.b64decode(data["archive"]),
                                  data["harness"])
    if event.kind == SKILL_PLACED:
        # A computer can place a skill on another of the person's computers, from the
        # dashboard; the event is still filed under the computer that made the change.
        target = _target(data.get("target_machine_id") or str(machine.machine_id))
        placed_on = session.get(Machine, target)
        if placed_on is None or placed_on.user_id != machine.user_id:
            # Placed while another computer removed it, or a log edited to name someone
            # else's: nothing of the person's is left to place on.
            return None
        skill = visibility.required_my_skill(session, machine.user_id, data["name"],
                                             removed_too=True)
        if data["enabled"]:
            skill.archived = False
        revision = data.get("revision")
        if revision is not None and type(revision) is not int:
            raise ValidationError("A change in the Library's log names a revision that is not "
                                  "a number. Remove what was added to the repository by hand.")
        return skill_service.set_enabled(session, target, validated_harness(data["harness"]),
                                         skill.skill_id, enabled=bool(data["enabled"]),
                                         revision=revision)
    if event.kind == SKILL_REMOVED:
        return skill_service.remove_from_my_skills(session, machine.user_id, data["name"])
    if event.kind == FOLDER_SYNCED:
        return sync_service.record_sync(session, machine.machine_id,
                                        validated_harness(data["harness"]))
    if event.kind == MACHINE_REMOVED:
        return _remove_machine(session, machine.user_id, _target(data["target_machine_id"]))
    if event.kind == MACHINE_RENAMED:
        return _rename_machine(session, machine.user_id, _target(data["target_machine_id"]),
                               data["name"])
    if event.kind in _PROJECT_KINDS:
        return _apply_to_project(session, machine, event, uploaded)
    if event.kind in _RULE_KINDS:
        return _apply_to_rule(session, machine.user_id, event)
    if event.kind in _PROJECT_FILE_KINDS:
        return _apply_to_project_files(session, machine.user_id, event)
    raise AssertionError(f"Unhandled event kind '{event.kind}'.")


def _replay(session: Session, event: Event,
            validated: Prepared) -> None:
    """`apply`, for an event read from the repository: a failure names its file, which
    anyone who can write to the repository could have put there."""
    ahead = validated.get(event.event_id)
    # Only for the very archive it was read from: two files in a repository can claim one id.
    uploaded = ahead[1] if ahead is not None and ahead[0] == event.data.get("archive") else None
    try:
        apply(session, event, uploaded)
    except Exception as error:
        reason = (error.message if isinstance(error, AIStackError)
                  else "It is not a change AIStack makes; remove it from the repository.")
        # Still a NeedsNewerRelease when it was one, so local mode can update itself.
        refusal = NeedsNewerRelease if isinstance(error, NeedsNewerRelease) else ValidationError
        raise refusal(f"The change in log/{event.path} of the Library's repository cannot be "
                      f"applied. {reason}") from error


def applied_through(session: Session) -> str | None:
    """The sort key of the last event this copy holds, or None for an empty log."""
    return session.scalar(select(LibraryEvent.sort_key)
                          .order_by(LibraryEvent.sort_key.desc()).limit(1))


def known_ids(session: Session) -> set[uuid.UUID]:
    return set(session.scalars(select(LibraryEvent.event_id)))


def arrivals(session: Session, events: list[Event]) -> list[Event]:
    """The events this copy does not hold yet, in order."""
    known = known_ids(session)
    return sorted((event for event in events if event.event_id not in known),
                  key=lambda event: event.sort_key)


def append(session: Session, new: list[Event],
           validated: Prepared | None = None) -> bool:
    """Apply `new` on top of this copy when every one comes after what it holds. False, with
    nothing applied, when one comes before: then only a rebuild puts the copy in order."""
    last = applied_through(session)
    if new and last is not None and new[0].sort_key <= last:
        return False
    for event in new:
        _replay(session, event, validated or {})
        _store_event(session, event, published=True)
    return True


def catch_up(session: Session, arrived: list[Event]) -> bool:
    """Apply events from other computers: on top when they all come after what this copy
    holds, by rebuilding the copy from the whole log when one comes before. True on a rebuild.

    The rebuild holds the transaction for the whole replay; `LibrarySharing` rebuilds beside
    a copy other sessions use instead.
    """
    if append(session, arrivals(session, arrived)):
        return False
    rebuild(session, arrived)
    return True


def rebuild(session: Session, events: list[Event], local: list[Event] | None = None,
            validated: Prepared | None = None) -> None:
    """Empty this copy and replay `events` with the events recorded on this computer but not
    yet published, in order, so every computer ends with the same Library.

    `local` is those events when they come from another copy than `session`'s; by default
    they are read from it."""
    if local is None:
        local = unpublished(session)
    everything = {event.event_id: event for event in [*events, *local]}
    published_ids = {event.event_id for event in events}
    # Children before parents, so no row is left pointing at one that is gone.
    for table in reversed(Base.metadata.sorted_tables):
        if table.name not in ("alembic_version", "schema_compatibility"):
            session.execute(delete(table))
    # The deleted rows may still be loaded; replay must not find them.
    session.expunge_all()
    for event in sorted(everything.values(), key=lambda event: event.sort_key):
        _replay(session, event, validated or {})
        _store_event(session, event, published=event.event_id in published_ids)


def unpublished(session: Session) -> list[Event]:
    return [Event.from_json(body) for body in session.scalars(
        select(LibraryEvent.body).where(LibraryEvent.published.is_(False))
        .order_by(LibraryEvent.sort_key))]


def mark_published(session: Session, event_ids: list[uuid.UUID]) -> None:
    for row in session.scalars(select(LibraryEvent).where(LibraryEvent.event_id.in_(event_ids))):
        row.published = True


def _add_machine(session: Session, event: Event) -> Machine:
    data = event.data
    machine = session.get(Machine, event.machine_id)
    if machine is not None:
        return machine
    user = session.get(User, uuid.UUID(data["user_id"])) or session.scalar(select(User).limit(1))
    if user is None:
        return onboarding_service.join(session, data["username"], data["machine_name"],
                                       data["os"], machine_id=event.machine_id,
                                       user_id=uuid.UUID(data["user_id"])).machine
    # A Library is one person's. Two new computers that started at once each made the user,
    # and the one that sorts first is the person: the other computer joins them.
    return onboarding_service.add_machine(
        session,
        user.user_id,
        _free_name(session, user.user_id, data["machine_name"]),
        data["os"],
        machine_id=event.machine_id,
    ).machine


def removed(session: Session, machine_id: uuid.UUID, target: Machine) -> Event:
    """`target` taken out of the Library, with what brings it back if it was still in use."""
    return new_event(session, machine_id, MACHINE_REMOVED,
                     target_machine_id=str(target.machine_id), name=target.name,
                     os=target.os.value)


def renamed(session: Session, machine_id: uuid.UUID, target: uuid.UUID, name: str) -> Event:
    return new_event(session, machine_id, MACHINE_RENAMED, target_machine_id=str(target),
                     name=name)


def refuse_when_moved(session: Session) -> None:
    """Refuse with where the Library went, once a move from this place is in its log: this
    copy is left as it was, and a change made to it would reach none of the person's other
    computers (AUTO-05)."""
    body = session.scalar(select(LibraryEvent.body).where(LibraryEvent.kind == LIBRARY_MOVED)
                          .order_by(LibraryEvent.sort_key.desc()).limit(1))
    if body is None:
        return
    event = Event.from_json(body)
    place, day = event.data.get("place"), event.at[:10]
    kind = place.get("kind") if isinstance(place, dict) else None
    follow = ("Set AIStack up again on this computer with that place to follow it. Nothing "
              "was changed here.")
    # Escaped and bounded: anyone who can write to the old repository chose these.
    if kind == "github":
        raise Conflict(f"Your Library moved to the GitHub repository "
                       f"{loggable(place.get('repository'))} on {day}. {follow}")
    if kind == "postgresql":
        raise Conflict(f"Your Library moved to the PostgreSQL database "
                       f"{loggable(place.get('database'))} at {loggable(place.get('host'))} "
                       f"on {day}. {follow}")
    if kind == "this_computer":
        mover = session.get(Machine, event.machine_id)
        name = f"'{mover.name}'" if mover is not None else "another computer"
        raise Conflict(f"Your Library moved onto {name} alone on {day}, where this computer "
                       f"cannot reach it. To share it again, run `aistack move github` or "
                       f"`aistack move postgresql` there, then set AIStack up again here with "
                       f"that place. Nothing was changed here.")
    raise NeedsNewerRelease(f"Your Library moved on {day}, to a place this release cannot "
                            f"name. {UPDATE_AND_RESTART}")


def _author(session: Session, machine_id: uuid.UUID) -> Machine:
    """The computer that made a change. One removed since comes back (ADR-0033): it was
    offline when another computer removed it, and a change from it says it is still in use."""
    machine = session.get(Machine, machine_id)
    if machine is not None:
        return machine
    removal = _last_removal(session, machine_id)
    if removal is None:
        raise ValidationError(f"The Library's log has a change from computer "
                              f"'{machine_id}' before that computer was added.")
    user_id = session.scalar(select(User.user_id).limit(1))
    return onboarding_service.add_machine(
        session,
        user_id,
        _free_name(session, user_id, removal["name"]),
        removal["os"],
        machine_id=machine_id,
    ).machine


def _last_removal(session: Session, machine_id: uuid.UUID) -> dict[str, Any] | None:
    """The data of the newest replayed removal of `machine_id`. Replay records each event as
    it applies it, so the copy's log holds exactly what came before."""
    bodies = session.scalars(select(LibraryEvent.body)
                             .where(LibraryEvent.kind == MACHINE_REMOVED)
                             .order_by(LibraryEvent.sort_key.desc()))
    for body in bodies:
        data = Event.from_json(body).data
        if data.get("target_machine_id") == str(machine_id):
            return data
    return None


def _remove_machine(session: Session, user_id: uuid.UUID, target: uuid.UUID) -> str | None:
    """Two computers can remove the same one, or each other, while offline. Neither stops
    replay: a computer already gone, or the last one left, stays as it is."""
    machine = session.get(Machine, target)
    if machine is None or machine.user_id != user_id:
        return None
    others = session.scalar(select(func.count()).select_from(Machine).where(
        Machine.user_id == user_id, Machine.machine_id != target))
    if not others:
        return None
    return onboarding_service.remove_machine(session, user_id, str(target))


def _rename_machine(session: Session, user_id: uuid.UUID, target: uuid.UUID,
                    name: str) -> str | None:
    """A name another computer took meanwhile gets a suffix, as a new computer's does."""
    machine = session.get(Machine, target)
    if machine is None or machine.user_id != user_id:
        return None
    if not isinstance(name, str):
        raise ValidationError("A change in the Library's log names a computer with something "
                              "that is not text. Remove what was added to the repository by "
                              "hand.")
    return onboarding_service.rename_machine(
        session,
        user_id,
        str(target),
        _free_name(session, user_id, name, but=target),
    )


def _apply_to_project(session: Session, machine: Machine, event: Event,
                      uploaded: ValidatedSkill | None) -> Any:
    """A change to a project folder (ADR-0026), with every value checked as the tool that
    recorded it checks it: anyone who can write to the repository can forge one."""
    data = event.data
    key = projects.validated_key(data["project"])
    harness = None if data.get("harness") is None else validated_harness(data["harness"])
    if event.kind == SKILL_PUSHED_TO_PROJECT:
        folder = project_service.folder_in(session, machine.user_id, machine.machine_id, key,
                                           projects.validated_name(data["project_name"]),
                                           validated_harness(harness))
        if uploaded is None:
            return skill_service.push(session, machine.machine_id, machine.user_id,
                                      data["name"], data.get("origin"),
                                      base64.b64decode(data["archive"]), harness.value,
                                      project_folder=folder)
        return skill_service.store(session, machine.machine_id, machine.user_id, uploaded,
                                   data.get("origin"), harness.value, project_folder=folder)
    # The dashboard changes another of the person's computers; a computer removed meanwhile
    # has nothing left to change.
    target = session.get(Machine, _target(data.get("target_machine_id")
                                          or str(machine.machine_id)))
    if target is None or target.user_id != machine.user_id:
        return None
    if event.kind == PROJECT_FOLDER_ADDED:
        path = data.get("path")
        if path is not None:
            path = projects.validated_here(path, None).path
        if target.machine_id == machine.machine_id and path is not None:
            return project_service.register_folder(
                session, machine.user_id, target.machine_id, key,
                projects.validated_name(data["project_name"]), validated_harness(harness),
                path).first_sync
        return project_service.folder_in(session, machine.user_id, target.machine_id, key,
                                         projects.validated_name(data["project_name"]),
                                         validated_harness(harness))
    try:
        if event.kind == PROJECT_FOLDER_REMOVED:
            return project_service.remove_folder(session, machine.user_id, target.machine_id,
                                                 key, harness)
        folder = project_service.required_folder(session, machine.user_id, target.machine_id,
                                                 key, validated_harness(harness))
    except NotFound:
        # Another computer stopped managing it first: nothing is left to change.
        return None
    skill = visibility.required_my_skill(session, machine.user_id, data["name"],
                                         removed_too=True)
    if data["enabled"]:
        skill.archived = False
    revision = data.get("revision")
    if revision is not None and type(revision) is not int:
        raise ValidationError("A change in the Library's log names a revision that is not "
                              "a number. Remove what was added to the repository by hand.")
    return project_service.set_enabled(session, folder, skill.skill_id,
                                       enabled=bool(data["enabled"]), revision=revision)


def _apply_to_rule(session: Session, user_id: uuid.UUID, event: Event) -> Any:
    """A change to a rule, through the `rule_service` call the dashboard makes, which checks
    every value as it does for a request: anyone who can write to the repository can forge one.

    Two computers can change one rule offline, so a change that no longer fits leaves the
    Library as it was instead of stopping replay: one to a rule renamed or removed meanwhile,
    a rename to a name taken meanwhile, an agent another rule for every project took. Each
    runs in a savepoint, so a refusal halfway leaves nothing behind."""
    data = event.data
    name, project = data["name"], data.get("project")

    def attempt(change, **arguments) -> tuple[bool, Any]:
        try:
            with session.begin_nested():
                return True, change(session, user_id, name, project=project, **arguments)
        except (Conflict, NotFound) as refused:
            # A project that is not the person's is a forged change, never a race: projects
            # are never deleted.
            if isinstance(refused, NotFound) and project is not None:
                visibility.required_my_project(session, user_id, projects.validated_key(project))
            return False, None

    if event.kind == RULE_CREATED:
        # The person confirmed a text that looked like a credential before it was recorded.
        done, saved = attempt(rule_service.create, text=data["text"], agents=data["agents"],
                              confirmed=True)
        if not done:
            # An agent another rule took meanwhile: the rule and its text are kept, unused.
            done, saved = attempt(rule_service.create, text=data["text"], agents=[],
                                  confirmed=True)
        if not done:
            # Two computers created one name offline: the later text is a new revision.
            saved = attempt(rule_service.edit, text=data["text"], confirmed=True)[1]
        return saved
    if event.kind == RULE_EDITED:
        return attempt(rule_service.edit, text=data["text"], confirmed=True)[1]
    if event.kind == RULE_RENAMED:
        return attempt(rule_service.rename, new_name=data["new_name"])[1]
    if event.kind == RULE_REMOVED:
        return attempt(rule_service.archive)[1]
    return attempt(rule_service.set_agents, agents=data["agents"])[1]


def _apply_to_project_files(session: Session, user_id: uuid.UUID, event: Event) -> Any:
    """A project's files listed, or one ticked or turned off, through the calls the dashboard
    makes, with every value checked again: anyone who can write to the repository can forge
    one. A file another computer's listing dropped meanwhile leaves the Library as it was."""
    data = event.data
    key = projects.validated_key(data["project"])
    if event.kind == PROJECT_FILES_LISTED:
        name = projects.validated_name(data["project_name"])
        projects.validated_here(data["path"], None)
        listing = project_file_service.validated_listing(data["files"])
        ticked = data["ticked"]
        if not isinstance(ticked, list) or not set(ticked) <= {path for path, _ in listing}:
            raise ValidationError("A change in the Library's log ticks a file it does not "
                                  "list. Remove what was added to the repository by hand.")
        project = project_service.listed_project(session, user_id, key, name)
        project_file_service.record_listing(session, project, listing)
        for path, _ in listing:
            project_file_service.set_ticked(session, user_id, key, path, path in ticked)
        return project
    field = "ticked" if event.kind == PROJECT_FILE_TICKED else "turned_off"
    if type(data[field]) is not bool:
        raise ValidationError(f"A change in the Library's log sets {field} to something that "
                              "is not true or false. Remove what was added to the repository "
                              "by hand.")
    change = (project_file_service.set_ticked if event.kind == PROJECT_FILE_TICKED
              else project_file_service.set_turned_off)
    try:
        with session.begin_nested():
            return change(session, user_id, key, data["path"], data[field])
    except NotFound:
        # Projects are never deleted, so one that is not the person's is a forged change.
        visibility.required_my_project(session, user_id, key)
        return None


def listed_from(session: Session, machine_id: uuid.UUID, key: str) -> str | None:
    """The folder `machine_id` last listed project `key` from, as its own event recorded it,
    or None when it never did. Display data: the caller checks the folder on disk."""
    return listed_here(session, machine_id).get(key)


def listed_here(session: Session, machine_id: uuid.UUID) -> dict[str, str]:
    """`listed_from` for every project `machine_id` listed, by key."""
    folders: dict[str, str] = {}
    bodies = session.scalars(select(LibraryEvent.body)
                             .where(LibraryEvent.kind == PROJECT_FILES_LISTED)
                             .order_by(LibraryEvent.sort_key.desc()))
    for body in bodies:
        event = Event.from_json(body)
        key, path = event.data.get("project"), event.data.get("path")
        if event.machine_id == machine_id and isinstance(key, str) and isinstance(path, str):
            folders.setdefault(key, path)
    return folders


def _target(text: object) -> uuid.UUID:
    try:
        return uuid.UUID(str(text))
    except ValueError as error:
        raise ValidationError("A change in the Library's log names a computer by something "
                              "that is not an id. Remove what was added to the repository by "
                              "hand.") from error


def _free_name(session: Session, user_id: uuid.UUID, wanted: str,
               but: uuid.UUID | None = None) -> str:
    """`wanted`, or `wanted-2`, `-3` and so on when another of the person's computers has it."""
    taken = set(session.scalars(select(Machine.name).where(Machine.user_id == user_id,
                                                           Machine.machine_id != but)))
    name, number = wanted, 1
    while name in taken:
        number += 1
        suffix = f"-{number}"
        name = wanted[:MACHINE_NAME_MAX_LENGTH - len(suffix)] + suffix
    return name
