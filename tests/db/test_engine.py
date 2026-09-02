import uuid

from sqlalchemy import Engine, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from aistack.db.models.user import User


def test_sqlite_connections_get_wal_busy_timeout_and_foreign_keys(engine: Engine):
    with engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"
        assert connection.exec_driver_sql("PRAGMA busy_timeout").scalar() == 5000
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1


def test_savepoint_rollback_preserves_the_outer_transaction(session_factory: sessionmaker[Session]):
    """ADR-0008's whole premise: the loser of the admin race keeps its user and machine.

    Without connect_args={"autocommit": False} the SAVEPOINT does not participate in the outer
    transaction, and rolling it back takes the row inserted before it along with it.
    """
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


def test_foreign_keys_are_enforced(engine: Engine):
    with engine.connect() as connection:
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


def test_the_os_column_is_a_varchar_with_a_check_constraint(engine: Engine):
    """docs/DESIGN.md §4: the OS enum is VARCHAR + CHECK, not a native enum.

    SQLAlchemy's Enum(native_enum=False) emits no CHECK unless create_constraint is set, so
    without this the column silently accepts any string on both dialects.
    """

    with engine.connect() as connection, connection.begin():
        connection.execute(text("INSERT INTO user (user_id, username, is_admin, created_on) "
                                "VALUES (:user_id, 'u', 0, '2026-01-01 00:00:00')"),
                           {"user_id": uuid.uuid4().hex})
        try:
            connection.execute(
                text("INSERT INTO machine (machine_id, user_id, name, os, token_hash, "
                     "created_on) SELECT :machine_id, user_id, 'm', 'SOLARIS', 'hash', "
                     "'2026-01-01 00:00:00' FROM user LIMIT 1"),
                {"machine_id": uuid.uuid4().hex},
            )
        except IntegrityError:
            return
    raise AssertionError("The database accepted an OS outside the enum.")
