import uuid
from time import perf_counter

import pytest
from sqlalchemy import Engine, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from aistack.commons.exceptions import Busy
from aistack.db.models.user import User
from aistack.db.engine import build_engine


def test_sqlite_connections_get_wal_busy_timeout_and_foreign_keys(engine: Engine):
    with engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"
        assert connection.exec_driver_sql("PRAGMA busy_timeout").scalar() == 5000
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1


def test_sqlite_waits_for_a_busy_writer_before_failing_with_a_sentence(engine):
    with engine.connect() as writer, engine.connect() as contender:
        writer.execute(User.__table__.insert().values(username="holding-lock"))
        started = perf_counter()
        with pytest.raises(Busy, match="Make the same call again in a few seconds"):
            contender.execute(User.__table__.insert().values(username="waiting"))
        assert perf_counter() - started >= 4.5


def test_savepoint_rollback_preserves_the_outer_transaction(session_factory: sessionmaker[Session]):
    """A failed nested write does not discard the preceding outer write."""
    with session_factory.begin() as session:
        session.add(User(username="kept"))
        session.flush()

        try:
            with session.begin_nested():
                session.add(User(username="kept"))  # violates the unique username
                session.flush()
        except IntegrityError:
            pass

        session.add(User(username="also-kept"))

    with session_factory() as session:
        assert sorted(session.scalars(select(User.username))) == ["also-kept", "kept"]


def test_releasing_a_savepoint_does_not_escape_outer_rollback(session_factory):
    # No preceding INSERT: legacy sqlite3 otherwise starts a transaction and hides the bug.
    with pytest.raises(RuntimeError, match="abort outer"):
        with session_factory.begin() as session:
            with session.begin_nested():
                session.add(User(username="must-rollback"))
                session.flush()
            raise RuntimeError("abort outer")
    with session_factory() as session:
        assert session.scalars(select(User)).all() == []


@pytest.mark.parametrize("url", [
    "postgresql+psycopg://u:review-password@localhost/test",
    "postgresql+psycopg://u@localhost/test?password=review-password",
])
def test_database_credentials_are_absent_from_engine_logs(url, caplog):
    with caplog.at_level("INFO"):
        engine = build_engine(url)
    engine.dispose()
    assert "Database engine built" in caplog.text
    assert "review-password" not in caplog.text
    assert url not in caplog.text


def test_foreign_keys_are_enforced(portable_engine: Engine):
    with portable_engine.connect() as connection:
        with connection.begin():
            try:
                connection.execute(
                    text("INSERT INTO machine (machine_id, user_id, name, os, token_hash, "
                         "created_on) VALUES (:machine_id, :user_id, 'orphan', 'LINUX', "
                         "'deadbeef', '2026-01-01 00:00:00')"),
                    {"machine_id": uuid.uuid4().hex, "user_id": uuid.uuid4().hex},
                )
            except IntegrityError:
                return
    raise AssertionError("A machine referencing a missing user was accepted.")


def test_the_os_column_is_a_varchar_with_a_check_constraint(portable_engine: Engine):
    """docs/DESIGN.md §4: the OS enum is VARCHAR + CHECK, not a native enum.

    SQLAlchemy's Enum(native_enum=False) emits no CHECK unless create_constraint is set, so
    without this the column silently accepts any string on both dialects.
    """

    with portable_engine.connect() as connection, connection.begin():
        connection.execute(text('INSERT INTO "user" (user_id, username, is_admin, created_on) '
                                "VALUES (:user_id, 'u', false, '2026-01-01 00:00:00')"),
                           {"user_id": uuid.uuid4().hex})
        try:
            connection.execute(
                text("INSERT INTO machine (machine_id, user_id, name, os, token_hash, "
                     "created_on) SELECT :machine_id, user_id, 'm', 'SOLARIS', 'hash', "
                     "'2026-01-01 00:00:00' FROM \"user\" LIMIT 1"),
                {"machine_id": uuid.uuid4().hex},
            )
        except IntegrityError:
            return
    raise AssertionError("The database accepted an OS outside the enum.")



def test_a_postgres_connection_closed_while_pooled_is_replaced_not_used(postgres_engine):
    """A managed database or pooler closes idle connections; the next request must not fail."""
    # Two connections in the pool, so the one that closes the other is not itself the victim.
    with postgres_engine.connect() as victim, postgres_engine.connect() as killer:
        pid = victim.exec_driver_sql("SELECT pg_backend_pid()").scalar()
        victim.rollback()
        victim.close()
        killer.exec_driver_sql(f"SELECT pg_terminate_backend({pid})")

    # Both pooled connections are handed out again; the closed one must have been replaced.
    with postgres_engine.connect() as first, postgres_engine.connect() as second:
        pids = {connection.exec_driver_sql("SELECT pg_backend_pid()").scalar()
                for connection in (first, second)}
    assert pid not in pids


@pytest.mark.parametrize("pasted", ["postgresql://u:p@db.example/aistack",
                                    "postgres://u:p@db.example/aistack"])
def test_a_providers_postgres_address_uses_the_shipped_driver(pasted):
    """Neon and Supabase hand out postgresql://, which SQLAlchemy would read as psycopg2."""
    engine = build_engine(pasted)
    try:
        assert engine.url.drivername == "postgresql+psycopg"
    finally:
        engine.dispose()
