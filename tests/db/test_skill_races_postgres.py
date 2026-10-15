"""A team skill or a Library skill changed from two places at once, on PostgreSQL.

The first call is held right after the read the second one invalidates, until the second has
finished. Where a lock makes the second wait for the first instead, the hold times out and
the two run one after the other, which is the point.
"""

import threading

import pytest
from sqlalchemy import select

from aistack.commons.exceptions import Conflict, NotFound
from aistack.db.engine import build_session_factory
from aistack.db.models.machine_skill import MachineSkill
from aistack.db.models.skill import Skill
from aistack.db.models.team import Team
from aistack.services import onboarding_service, skill_service, team_service, visibility
from tests.archives import skill_archive
from tests.teams import make_team

# Long enough for the second call to finish when nothing blocks it.
_WINDOW = 2


@pytest.fixture(name="session_factory")
def session_factory_fixture(postgres_engine):
    return build_session_factory(postgres_engine)


@pytest.fixture(name="people")
def people_fixture(session_factory):
    """ann, acme's admin, and bob, a member; ann shared 'wizard' into acme."""
    with session_factory.begin() as session:
        people = {name: onboarding_service.join(session, name, "laptop", "LINUX")
                  for name in ("ann", "bob")}
        make_team(session, "acme", people["ann"].user.user_id, people["bob"].user.user_id)
    _push(session_factory, people["ann"], "first\n")
    _push(session_factory, people["bob"], "bob's own\n")
    with session_factory.begin() as session:
        skill_service.share(session, people["ann"].user.user_id, "wizard", "acme")
    return people


def _push(session_factory, joined, content):
    with session_factory.begin() as session:
        return skill_service.push(session, machine_id=joined.machine.machine_id,
                                  user_id=joined.user.user_id, name="wizard", origin=None,
                                  archive=skill_archive(files={"notes.md": content}))


def _first_held_after(monkeypatch, module, function_name, first, second):
    """Run `first` and hold it after `function_name` returns, while `second` runs."""
    reached, finished = threading.Event(), threading.Event()
    original = getattr(module, function_name)

    def held(*args, **kwargs):
        result = original(*args, **kwargs)
        if threading.current_thread().name == "first" and not reached.is_set():
            reached.set()
            finished.wait(timeout=_WINDOW)
        return result

    monkeypatch.setattr(module, function_name, held)
    outcomes = {}

    def run(name, call):
        try:
            call()
            outcomes[name] = "ok"
        except (Conflict, NotFound) as error:
            outcomes[name] = f"{type(error).__name__}: {error}"
        finally:
            if name == "second":
                finished.set()

    one = threading.Thread(target=run, args=("first", first), name="first")
    one.start()
    assert reached.wait(timeout=10)
    two = threading.Thread(target=run, args=("second", second), name="second")
    two.start()
    for thread in (one, two):
        thread.join(timeout=30)
    return outcomes


def _in(session_factory, function, *args):
    def call():
        with session_factory.begin() as session:
            function(session, *args)
    return call


def _team_skill_exists(session_factory) -> bool:
    with session_factory() as session:
        return session.scalar(select(Skill).join(Team, Team.team_id == Skill.team_id)
                              .where(Team.name == "acme", Skill.name == "wizard")) is not None


def test_sharing_while_an_admin_removes_the_skill_runs_one_after_the_other(
        session_factory, people, monkeypatch):
    ann, bob = people["ann"].user.user_id, people["bob"].user.user_id

    outcomes = _first_held_after(
        monkeypatch, skill_service, "_stored_as_uploaded",
        _in(session_factory, skill_service.share, bob, "wizard", "acme"),
        _in(session_factory, team_service.remove_skill, ann, "acme", "wizard"))

    # The share landed, then the admin removed what it landed in: what one order gives.
    assert outcomes == {"first": "ok", "second": "ok"}
    assert not _team_skill_exists(session_factory)


def test_taking_a_skill_while_an_admin_removes_it_runs_one_after_the_other(
        session_factory, people, monkeypatch):
    ann, bob = people["ann"], people["bob"]

    # The take has read the team's files and not yet linked bob's copy to the team's skill.
    outcomes = _first_held_after(
        monkeypatch, skill_service, "_stored_as_uploaded",
        _in(session_factory, skill_service.get_skill, bob.machine.machine_id,
            bob.user.user_id, "wizard", "acme"),
        _in(session_factory, team_service.remove_skill, ann.user.user_id, "acme", "wizard"))

    assert outcomes == {"first": "ok", "second": "ok"}
    with session_factory() as session:
        mine = visibility.my_skill(session, bob.user.user_id, "wizard")
        # Taken, then the team's copy removed: bob keeps his, linked to nothing.
        assert mine.source_skill_id is None and mine.source_revision == 1


def test_moving_a_skill_while_an_admin_removes_it_runs_one_after_the_other(session_factory,
                                                                          people, monkeypatch):
    ann = people["ann"].user.user_id
    with session_factory.begin() as session:
        team_service.create_group(session, ann, "acme", "design")

    outcomes = _first_held_after(
        monkeypatch, team_service, "_skill",
        _in(session_factory, team_service.move_skill, ann, "acme", "wizard", "design"),
        _in(session_factory, team_service.remove_skill, ann, "acme", "wizard"))

    assert outcomes == {"first": "ok", "second": "ok"}
    assert not _team_skill_exists(session_factory)


def test_a_push_during_remove_from_library_ends_as_one_order_would(session_factory, people,
                                                                   monkeypatch):
    bob = people["bob"]

    outcomes = _first_held_after(
        monkeypatch, skill_service, "_store_revision",
        lambda: _push(session_factory, bob, "pushed meanwhile\n"),
        _in(session_factory, skill_service.remove_from_my_skills, bob.user.user_id, "wizard"))

    assert outcomes == {"first": "ok", "second": "ok"}
    with session_factory() as session:
        mine = visibility.my_skill(session, bob.user.user_id, "wizard")
        enabled = session.scalars(select(MachineSkill.enabled)
                                  .where(MachineSkill.skill_id == mine.skill_id)).all()
    # Removed, then pushed again: back in the Library and on the computer that pushed it.
    assert mine.archived is False and enabled == [True]
