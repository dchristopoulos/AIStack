"""A report during a back-up preserves local edits and each computer's placement."""

import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import event, select

from aistack.db.engine import build_session_factory
from aistack.db.models.harness import Harness
from aistack.db.models.machine_skill import MachineSkill
from aistack.db.models.skill_version import SkillVersion
from aistack.services import skill_service, sync_service
from aistack.services.reconciliation import Choice, Observed
from aistack.services.skill_archive import read_archive
from aistack.services.skill_validation import validated_skill
from tests.archives import skill_archive
from tests.teams import machines_of_one_user


def test_sync_during_a_push_keeps_local_edits_and_the_other_computers_revision(
        portable_engine, monkeypatch):
    factory = build_session_factory(portable_engine)
    first_archive = skill_archive(files={"notes.md": "first\n"})
    first = validated_skill("wizard", read_archive(first_archive))
    next_revision = validated_skill(
        "wizard", read_archive(skill_archive(files={"notes.md": "backed up elsewhere\n"})))
    local = {"wizard": {file.path: file.sha256 for file in first.files}}
    local["wizard"]["notes.md"] = hashlib.sha256(b"edited here\n").hexdigest()
    with factory.begin() as session:
        computers = machines_of_one_user(session, 2)
        user_id = computers[0].user.user_id
        for computer in computers:
            skill_service.store(session, computer.machine.machine_id, user_id, first, None)

    at_insert, release_push, sync_started = (threading.Event() for _ in range(3))
    store_revision = skill_service._store_revision

    def held_after_hash_read(*args, **kwargs):
        assert args[3].revision == 1
        at_insert.set()
        assert release_push.wait(10)
        return store_revision(*args, **kwargs)

    monkeypatch.setattr(skill_service, "_store_revision", held_after_hash_read)

    def pushing():
        with factory.begin() as session:
            return skill_service.store(
                session, computers[1].machine.machine_id, user_id, next_revision, None)

    def syncing():
        with factory.begin() as session:
            return sync_service.sync(session, computers[0].machine.machine_id, user_id, local)

    def starting_sql(connection, cursor, statement, parameters, context, executemany):
        if threading.current_thread().name.startswith("sync"):
            if portable_engine.dialect.name == "sqlite" and not sync_started.is_set():
                # The writer's lock must be taken before the report reads its snapshot.
                assert statement == "BEGIN IMMEDIATE"
            sync_started.set()

    event.listen(portable_engine, "before_cursor_execute", starting_sql)
    try:
        with ThreadPoolExecutor(max_workers=1) as pushes, ThreadPoolExecutor(
                max_workers=1, thread_name_prefix="sync") as syncs:
            pushed = pushes.submit(pushing)
            try:
                assert at_insert.wait(10)
                report = syncs.submit(syncing)
                assert sync_started.wait(10)
                if portable_engine.dialect.name == "postgresql":
                    # PostgreSQL can report the committed revision while the push is held.
                    during = report.result(timeout=10)
                    assert during.ask[0].latest_revision == 1
                release_push.set()
                assert pushed.result(timeout=10).revision == 2
                during = report.result(timeout=10)
            finally:
                release_push.set()
    finally:
        event.remove(portable_engine, "before_cursor_execute", starting_sql)

    with factory.begin() as session:
        after = sync_service.sync(session, computers[0].machine.machine_id, user_id, local)
        versions = session.scalars(select(SkillVersion).order_by(SkillVersion.revision)).all()
        placements = {
            placed.machine_id: (placed.enabled, placed.revision)
            for placed in session.scalars(select(MachineSkill).where(
                MachineSkill.harness == Harness.CLAUDE_CODE))
        }

    for report in (during, after):
        assert report.install == report.update == ()
        assert len(report.ask) == 1
        question = report.ask[0]
        assert question.name == "wizard" and question.local is Observed.UNKNOWN
        assert question.edited_from == 1
        restore = next(option for option in question.options if option.choice is Choice.RESTORE)
        assert restore.overwrites_local and restore.loses_local_edits
    assert after.ask[0].latest_revision == 2
    assert [(v.revision, v.content_hash) for v in versions] == [
        (1, first.content_hash), (2, next_revision.content_hash),
    ]
    assert placements == {
        computers[0].machine.machine_id: (True, 1),
        computers[1].machine.machine_id: (True, 2),
    }
