"""What one person's dashboard, listing and sync cost, whoever else is on the server.

Each of these runs on every page load and every agent session, and on SQLite it holds the
write lock while it does. So none may read every revision or every file on the server, and
the dashboard may not issue more statements because a team has more members or groups.
"""

import json
import re

import pytest
from sqlalchemy import event

from aistack.db.engine import build_session_factory
from aistack.services import (
    dashboard_service,
    onboarding_service,
    skill_service,
    sync_service,
    team_service,
)
from tests.archives import local_digests, skill_archive
from tests.teams import make_team

# The tables that grow with everything anyone ever pushed.
_BIG = ("skill_version", "skill_file")


@pytest.fixture(name="session_factory")
def session_factory_fixture(portable_engine):
    return build_session_factory(portable_engine)


def _join(session_factory, username):
    with session_factory.begin() as session:
        return onboarding_service.join(session, username, "laptop", "LINUX")


def _push(session_factory, joined, name, content="one\n"):
    with session_factory.begin() as session:
        skill_service.push(session, machine_id=joined.machine.machine_id,
                           user_id=joined.user.user_id, name=name, origin=None,
                           archive=skill_archive(name, files={"notes.md": content}))


def _world(session_factory, focus, teams: int, members: int, prefix: str):
    """`teams` teams of `focus` and `members` others, each with two groups and a skill."""
    people = [_join(session_factory, f"{prefix}{index}") for index in range(members)]
    for number in range(teams):
        team = f"{prefix}team{number}"
        with session_factory.begin() as session:
            make_team(session, team, focus.user.user_id,
                      *(person.user.user_id for person in people))
            team_service.create_group(session, focus.user.user_id, team, "open")
            team_service.create_group(session, focus.user.user_id, team, "secret",
                                      private=True)
            for person in people[::2]:
                team_service.set_group_member(session, focus.user.user_id, team, "secret",
                                              person.user.username, True)
            team_service.new_invite_code(session, focus.user.user_id, team)
        _push(session_factory, people[0], f"{team}-skill")
        with session_factory.begin() as session:
            skill_service.share(session, people[0].user.user_id, f"{team}-skill", team)
    return people


@pytest.fixture(name="focus")
def focus_fixture(session_factory):
    """Someone with skills of their own, one taken from a team, on a server with others."""
    focus = _join(session_factory, "focus")
    for name in ("alpha", "beta"):
        _push(session_factory, focus, name)
        _push(session_factory, focus, name, "two\n")
    _world(session_factory, focus, teams=2, members=3, prefix="small")
    with session_factory.begin() as session:
        skill_service.get_skill(session, focus.machine.machine_id, focus.user.user_id,
                                "smallteam0-skill", "smallteam0")
    # Someone else's history, which none of focus's reads should walk.
    stranger = _join(session_factory, "stranger")
    for revision in range(5):
        _push(session_factory, stranger, "noise", f"{revision}\n")
    return focus


def _statements(session_factory, call) -> list[tuple[str, object]]:
    engine = session_factory.kw["bind"]
    seen = []

    def record(conn, cursor, statement, parameters, context, executemany):
        seen.append((statement, parameters))

    event.listen(engine, "before_cursor_execute", record)
    try:
        with session_factory.begin() as session:
            call(session)
    finally:
        event.remove(engine, "before_cursor_execute", record)
    return [(statement, parameters) for statement, parameters in seen
            if statement.lstrip().upper().startswith(("SELECT", "WITH"))]


def _full_scans(session_factory, statements) -> list[str]:
    """Every statement that reads a big table without an index condition, with its plan."""
    engine = session_factory.kw["bind"]
    found = []
    with engine.connect() as connection:
        if engine.dialect.name == "postgresql":
            # The test's tables are tiny, where a sequential scan is cheapest; with it priced
            # out the plan shows whether an index condition exists at all.
            connection.exec_driver_sql("SET enable_seqscan = off")
        for statement, parameters in statements:
            if engine.dialect.name == "sqlite":
                plan = [row[-1] for row in connection.exec_driver_sql(
                    "EXPLAIN QUERY PLAN " + statement, parameters)]
                bad = [line for line in plan
                       if re.match(rf"SCAN ({'|'.join(_BIG)})\b", line)]
            else:
                plan = connection.exec_driver_sql(
                    "EXPLAIN (FORMAT JSON) " + statement, parameters).scalar()
                plan = plan if isinstance(plan, list) else json.loads(plan)
                bad = list(_unindexed(plan[0]["Plan"]))
            if bad:
                found.append(f"{statement}\n  {bad}")
    return found


def _unindexed(node):
    if node.get("Relation Name") in _BIG and "Index Cond" not in node \
            and node["Node Type"] != "Bitmap Heap Scan":
        yield f"{node['Node Type']} on {node['Relation Name']}"
    for child in node.get("Plans", []):
        yield from _unindexed(child)


@pytest.mark.parametrize("read", ["state", "list_skills", "sync", "export"])
def test_one_persons_reads_walk_only_their_own_revisions(session_factory, focus, read):
    user_id, machine_id = focus.user.user_id, focus.machine.machine_id
    call = {
        "state": lambda session: dashboard_service.state(session, user_id),
        "list_skills": lambda session: skill_service.list_skills(session, user_id),
        "sync": lambda session: sync_service.sync(session, machine_id, user_id,
                                                  {"alpha": local_digests(
                                                      files={"notes.md": "one\n"})}),
        "export": lambda session: skill_service.export_library(session, user_id),
    }[read]

    assert _full_scans(session_factory, _statements(session_factory, call)) == []


def test_an_export_reads_the_library_in_two_statements_however_many_skills(session_factory,
                                                                          focus):
    statements = _statements(session_factory, lambda session: skill_service.export_library(
        session, focus.user.user_id))

    assert len(statements) == 2


def test_the_dashboard_costs_the_same_however_big_its_teams_are(session_factory, focus):
    def count() -> int:
        return len(_statements(session_factory,
                               lambda session: dashboard_service.state(session,
                                                                       focus.user.user_id)))

    small = count()
    _world(session_factory, focus, teams=3, members=25, prefix="big")

    assert count() == small
