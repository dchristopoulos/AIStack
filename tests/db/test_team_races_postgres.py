"""Two people changing one team at once, on PostgreSQL, where nothing serializes them but a lock.

Each test holds both transactions at the exact window the race needs: right after the check
that the other's write would change. With the team locked, the second never reaches that
window until the first commits, so its wait at the barrier times out and it carries on.
"""

import threading

import pytest
from sqlalchemy import func, select

from aistack.commons.exceptions import Conflict, NotFound, ValidationError
from aistack.db.engine import build_session_factory
from aistack.db.models.team import GroupMember, Team, TeamMember, TeamRole
from aistack.services import onboarding_service, team_service
from tests.teams import make_team

# Long enough for the other thread to reach the barrier when nothing blocks it.
_WINDOW = 2


@pytest.fixture(name="session_factory")
def session_factory_fixture(postgres_engine):
    return build_session_factory(postgres_engine)


@pytest.fixture(name="acme")
def acme_fixture(session_factory):
    """Team acme: admins ann and bob, member cid, and a private group 'secret' of ann's."""
    with session_factory.begin() as session:
        people = {name: onboarding_service.join(session, name, "laptop", "LINUX").user.user_id
                  for name in ("ann", "bob", "cid")}
        make_team(session, "acme", people["ann"], people["bob"], people["cid"])
        team_service.set_member(session, people["ann"], "acme", "bob", "ADMIN")
        team_service.create_group(session, people["ann"], "acme", "secret", private=True)
    return people


def _held_after(monkeypatch, function_name, threads):
    """Make `function_name` wait for the other thread once it returns, in `threads` only."""
    together = threading.Barrier(2)
    original = getattr(team_service, function_name)

    def held(*args, **kwargs):
        result = original(*args, **kwargs)
        if threading.current_thread().name in threads:
            try:
                together.wait(timeout=_WINDOW)
            except threading.BrokenBarrierError:
                pass  # The other is waiting on the team's lock: no race to set up.
        return result

    monkeypatch.setattr(team_service, function_name, held)


def _at_once(session_factory, **calls):
    outcomes = {}

    def run(name, call):
        try:
            with session_factory.begin() as session:
                call(session)
            outcomes[name] = "ok"
        except (Conflict, NotFound, ValidationError) as error:
            outcomes[name] = type(error).__name__

    threads = [threading.Thread(target=run, args=(name, call), name=name)
               for name, call in calls.items()]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    return outcomes


def _admins(session_factory) -> int:
    with session_factory() as session:
        return session.scalar(select(func.count()).select_from(TeamMember)
                              .join(Team, Team.team_id == TeamMember.team_id)
                              .where(Team.name == "acme", TeamMember.role == TeamRole.ADMIN))


@pytest.mark.parametrize("case", ["both-leave", "demote-each-other", "remove-while-demoted"])
def test_two_admins_acting_at_once_leave_the_team_an_admin(session_factory, acme, monkeypatch,
                                                           case):
    ann, bob = acme["ann"], acme["bob"]
    calls = {
        "both-leave": {
            "first": lambda s: team_service.leave_team(s, ann, "acme"),
            "second": lambda s: team_service.leave_team(s, bob, "acme"),
        },
        "demote-each-other": {
            "first": lambda s: team_service.set_member(s, ann, "acme", "bob", "MEMBER"),
            "second": lambda s: team_service.set_member(s, bob, "acme", "ann", "MEMBER"),
        },
        "remove-while-demoted": {
            "first": lambda s: team_service.remove_member(s, ann, "acme", "bob"),
            "second": lambda s: team_service.set_member(s, bob, "acme", "ann", "MEMBER"),
        },
    }[case]
    _held_after(monkeypatch, "_keep_an_admin", calls)

    outcomes = _at_once(session_factory, **calls)

    assert sorted(outcomes.values()) != ["ok", "ok"], outcomes
    assert "ok" in outcomes.values()
    assert _admins(session_factory) == 1


def test_a_member_removed_while_being_added_to_a_group_keeps_no_group(session_factory, acme,
                                                                      monkeypatch):
    ann, bob, cid = acme["ann"], acme["bob"], acme["cid"]
    # The add has found cid in the team and not yet written the group row.
    _held_after(monkeypatch, "_member", {"add", "remove"})

    _at_once(session_factory,
             add=lambda s: team_service.set_group_member(s, bob, "acme", "secret", "cid", True),
             remove=lambda s: team_service.remove_member(s, ann, "acme", "cid"))

    with session_factory() as session:
        assert session.scalars(select(GroupMember.user_id)
                               .where(GroupMember.user_id == cid)).all() == []
    # Invited back, they are in the team and in none of its groups.
    with session_factory.begin() as session:
        team_service.join_team(session, cid, team_service.new_invite_code(session, ann, "acme"))
    with session_factory() as session:
        assert [group.path for group in team_service.groups(session, cid, "acme")] == []


def test_one_person_joining_with_two_invites_at_once_joins_once(session_factory, acme,
                                                                monkeypatch):
    ann = acme["ann"]
    with session_factory.begin() as session:
        dan = onboarding_service.join(session, "dan", "laptop", "LINUX").user.user_id
        codes = [team_service.new_invite_code(session, ann, "acme") for _ in range(2)]
    # Each has read its invite pending and found dan not yet in the team.
    _held_after(monkeypatch, "invited_to", {"one", "two"})

    outcomes = _at_once(session_factory,
                        one=lambda s: team_service.join_team(s, dan, codes[0]),
                        two=lambda s: team_service.join_team(s, dan, codes[1]))

    assert outcomes == {"one": "ok", "two": "ok"}
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(TeamMember)
                              .where(TeamMember.user_id == dan)) == 2
