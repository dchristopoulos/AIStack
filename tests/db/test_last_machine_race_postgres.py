"""Two removals at once must not leave a person with no computer (ADR-0027)."""

import threading
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import func, select

from aistack.commons.exceptions import Conflict
from aistack.db.engine import build_session_factory
from aistack.db.models.machine import Machine
from aistack.services import onboarding_service


def test_removing_both_computers_at_once_keeps_one(postgres_engine, monkeypatch):
    session_factory = build_session_factory(postgres_engine)
    with session_factory.begin() as session:
        joined = onboarding_service.join(session, "dimitris", "laptop", "MACOS")
        desktop = onboarding_service.add_machine(session, joined.user.user_id, "desktop",
                                                 "LINUX")
        user_id = joined.user.user_id
        machine_ids = [str(joined.machine.machine_id), str(desktop.machine.machine_id)]

    # Both removals hold their computer and are about to count the other one. With the lock,
    # the second never gets here while the first is open, so the wait gives up and the first
    # goes on alone.
    both_found_theirs = threading.Barrier(2)
    own_machine = onboarding_service.own_machine

    def found_together(session, user_id, machine_id):
        machine = own_machine(session, user_id, machine_id)
        try:
            both_found_theirs.wait(timeout=2)
        except threading.BrokenBarrierError:
            pass
        return machine

    monkeypatch.setattr(onboarding_service, "own_machine", found_together)

    def remove(machine_id):
        try:
            with session_factory.begin() as session:
                return onboarding_service.remove_machine(session, user_id, machine_id)
        except Conflict as refused:
            return refused

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(remove, machine_ids))

    assert sorted(type(outcome).__name__ for outcome in outcomes) == ["Conflict", "str"]
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Machine)) == 1
