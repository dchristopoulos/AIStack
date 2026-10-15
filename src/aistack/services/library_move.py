"""Moving a local mode Library to another place by replaying its log there (ADR-0025).

Every change local mode makes is recorded as an event, so the log is the Library, history,
placements and removals included. A move refuses whenever that might not hold: a log that
does not rebuild the Library it came from, or a destination that already holds one.
"""

import uuid
from pathlib import Path

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from aistack.commons.exceptions import AIStackError, Conflict
from aistack.db.engine import build_engine, build_session_factory
from aistack.db.models.library_event import LibraryEvent
from aistack.db.models.machine import Machine
from aistack.db.models.machine_harness import MachineHarness
from aistack.db.models.machine_skill import MachineSkill
from aistack.db.models.skill import Skill
from aistack.db.models.skill_version import SkillVersion
from aistack.db.models.user import User
from aistack.db.schema import migrate_schema
from aistack.services import library_log
from aistack.services.library_log import Event
from aistack.services.library_repo import LibraryRepo


def events(session: Session) -> list[Event]:
    """Every event this Library holds, in replay order."""
    return [Event.from_json(body) for body in session.scalars(
        select(LibraryEvent.body).order_by(LibraryEvent.sort_key))]


def contents(session: Session) -> dict:
    """The Library as its person sees it, in terms every copy agrees on: not the ids or
    times a copy mints for itself."""
    names = dict(session.execute(select(Skill.skill_id, Skill.name)).all())
    return {
        "users": sorted(session.execute(select(User.user_id, User.username)).all()),
        "machines": sorted(session.execute(select(Machine.machine_id, Machine.name)).all()),
        "skills": sorted(session.execute(
            select(Skill.name, Skill.archived, Skill.description, Skill.origin)).all()),
        "revisions": sorted(
            (names[skill_id], revision, content_hash)
            for skill_id, revision, content_hash in session.execute(
                select(SkillVersion.skill_id, SkillVersion.revision,
                       SkillVersion.content_hash)).all()),
        "placements": sorted(
            (machine_id, harness.value, names[skill_id], enabled, revision or 0)
            for machine_id, harness, skill_id, enabled, revision in session.execute(
                select(MachineSkill.machine_id, MachineSkill.harness, MachineSkill.skill_id,
                       MachineSkill.enabled, MachineSkill.revision)).all()),
        "folders": sorted((machine_id, harness.value) for machine_id, harness in session.execute(
            select(MachineHarness.machine_id, MachineHarness.harness)).all()),
    }


def check_replays(log: list[Event], expected: dict, scratch: Path) -> None:
    """Refuse a log that does not rebuild `expected`, the Library it was read from. A Library
    older than its log holds changes no event records, and moving it by its log would drop
    them without a word."""
    file = scratch / f"aistack-move-check-{uuid.uuid4().hex}.db"
    engine = build_engine(f"sqlite:///{file.as_posix()}")
    try:
        migrate_schema(engine)
        try:
            _replay_into(engine, log)
            with build_session_factory(engine).begin() as session:
                rebuilt = contents(session)
        except AIStackError:
            # Not even replayable: a change recorded on top of one the log never had.
            rebuilt = None
    finally:
        engine.dispose()
        for leftover in (file, *(file.with_name(file.name + suffix)
                                 for suffix in ("-wal", "-shm", "-journal"))):
            leftover.unlink(missing_ok=True)
    if rebuilt != expected:
        raise Conflict("This Library holds changes from before AIStack kept a log of them, so "
                       "moving it by its log would lose some. Nothing was moved. Export it "
                       "instead (`aistack export`), set AIStack up in the new place, and copy "
                       "the exported folders into a skills folder there.")


def into_database(engine: Engine, log: list[Event]) -> None:
    """Replay `log` into an empty database, in one transaction: all of it lands or none."""
    migrate_schema(engine)
    with build_session_factory(engine)() as session:
        if session.scalar(select(User.user_id).limit(1)) is not None:
            raise Conflict("That database already holds a Library, so nothing was moved into "
                           "it. Choose an empty database.")
    _replay_into(engine, log)


def into_repository(repo: LibraryRepo, log: list[Event]) -> int:
    """Publish `log` to a repository that holds no other Library; how many it added. A
    repository already holding some of this log, from a move that stopped, takes the rest."""
    repo.pull()
    ours = {event.event_id for event in log}
    there = {event.event_id for event in repo.events()}
    if there - ours:
        raise Conflict("That repository already holds another Library's log, so nothing was "
                       "moved into it. Choose a new private repository.")
    missing = [event for event in log if event.event_id not in there]
    repo.publish(missing)
    return len(missing)


def _replay_into(engine: Engine, log: list[Event]) -> None:
    # Archives are read before the transaction opens (ADR-0032).
    validated = library_log.prepared(log)
    with build_session_factory(engine).begin() as session:
        library_log.rebuild(session, log, local=[], validated=validated)
