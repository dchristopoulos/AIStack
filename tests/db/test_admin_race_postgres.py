import os
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import select

from aistack.db.engine import build_engine, build_session_factory, create_schema
from aistack.db.models import Base
from aistack.db.models.machine import Machine
from aistack.db.models.user import User
from aistack.services.onboarding_service import _claim_admin
from aistack.services.token_service import generate_machine_token, hash_token

# Never DATABASE_URL: a test that falls back to the server's own variable can drop the tables
# of a real deployment. The absence of TEST_DATABASE_URL is a skip locally and a setup failure
# in CI, which is what keeps this from quietly never running.
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="Set TEST_DATABASE_URL to a PostgreSQL URL to run the concurrent-admin race. "
           "Start one with: docker compose -f compose.test.yaml up -d"
)


@pytest.fixture(name="postgres_session_factory")
def postgres_session_factory_fixture():
    engine = build_engine(TEST_DATABASE_URL)
    Base.metadata.drop_all(engine)
    create_schema(engine)
    yield build_session_factory(engine)
    Base.metadata.drop_all(engine)
    engine.dispose()


JOINER_COUNT = 8


def test_concurrent_joins_produce_exactly_one_admin(postgres_session_factory):
    """The race SQLite cannot reproduce, and the reason the partial index is the enforcer.

    Under READ COMMITTED every transaction evaluates the guard's NOT EXISTS against committed
    rows only, so none of them sees the others' uncommitted writes and all of them would set
    is_admin. The unique partial index rejects all but one; each loser's savepoint absorbs that
    rejection, so the user and machine it inserted beforehand still commit.

    A barrier drives the claims into the same instant rather than hoping eight threads collide:
    a race reproduced by luck is a test that passes for the wrong reason on a quiet machine.
    That is also why this reaches for the claim directly instead of calling join() — the window
    being pinned is between the guard and the commit, and nothing else can aim at it.
    """
    at_the_claim = threading.Barrier(JOINER_COUNT)

    def join_once(index: int) -> None:
        with postgres_session_factory.begin() as session:
            user = User(username=f"user-{index}")
            session.add(user)
            session.flush()

            token = generate_machine_token()
            session.add(Machine(user_id=user.user_id, name=f"machine-{index}", os="LINUX",
                                token_hash=hash_token(token)))
            session.flush()

            at_the_claim.wait(timeout=30)
            _claim_admin(session, user)

    with ThreadPoolExecutor(max_workers=JOINER_COUNT) as pool:
        for outcome in [pool.submit(join_once, index) for index in range(JOINER_COUNT)]:
            outcome.result()  # Re-raises: a join that failed outright is the failure to catch.

    with postgres_session_factory() as session:
        # Every join committed, every machine survived its savepoint, and one user holds admin.
        assert len(session.scalars(select(User)).all()) == JOINER_COUNT
        assert len(session.scalars(select(Machine)).all()) == JOINER_COUNT
        assert len(session.scalars(select(User).where(User.is_admin.is_(True))).all()) == 1
