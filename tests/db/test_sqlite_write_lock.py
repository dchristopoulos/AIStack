import threading
import time
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import select, text

from aistack.db.engine import build_session_factory
from aistack.db.models.skill_version import SkillVersion
from aistack.db.models.user import User
from aistack.services import onboarding_service, skill_service
from tests.archives import skill_archive
from tests.teams import machines_of_one_user

# PostgreSQL never had this problem: its writers wait for each other. These tests are about
# SQLite, which is the default backend and so the one most deployments run.
WRITER_COUNT = 8


def test_a_transaction_holds_the_write_lock_from_its_first_statement(engine):
    """The mechanism itself: a second transaction waits for the first to finish.

    With a deferred BEGIN the second transaction starts at once, reads, and is then refused
    the moment it writes, because what it read is already stale and no amount of waiting can
    fix that. Taking the lock at BEGIN is what turns that failure into a short queue.
    """
    session_factory = build_session_factory(engine)
    first_is_open = threading.Event()
    finished: dict[str, float] = {}

    def first():
        with session_factory.begin() as session:
            session.execute(text("SELECT 1"))
            first_is_open.set()
            time.sleep(0.3)
        finished["first"] = time.perf_counter()

    def second():
        first_is_open.wait(timeout=5)
        with session_factory.begin() as session:
            session.execute(text("SELECT 1"))
            finished["second began"] = time.perf_counter()

    with ThreadPoolExecutor(max_workers=2) as pool:
        for future in [pool.submit(first), pool.submit(second)]:
            future.result(timeout=10)

    assert finished["second began"] >= finished["first"]


def _joined(session_factory, count):
    with session_factory.begin() as session:
        return [onboarding_service.join(session, f"pusher-{index}", "box", "LINUX")
                for index in range(count)]


def _push_all_at_once(session_factory, pushers, name_for, content_for):
    at_the_start = threading.Barrier(len(pushers))

    def push(index):
        at_the_start.wait(timeout=10)
        with session_factory.begin() as session:
            return skill_service.push(
                session,
                machine_id=pushers[index].machine.machine_id,
                user_id=pushers[index].user.user_id,
                name=name_for(index),
                origin=None,
                archive=skill_archive(name_for(index), files={"notes.md": content_for(index)}),
            )

    with ThreadPoolExecutor(max_workers=len(pushers)) as pool:
        return list(pool.map(push, range(len(pushers))))


def test_concurrent_pushes_of_different_skills_all_succeed(engine):
    session_factory = build_session_factory(engine)
    pushers = _joined(session_factory, WRITER_COUNT)

    pushed = _push_all_at_once(session_factory, pushers,
                               name_for=lambda index: f"skill-{index}",
                               content_for=lambda index: "same\n")

    assert sorted(result.name for result in pushed) == sorted(
        f"skill-{index}" for index in range(WRITER_COUNT))
    assert all(result.revision == 1 and result.created for result in pushed)


def test_concurrent_pushes_of_one_skill_all_succeed_with_distinct_revisions(engine):
    session_factory = build_session_factory(engine)
    with session_factory.begin() as session:
        pushers = machines_of_one_user(session, WRITER_COUNT)

    pushed = _push_all_at_once(session_factory, pushers,
                               name_for=lambda index: "wizard",
                               content_for=lambda index: f"from pusher {index}\n")

    assert sorted(result.revision for result in pushed) == list(range(1, WRITER_COUNT + 1))
    with session_factory() as session:
        stored = session.scalars(select(SkillVersion.revision)
                                 .order_by(SkillVersion.revision)).all()
    assert stored == list(range(1, WRITER_COUNT + 1))


def test_concurrent_joins_all_succeed_with_one_admin(engine):
    session_factory = build_session_factory(engine)
    at_the_start = threading.Barrier(WRITER_COUNT)

    def join(index):
        at_the_start.wait(timeout=10)
        with session_factory.begin() as session:
            return onboarding_service.join(session, f"joiner-{index}", "box", "LINUX")

    with ThreadPoolExecutor(max_workers=WRITER_COUNT) as pool:
        joined = list(pool.map(join, range(WRITER_COUNT)))

    assert sum(result.user.is_admin for result in joined) == 1
    with session_factory() as session:
        assert len(session.scalars(select(User)).all()) == WRITER_COUNT
