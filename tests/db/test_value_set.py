"""A release keeps working on rows a newer release wrote with values it does not know
(ADR-0031)."""

import uuid

import pytest
from sqlalchemy import text

from aistack.db.engine import build_session_factory
from aistack.services import dashboard_service, onboarding_service, skill_service, team_service
from tests.archives import skill_archive
from tests.teams import make_team


@pytest.fixture(name="session_factory")
def session_factory_fixture(portable_engine):
    return build_session_factory(portable_engine)


def _widen(connection, table: str, column: str, constraint: str, values: tuple[str, ...]):
    """What a newer release's migration would do: allow one more value."""
    allowed = ", ".join(f"'{value}'" for value in values)
    if connection.dialect.name == "postgresql":
        connection.exec_driver_sql(f'ALTER TABLE "{table}" DROP CONSTRAINT {constraint}')
        connection.exec_driver_sql(f'ALTER TABLE "{table}" ADD CONSTRAINT {constraint} '
                                   f"CHECK ({column} IN ({allowed}))")
    else:
        # SQLite cannot alter a CHECK; this connection stops enforcing it instead.
        connection.exec_driver_sql("PRAGMA ignore_check_constraints = ON")


def _as_stored(connection, value: uuid.UUID) -> str:
    return value.hex if connection.dialect.name == "sqlite" else str(value)


def test_values_a_newer_release_added_are_left_out_not_failed_on(portable_engine,
                                                                session_factory):
    with session_factory.begin() as session:
        maria = onboarding_service.join(session, "maria", "laptop", "LINUX")
        dimitris = onboarding_service.join(session, "dimitris", "desktop", "MACOS")
        user_id, machine_id = maria.user.user_id, maria.machine.machine_id
        skill_service.push(session, machine_id=machine_id, user_id=user_id, name="wizard",
                           origin=None, archive=skill_archive("wizard"))
        make_team(session, "acme", user_id, dimitris.user.user_id)

    with portable_engine.begin() as connection:
        _widen(connection, "machine_skill", "harness", "ck_machine_skill_harness",
               ("claude_code", "agents", "codex"))
        _widen(connection, "machine_harness", "harness", "ck_machine_harness_harness",
               ("claude_code", "agents", "codex"))
        _widen(connection, "machine", "os", "ck_machine_os",
               ("MACOS", "WINDOWS", "LINUX", "FREEBSD"))
        _widen(connection, "team_member", "role", "ck_team_member_role",
               ("ADMIN", "MEMBER", "OWNER"))
        skill_id = connection.exec_driver_sql("SELECT skill_id FROM skill WHERE name = 'wizard' "
                                              "ORDER BY created_on LIMIT 1").scalar()
        machine = _as_stored(connection, machine_id)
        connection.execute(text(
            "INSERT INTO machine_skill (machine_skill_id, machine_id, harness, skill_id, "
            "enabled, created_on, updated_on) VALUES "
            "(:id, :machine, 'codex', :skill, true, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"),
            {"id": _as_stored(connection, uuid.uuid4()), "machine": machine, "skill": skill_id})
        connection.execute(text(
            "INSERT INTO machine_harness (machine_harness_id, machine_id, harness, "
            "created_on, last_synced_on) VALUES (:id, :machine, 'codex', CURRENT_TIMESTAMP, "
            "CURRENT_TIMESTAMP)"),
            {"id": _as_stored(connection, uuid.uuid4()), "machine": machine})
        connection.execute(text(
            "INSERT INTO machine (machine_id, user_id, name, os, token_hash, created_on) "
            "VALUES (:id, :user, 'bsd-box', 'FREEBSD', :token, CURRENT_TIMESTAMP)"),
            {"id": _as_stored(connection, uuid.uuid4()),
             "user": _as_stored(connection, user_id), "token": "f" * 64})
        connection.execute(text("UPDATE team_member SET role = 'OWNER' WHERE user_id = :user"),
                           {"user": _as_stored(connection, dimitris.user.user_id)})

    with session_factory.begin() as session:
        state = dashboard_service.state(session, user_id)
        teams_of_dimitris = team_service.list_teams(session, dimitris.user.user_id)
        # His own membership row is read whole, and its role as no role at all.
        seen_by_dimitris = team_service.members(session, dimitris.user.user_id, "acme")

    assert [machine["name"] for machine in state["machines"]] == ["laptop"]
    assert state["machines"][0]["harnesses"] == ["claude_code"]
    [wizard] = state["skills"]
    assert [placement["harness"] for placement in wizard["placements"]] == ["claude_code"]
    [acme] = state["teams"]
    assert [member["username"] for member in acme["members"]] == ["maria"]
    # A role this release does not know grants nothing here, so the team is left out.
    assert teams_of_dimitris == []
    assert [member.username for member in seen_by_dimitris] == ["maria"]
