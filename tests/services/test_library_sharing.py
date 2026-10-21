"""ADR-0032: a Library copy is rebuilt beside the one other sessions are reading."""

import threading
import time
import uuid

import pytest
from sqlalchemy import event, select

from aistack.db.engine import build_engine, build_session_factory
from aistack.db.models.library_event import LibraryEvent
from aistack.db.models.skill_version import SkillVersion
from aistack.db.models.user import User
from aistack.db.schema import migrate_schema
from aistack.services import library_log, skill_archive, skill_service
from aistack.services.library_sharing import LibrarySharing

PUSHES = 200


class Clone:
    """A repository already pulled, holding `log`."""

    def __init__(self, log):
        self.log = log

    def events(self):
        return list(self.log)


def _copy(path):
    engine = build_engine(f"sqlite:///{path}")
    migrate_schema(engine)
    return engine, build_session_factory(engine)


def _archive(name: str, number: int) -> bytes:
    document = f"---\nname: {name}\ndescription: {name} things.\n---\n\nRevision {number}.\n"
    return skill_archive.build_archive([("SKILL.md", document.encode(), False),
                                        ("notes.md", b"x" * 4096 * (1 + number % 3), False)])


def _log(tmp_path) -> list[library_log.Event]:
    """Another computer's log: it joined, then pushed a few skills many times."""
    _, session_factory = _copy(tmp_path / "laptop.db")
    laptop = uuid.uuid4()
    with session_factory.begin() as session:
        event = library_log.new_event(session, laptop, library_log.MACHINE_ADDED,
                                      user_id=str(uuid.uuid4()), username="maria",
                                      machine_name="laptop", os="MACOS")
        library_log.apply(session, event)
        library_log.record(session, event)
        for number in range(PUSHES):
            name = f"skill-{number % 7}"
            event = library_log.pushed(session, laptop, name, None, "claude_code",
                                       _archive(name, number))
            library_log.apply(session, event)
            library_log.record(session, event)
    with session_factory.begin() as session:
        return [library_log.Event.from_json(body) for body in session.scalars(
            select(LibraryEvent.body).order_by(LibraryEvent.sort_key))]


def _needing_a_rebuild(tmp_path, log, name="desktop"):
    """A copy that read the first event, then recorded a change of its own after the rest:
    the rest of the log sorts before it, so catching up rebuilds."""
    engine, session_factory = _copy(tmp_path / f"{name}.db")
    with session_factory.begin() as session:
        library_log.catch_up(session, log[:1])
        library_log.record(session, library_log.new_event(
            session, log[0].machine_id, library_log.FOLDER_SYNCED, harness="claude_code"))
    return engine, session_factory


def test_a_rebuild_does_not_make_another_session_on_the_copy_wait(tmp_path, monkeypatch):
    log = _log(tmp_path)
    engine, session_factory = _needing_a_rebuild(tmp_path, log)
    # Another agent session on this computer, with its own connections to the copy.
    _, other_session = _copy(tmp_path / "desktop.db")

    # Hold the replay half-way until the other session has read: a read that waits on the
    # rebuild's lock then times out instead of finishing.
    replaying, read_done = threading.Event(), threading.Event()
    stored = skill_service.store
    calls = []

    def store_and_wait(*arguments, **keywords):
        calls.append(1)
        if len(calls) == PUSHES // 2:
            replaying.set()
            read_done.wait(timeout=15)
        return stored(*arguments, **keywords)

    monkeypatch.setattr(skill_service, "store", store_and_wait)
    outcome = {}

    def read():
        replaying.wait(timeout=15)
        started = time.monotonic()
        try:
            with other_session.begin() as session:
                outcome["users"] = len(session.scalars(select(User)).all())
        except Exception as error:
            outcome["error"] = error
        outcome["seconds"] = time.monotonic() - started
        read_done.set()

    reader = threading.Thread(target=read)
    reader.start()
    LibrarySharing(Clone(log), engine, session_factory).replay_clone()
    reader.join()

    assert "error" not in outcome and outcome["seconds"] < 1
    with session_factory.begin() as session:
        assert len(session.scalars(select(SkillVersion)).all()) == PUSHES
        kinds = session.scalars(select(LibraryEvent.kind).order_by(LibraryEvent.sort_key)).all()
        assert kinds[-1] == library_log.FOLDER_SYNCED and len(kinds) == PUSHES + 2
        assert library_log.unpublished(session)[0].kind == library_log.FOLDER_SYNCED
    assert not [path for path in tmp_path.iterdir() if ".rebuild-" in path.name]


