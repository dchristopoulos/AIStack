"""Two first syncs of one harness must preserve both surrounding transactions."""

import threading
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import select

from aistack.db.engine import build_session_factory
from aistack.db.models.harness import Harness
from aistack.db.models.machine_harness import MachineHarness
from aistack.db.models.user import User
from aistack.services import onboarding_service, sync_service


def test_two_first_syncs_record_one_harness_and_preserve_their_other_writes(
        postgres_engine, monkeypatch):
    factory = build_session_factory(postgres_engine)
    with factory.begin() as session:
        joined = onboarding_service.join(session, "dimitris", "laptop", "LINUX")
    both_read_absent = threading.Barrier(2)
    machine_harness = sync_service._machine_harness
    reads = threading.local()
    reread = []

    def hold_after_first_read(session, machine_id, harness):
        row = machine_harness(session, machine_id, harness)
        if not getattr(reads, "held", False):
            reads.held = True
            assert row is None
            both_read_absent.wait(timeout=10)
        else:
            reread.append(row)
        return row

    monkeypatch.setattr(sync_service, "_machine_harness", hold_after_first_read)

    def sync(index):
        with factory.begin() as session:
            session.add(User(username=f"before-{index}"))
            session.flush()
            first = sync_service.record_sync(session, joined.machine.machine_id, Harness.AGENTS)
            session.add(User(username=f"after-{index}"))
        return first

    with ThreadPoolExecutor(max_workers=2) as pool:
        first_syncs = list(pool.map(sync, range(2)))

    assert sorted(first_syncs) == [False, True]
    assert len(reread) == 1 and reread[0] is not None
    with factory.begin() as session:
        rows = session.scalars(select(MachineHarness)).all()
        assert len(rows) == 1
        assert rows[0].machine_id == joined.machine.machine_id
        assert rows[0].harness == Harness.AGENTS
        assert rows[0].last_synced_on is not None
        assert sorted(session.scalars(select(User.username))) == [
            "after-0", "after-1", "before-0", "before-1", "dimitris",
        ]
