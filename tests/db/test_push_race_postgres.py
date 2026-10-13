import threading
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import select

from aistack.db.engine import build_session_factory
from aistack.db.models.skill import Skill
from aistack.db.models.skill_version import SkillVersion
from aistack.services import onboarding_service, skill_service
from tests.archives import skill_archive

# Three, because that is what three attempts guarantee: the unluckiest pusher loses to each of
# the other two once and wins on its third try. A fourth could lose three times, and that is
# the stampede the Conflict exists for, not something a test should produce by accident.
PUSHER_COUNT = 3


def _joined(session_factory, count):
    with session_factory.begin() as session:
        return [onboarding_service.join(session, f"pusher-{index}", "box", "LINUX")
                for index in range(count)]


def _push(session_factory, joined, content):
    with session_factory.begin() as session:
        return skill_service.push(
            session,
            machine_id=joined.machine.machine_id,
            user_id=joined.user.user_id,
            name="wizard",
            origin=None,
            archive=skill_archive(files={"notes.md": content}),
        )


def test_concurrent_pushes_never_share_a_revision_number(postgres_engine, monkeypatch, caplog):
    """Every pusher reads the same MAX(revision) before any of them writes.

    The barrier sits after the read and before the insert, which is the whole window. Without
    the unique constraint on (skill_id, revision) all three would store revision 2.
    """
    session_factory = build_session_factory(postgres_engine)
    pushers = _joined(session_factory, PUSHER_COUNT)
    _push(session_factory, pushers[0], "revision one\n")

    at_the_insert = threading.Barrier(PUSHER_COUNT)
    store_revision = skill_service._store_revision

    def store_together(session, skill, uploaded, latest, user_id):
        at_the_insert.wait(timeout=30)
        return store_revision(session, skill, uploaded, latest, user_id)

    monkeypatch.setattr(skill_service, "_store_revision", store_together)

    with caplog.at_level("INFO"), ThreadPoolExecutor(max_workers=PUSHER_COUNT) as pool:
        pushed = list(pool.map(
            lambda index: _push(session_factory, pushers[index], f"from pusher {index}\n"),
            range(PUSHER_COUNT)))

    assert sorted(result.revision for result in pushed) == [2, 3, 4]
    with session_factory() as session:
        stored = session.scalars(select(SkillVersion.revision)
                                 .order_by(SkillVersion.revision)).all()
    assert stored == [1, 2, 3, 4]
    # Two lost the race for 2, then one of those lost the race for 3.
    retries = [record for record in caplog.records
               if "Revision number taken concurrently" in record.getMessage()]
    assert len(retries) == 3


def test_two_first_pushes_of_one_name_become_one_skill(postgres_engine, monkeypatch):
    """Both look for the skill before either has created it."""
    session_factory = build_session_factory(postgres_engine)
    pushers = _joined(session_factory, 2)

    at_the_create = threading.Barrier(2)
    waited = threading.local()
    skill_named = skill_service._skill_named

    def look_together(session, name):
        found = skill_named(session, name)
        # Only the first look per pusher: the loser looks again once it has lost.
        if not getattr(waited, "done", False):
            waited.done = True
            at_the_create.wait(timeout=30)
        return found

    monkeypatch.setattr(skill_service, "_skill_named", look_together)

    with ThreadPoolExecutor(max_workers=2) as pool:
        pushed = list(pool.map(
            lambda index: _push(session_factory, pushers[index], f"from pusher {index}\n"),
            range(2)))

    assert sorted(result.created for result in pushed) == [False, True]
    assert sorted(result.revision for result in pushed) == [1, 2]
    with session_factory() as session:
        assert len(session.scalars(select(Skill)).all()) == 1
        assert len(session.scalars(select(SkillVersion)).all()) == 2
