import threading
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import select

from aistack.db.engine import build_session_factory
from aistack.db.models.skill import Skill
from aistack.db.models.skill_version import SkillVersion
from aistack.db.models.team import Team
from aistack.services import onboarding_service, skill_service
from tests.archives import skill_archive
from tests.teams import machines_of_one_user, make_team

# Three, because that is what three attempts guarantee: the unluckiest pusher loses to each of
# the other two once and wins on its third try. A fourth could lose three times, and that is
# the stampede the Conflict exists for, not something a test should produce by accident.
PUSHER_COUNT = 3


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


def test_concurrent_shares_never_share_a_revision_number(postgres_engine, monkeypatch, caplog):
    """Every member reads the same MAX(revision) of the team's skill before any of them writes.

    Several people sharing over one team skill is the one place different users contend for a
    revision: a push lands in the pusher's own skills. The barrier sits after the read and
    before the insert, which is the whole window. Without the unique constraint on
    (skill_id, revision) all three would store revision 2.
    """
    session_factory = build_session_factory(postgres_engine)
    with session_factory.begin() as session:
        members = [onboarding_service.join(session, f"pusher-{index}", "box", "LINUX")
                   for index in range(PUSHER_COUNT)]
        make_team(session, "acme", *(member.user.user_id for member in members))
    _push(session_factory, members[0], "revision one\n")
    with session_factory.begin() as session:
        skill_service.share(session, members[0].user.user_id, "wizard", "acme")
    for index, member in enumerate(members):
        _push(session_factory, member, f"from pusher {index}\n")

    at_the_insert = threading.Barrier(PUSHER_COUNT)
    store_revision = skill_service._store_revision

    def store_together(session, skill, uploaded, latest, user_id):
        at_the_insert.wait(timeout=30)
        return store_revision(session, skill, uploaded, latest, user_id)

    monkeypatch.setattr(skill_service, "_store_revision", store_together)

    def share(index):
        with session_factory.begin() as session:
            return skill_service.share(session, members[index].user.user_id, "wizard", "acme")

    with caplog.at_level("INFO"), ThreadPoolExecutor(max_workers=PUSHER_COUNT) as pool:
        pushed = list(pool.map(share, range(PUSHER_COUNT)))

    assert sorted(result.revision for result in pushed) == [2, 3, 4]
    # Each response names the revision it actually followed. The value read before the race
    # was "pusher-0" for all three; only the winner of revision 2 may still say so.
    pusher_of = {2: None, 3: None, 4: None}
    for index, result in enumerate(pushed):
        pusher_of[result.revision] = f"pusher-{index}"
    for result in pushed:
        expected = "pusher-0" if result.revision == 2 else pusher_of[result.revision - 1]
        assert result.previous_pushed_by == expected
    with session_factory() as session:
        stored = session.scalars(
            select(SkillVersion.revision)
            .join(Skill, Skill.skill_id == SkillVersion.skill_id)
            .join(Team, Team.team_id == Skill.team_id)
            .where(Team.name == "acme").order_by(SkillVersion.revision)).all()
    assert stored == [1, 2, 3, 4]
    # Two lost the race for 2, then one of those lost the race for 3.
    retries = [record for record in caplog.records
               if "Revision number taken concurrently" in record.getMessage()]
    assert len(retries) == 3


def test_two_first_pushes_of_one_name_become_one_skill(postgres_engine, monkeypatch):
    """Both look for the skill before either has created it."""
    session_factory = build_session_factory(postgres_engine)
    with session_factory.begin() as session:
        pushers = machines_of_one_user(session, 2)

    at_the_create = threading.Barrier(2)
    waited = threading.local()
    skill_in = skill_service._skill_in

    def look_together(session, team_id, name):
        found = skill_in(session, team_id, name)
        # Only the first look per pusher: the loser looks again once it has lost.
        if not getattr(waited, "done", False):
            waited.done = True
            at_the_create.wait(timeout=30)
        return found

    monkeypatch.setattr(skill_service, "_skill_in", look_together)

    with ThreadPoolExecutor(max_workers=2) as pool:
        pushed = list(pool.map(
            lambda index: _push(session_factory, pushers[index], f"from pusher {index}\n"),
            range(2)))

    assert sorted(result.created for result in pushed) == [False, True]
    assert sorted(result.revision for result in pushed) == [1, 2]
    with session_factory() as session:
        assert len(session.scalars(select(Skill)).all()) == 1
        assert len(session.scalars(select(SkillVersion)).all()) == 2
