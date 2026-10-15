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

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from aistack.commons.exceptions import AIStackError, NeedsNewerRelease, ValidationError
from aistack.commons.release import UPDATE_AND_RESTART
from aistack.db.models import Base
from aistack.db.models.library_event import LibraryEvent
from aistack.db.models.machine import MACHINE_NAME_MAX_LENGTH, Machine
from aistack.db.models.user import User
from aistack.services import onboarding_service, skill_service, sync_service, visibility
from aistack.services.harnesses import validated_harness
from aistack.services.skill_archive import read_archive
from aistack.services.skill_validation import ValidatedSkill, validated_skill

MACHINE_ADDED = "machine_added"
SKILL_PUSHED = "skill_pushed"
SKILL_PLACED = "skill_placed"
SKILL_REMOVED = "skill_removed"
FOLDER_SYNCED = "folder_synced"
_KINDS = {MACHINE_ADDED, SKILL_PUSHED, SKILL_PLACED, SKILL_REMOVED, FOLDER_SYNCED}
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
    session.add(LibraryEvent(event_id=event.event_id, sort_key=event.sort_key,
                             kind=event.kind, body=event.to_json(), published=published))


# Pushes' archives read ahead of a transaction, by event id: each as the text in its event,
# and the skill it validated to.
Prepared = dict[uuid.UUID, tuple[str, ValidatedSkill]]


def prepared(events: list[Event]) -> Prepared:
    """The archives of the pushes among `events`, read and validated, by event id: done before
    a transaction, so replaying them holds SQLite's write lock only for the writes.

    One that fails is left out, and `apply` reads it again, so the refusal names its file."""
    validated = {}
    for event in events:
        if event.kind != SKILL_PUSHED:
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
    machine = session.get(Machine, event.machine_id)
    if machine is None:
        raise ValidationError(f"The Library's log has a change from computer "
                              f"'{event.machine_id}' before that computer was added.")
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
        target = uuid.UUID(data.get("target_machine_id") or str(machine.machine_id))
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
        record(session, event, published=True)
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
        record(session, event, published=event.event_id in published_ids)


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
    user_id = user.user_id
    taken = set(session.scalars(select(Machine.name).where(Machine.user_id == user_id)))
    name, number = data["machine_name"], 1
    while name in taken:
        number += 1
        suffix = f"-{number}"
        name = data["machine_name"][:MACHINE_NAME_MAX_LENGTH - len(suffix)] + suffix
    return onboarding_service.add_machine(session, user_id, name, data["os"],
                                          machine_id=event.machine_id).machine