@pytest.mark.parametrize("rebuilt", [False, True])
def test_archives_are_never_read_while_the_copy_is_locked(tmp_path, monkeypatch, rebuilt):
    log = _log(tmp_path)
    engine, session_factory = (_needing_a_rebuild(tmp_path, log) if rebuilt
                               else _copy(tmp_path / "desktop.db"))
    locked, reads = [], []
    event.listen(engine, "begin", lambda connection: locked.append(True))
    event.listen(engine, "commit", lambda connection: locked.pop())
    event.listen(engine, "rollback", lambda connection: locked and locked.pop())
    read_archive = skill_archive.read_archive

    def watched(archive):
        reads.append(bool(locked))
        return read_archive(archive)

    monkeypatch.setattr(library_log, "read_archive", watched)
    monkeypatch.setattr(skill_service, "read_archive", watched)
    LibrarySharing(Clone(log), engine, session_factory).replay_clone()

    # Each archive read once, and never while the copy's lock is held.
    assert len(reads) == PUSHES and not any(reads)
    with session_factory.begin() as session:
        assert len(session.scalars(select(SkillVersion)).all()) == PUSHES


def test_a_change_recorded_during_a_rebuild_is_not_lost(tmp_path, monkeypatch):
    log = _log(tmp_path)
    engine, session_factory = _needing_a_rebuild(tmp_path, log)
    stored = skill_service.store
    recorded = []

    def store_and_record(*arguments, **keywords):
        # The first rebuild beside: this computer records a change meanwhile.
        if not recorded:
            with session_factory.begin() as session:
                event = library_log.new_event(session, log[0].machine_id,
                                              library_log.FOLDER_SYNCED, harness="agents")
                library_log.record(session, event)
                recorded.append(event.event_id)
        return stored(*arguments, **keywords)

    monkeypatch.setattr(skill_service, "store", store_and_record)
    LibrarySharing(Clone(log), engine, session_factory).replay_clone()

    with session_factory.begin() as session:
        assert recorded[0] in library_log.known_ids(session)
        assert len(session.scalars(select(SkillVersion)).all()) == PUSHES


def test_a_copy_that_keeps_changing_is_rebuilt_in_place_with_nothing_lost(tmp_path,
                                                                         monkeypatch):
    log = _log(tmp_path)
    engine, session_factory = _needing_a_rebuild(tmp_path, log)
    stored = skill_service.store
    stores, recorded = [], []

    def store_and_record(*arguments, **keywords):
        stores.append(1)
        # Each rebuild beside: this computer records a change meanwhile, so none swaps in.
        if len(recorded) < 3 and len(stores) % PUSHES == 1:
            with session_factory.begin() as session:
                event = library_log.new_event(session, log[0].machine_id,
                                              library_log.FOLDER_SYNCED, harness="agents")
                library_log.record(session, event)
                recorded.append(event.event_id)
        return stored(*arguments, **keywords)

    monkeypatch.setattr(skill_service, "store", store_and_record)
    LibrarySharing(Clone(log), engine, session_factory).replay_clone()

    # Three rebuilds beside, then one in place.
    assert len(stores) == 4 * PUSHES
    with session_factory.begin() as session:
        assert len(session.scalars(select(SkillVersion)).all()) == PUSHES
        assert library_log.known_ids(session) >= {event.event_id for event in log}
        waiting = [event.event_id for event in library_log.unpublished(session)]
        assert len(waiting) == 4 and set(recorded) <= set(waiting)
    assert not [path for path in tmp_path.iterdir() if ".rebuild-" in path.name]


def test_a_copy_rebuilt_beside_matches_one_rebuilt_in_place(tmp_path):
    log = _log(tmp_path)
    engine, session_factory = _needing_a_rebuild(tmp_path, log)
    LibrarySharing(Clone(log), engine, session_factory).replay_clone()
    _, in_place = _needing_a_rebuild(tmp_path, log, name="in-place")
    with in_place.begin() as session:
        assert library_log.catch_up(session, log)

    assert _library(session_factory) == _library(in_place)


def _library(session_factory) -> dict:
    with session_factory.begin() as session:
        return {
            "revisions": sorted(session.execute(select(SkillVersion.revision,
                                                       SkillVersion.content_hash)).all()),
            "log": session.execute(select(LibraryEvent.kind, LibraryEvent.published)
                                   .order_by(LibraryEvent.sort_key)).all()[-3:],
        }
