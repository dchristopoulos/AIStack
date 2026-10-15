"""What a query returns is the same on SQLite and on PostgreSQL (ADR-0002)."""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from aistack.db.engine import build_engine, build_session_factory
from aistack.db.models.team import Team, TeamKind
from aistack.db.models.timestamps import as_utc
from aistack.db.models.user import User
from aistack.db.schema import migrate_schema
from aistack.services import onboarding_service, team_service
from tests.db.test_schema import _migrations_up_to


@pytest.fixture(name="session_factory")
def session_factory_fixture(portable_engine):
    return build_session_factory(portable_engine)


def test_group_names_sort_by_their_bytes_whatever_the_databases_collation(portable_engine,
                                                                          session_factory):
    if portable_engine.dialect.name == "postgresql":
        # Managed databases and the official image sort text by a locale that ignores
        # punctuation at first; ICU's root locale is one, on any server.
        with portable_engine.begin() as connection:
            connection.exec_driver_sql(
                'ALTER TABLE team_group ALTER COLUMN path TYPE VARCHAR(255) COLLATE "und-x-icu"')
    names = ["ab", "a_b", "a.b", "a-b"]
    with session_factory.begin() as session:
        dimitris = onboarding_service.join(session, "dimitris", "laptop", "LINUX").user.user_id
        team_service.create_team(session, dimitris, "acme")
        for name in names:
            team_service.create_group(session, dimitris, "acme", name)
        listed = [group.path for group in team_service.groups(session, dimitris, "acme")]

    assert listed == sorted(names)


def test_a_user_has_one_library(session_factory):
    with session_factory.begin() as session:
        dimitris = onboarding_service.join(session, "dimitris", "laptop", "LINUX").user.user_id

    with pytest.raises(IntegrityError):
        with session_factory.begin() as session:
            session.add(Team(name="second-library", kind=TeamKind.PERSONAL,
                             created_by=dimitris))


def test_a_user_may_create_any_number_of_shared_teams(session_factory):
    with session_factory.begin() as session:
        dimitris = onboarding_service.join(session, "dimitris", "laptop", "LINUX").user.user_id
        for name in ("acme", "globex"):
            team_service.create_team(session, dimitris, name)
        created = session.scalars(select(Team.name).where(
            Team.created_by == dimitris, Team.kind == TeamKind.SHARED)).all()

    assert sorted(created) == ["acme", "globex"]


def test_stored_times_read_as_utc_whatever_the_databases_time_zone(portable_engine):
    if portable_engine.dialect.name == "postgresql":
        with portable_engine.begin() as connection:
            database = connection.exec_driver_sql("SELECT current_database()").scalar()
            connection.exec_driver_sql(
                f'ALTER DATABASE "{database}" SET timezone = \'Europe/Athens\'')
        # A connection takes the database's default when it opens.
        portable_engine.dispose()
    try:
        with build_session_factory(portable_engine).begin() as session:
            onboarding_service.join(session, "dimitris", "laptop", "LINUX")
            created_on = session.scalar(select(User.created_on))

        assert as_utc(created_on).utcoffset() == timedelta(0)
    finally:
        if portable_engine.dialect.name == "postgresql":
            with portable_engine.begin() as connection:
                connection.exec_driver_sql(f'ALTER DATABASE "{database}" RESET timezone')
            portable_engine.dispose()


def test_the_upgrade_refuses_a_database_with_two_libraries_for_one_user(tmp_path):
    engine = build_engine(f"sqlite:///{tmp_path / 'aistack.db'}")
    migrate_schema(engine, script_location=_migrations_up_to(tmp_path, "0011"))
    with build_session_factory(engine).begin() as session:
        dimitris = onboarding_service.join(session, "dimitris", "laptop", "LINUX").user.user_id
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO team (team_id, name, kind, created_by, created_on) "
            "VALUES (:id, 'second', 'PERSONAL', :user, CURRENT_TIMESTAMP)"),
            {"id": uuid.uuid4().hex, "user": dimitris.hex})

    with pytest.raises(RuntimeError, match="more than one personal team"):
        migrate_schema(engine)

    with engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT version_num FROM alembic_version"
                                          ).scalar() == "0011"
    engine.dispose()
