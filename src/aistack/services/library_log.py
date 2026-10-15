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

from aistack.commons.exceptions import AIStackError, ValidationError
from aistack.db.models import Base
from aistack.db.models.library_event import LibraryEvent
from aistack.db.models.machine import MACHINE_NAME_MAX_LENGTH, Machine
from aistack.db.models.user import User
from aistack.services import onboarding_service, skill_service, sync_service, visibility
from aistack.services.harnesses import validated_harness

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


def new_event(machine_id: uuid.UUID, kind: str, **data: Any) -> Event:
    now = datetime.now(UTC).strftime(_AT_FORMAT)
    return Event(uuid.uuid4(), now, machine_id, kind, data)


def pushed(machine_id: uuid.UUID, name: str, origin: str | None, harness: str,
           archive: bytes) -> Event:
    """A revision, with its files as the archive push validated."""
    return new_event(machine_id, SKILL_PUSHED, name=name, origin=origin, harness=harness,
                     archive=base64.b64encode(archive).decode("ascii"))


def record(session: Session, event: Event, published: bool = False) -> None:
    """Add `event` to this Library's log, in the caller's transaction."""
    session.add(LibraryEvent(event_id=event.event_id, sort_key=event.sort_key,
                             kind=event.kind, body=event.to_json(), published=published))


def apply(session: Session, event: Event) -> Any:
    """Make the change `event` describes, through the call the tool that recorded it made."""
    # Asked first: a newer release's change may also name a computer this one cannot place.
    if event.kind not in _KINDS:
        raise ValidationError(f"The Library's log has a change of a kind this release does "
                              f"not know, '{event.kind}'. Update AIStack on this computer: run "
                              "`uv tool upgrade aistack-mcp`, then restart your coding agent.")
    if event.kind == MACHINE_ADDED:
        return _add_machine(session, event)
    machine = session.get(Machine, event.machine_id)
    if machine is None:
        raise ValidationError(f"The Library's log has a change from computer "
                              f"'{event.machine_id}' before that computer was added.")
    data = event.data
    if event.kind == SKILL_PUSHED:
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
        return skill_service.set_enabled(session, target, validated_harness(data["harness"]),
                                         skill.skill_id, enabled=bool(data["enabled"]))
    if event.kind == SKILL_REMOVED:
        return skill_service.remove_from_my_skills(session, machine.user_id, data["name"])
    if event.kind == FOLDER_SYNCED:
        return sync_service.record_sync(session, machine.machine_id,
                                        validated_harness(data["harness"]))
    raise AssertionError(f"Unhandled event kind '{event.kind}'.")


def _replay(session: Session, event: Event) -> None:
    """`apply`, for an event read from the repository: a failure names its file, which
    anyone who can write to the repository could have put there."""
    try:
        apply(session, event)
    except Exception as error:
        reason = (error.message if isinstance(error, AIStackError)
                  else "It is not a change AIStack makes; remove it from the repository.")
        raise ValidationError(f"The change in log/{event.path} of the Library's repository "
                              f"cannot be applied. {reason}") from error


def applied_through(session: Session) -> str | None:
    """The sort key of the last event this copy holds, or None for an empty log."""
    return session.scalar(select(LibraryEvent.sort_key)
                          .order_by(LibraryEvent.sort_key.desc()).limit(1))


def known_ids(session: Session) -> set[uuid.UUID]:
    return set(session.scalars(select(LibraryEvent.event_id)))


def catch_up(session: Session, arrived: list[Event]) -> bool:
    """Apply events from other computers: on top when they all come after what this copy
    holds, by rebuilding the copy from the whole log when one comes before. True on a rebuild.
    """
    known = known_ids(session)
    new = sorted((event for event in arrived if event.event_id not in known),
                 key=lambda event: event.sort_key)
    if not new:
        return False
    last = applied_through(session)
    if last is None or new[0].sort_key > last:
        for event in new:
            _replay(session, event)
            record(session, event, published=True)
        return False
    rebuild(session, arrived)
    return True


def rebuild(session: Session, events: list[Event]) -> None:
    """Empty this copy and replay `events` with every event recorded here but not yet
    published, in order, so every computer ends with the same Library."""
    unpublished = [Event.from_json(body) for body in session.scalars(
        select(LibraryEvent.body).where(LibraryEvent.published.is_(False)))]
    everything = {event.event_id: event for event in [*events, *unpublished]}
    published_ids = {event.event_id for event in events}
    # Children before parents, so no row is left pointing at one that is gone.
    for table in reversed(Base.metadata.sorted_tables):
        if table.name not in ("alembic_version", "schema_compatibility"):
            session.execute(delete(table))
    # The deleted rows may still be loaded; replay must not find them.
    session.expunge_all()
    for event in sorted(everything.values(), key=lambda event: event.sort_key):
        _replay(session, event)
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
