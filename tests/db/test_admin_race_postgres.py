import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import false, select

from aistack.db.engine import build_session_factory
from aistack.db.models.machine import Machine
from aistack.db.models.user import User
from aistack.services import onboarding_service

JOINER_COUNT = 8


@pytest.mark.parametrize("force_contenders", [False, True], ids=["real-guard", "all-contend"])
def test_concurrent_join_keeps_every_machine_and_one_admin(postgres_engine, monkeypatch,
                                                           caplog, force_contenders):
    session_factory = build_session_factory(postgres_engine)
    at_the_claim = threading.Barrier(JOINER_COUNT)
    claim_admin = onboarding_service._claim_admin

    def claim_together(session, user):
        at_the_claim.wait(timeout=30)
        claim_admin(session, user)

    monkeypatch.setattr(onboarding_service, "_claim_admin", claim_together)
    if force_contenders:
        # Reproduce every contender observing no committed admin, regardless of scheduling.
        # The real UPDATE, unique index, savepoint, and outer transaction still decide the result.
        monkeypatch.setattr(onboarding_service, "exists", lambda query: false())

    def join_once(index):
        with session_factory.begin() as session:
            return onboarding_service.join(session, f"racer-{index}\nline", f"box-{index}", "MACOS")

    with caplog.at_level("INFO"), ThreadPoolExecutor(max_workers=JOINER_COUNT) as pool:
        joined = list(pool.map(join_once, range(JOINER_COUNT)))

    assert sum(result.user.is_admin for result in joined) == 1
    with session_factory() as session:
        assert len(session.scalars(select(User)).all()) == JOINER_COUNT
        assert len(session.scalars(select(Machine)).all()) == JOINER_COUNT
        assert len(session.scalars(select(User).where(User.is_admin.is_(True))).all()) == 1

    if force_contenders:
        losers = [r.getMessage() for r in caplog.records if "Admin already claimed concurrently" in r.getMessage()]
        assert len(losers) == JOINER_COUNT - 1
        assert all("\n" not in message and "\\nline" in message for message in losers)
