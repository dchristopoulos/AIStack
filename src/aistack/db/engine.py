import logging
import sqlite3
from time import perf_counter

from sqlalchemy import Connection, Engine, create_engine, event, make_url
from sqlalchemy.engine import ExceptionContext
from sqlalchemy.orm import Session, sessionmaker

from aistack.commons.exceptions import Busy

logger = logging.getLogger(__name__)

# Explicit policy, independent of sqlite3 defaults.
SQLITE_BUSY_TIMEOUT_SECONDS = 5

# Marks a connection whose transaction only reads (ADR-0030).
_READ_ONLY = "aistack_read_only"

_BUSY = ("The server is busy right now and could not finish this in time. Nothing was "
         "changed. Make the same call again in a few seconds.")


def build_engine(database_url: str) -> Engine:
    """Build an engine, keeping all database-specific setup here. See ADR-0002."""
    started_at = perf_counter()
    url = make_url(database_url)
    # Neon and Supabase hand out postgresql:// addresses, which SQLAlchemy reads as psycopg2.
    # The driver AIStack ships is psycopg 3, so a pasted address is pointed at it.
    if url.drivername in ("postgresql", "postgres"):
        url = url.set(drivername="postgresql+psycopg")

    if url.get_backend_name() == "sqlite":
        engine = create_engine(url)
        # sqlite3 is told to open no transactions of its own, and SQLAlchemy opens them
        # explicitly with BEGIN IMMEDIATE. See ADR-0014.
        event.listen(engine, "connect", _configure_sqlite_connection)
        event.listen(engine, "begin", _begin_immediate)
        event.listen(engine, "commit", _end_read_only)
        event.listen(engine, "rollback", _end_read_only)
    else:
        # Managed databases and poolers close idle connections (Neon's scale to zero, a
        # restart, a pooler's idle timeout). Checking a connection before handing it out
        # replaces a closed one instead of failing the first request after a quiet spell.
        engine = create_engine(url, pool_pre_ping=True)

    event.listen(engine, "handle_error", _busy_as_a_sentence)

    # Connection URLs can carry passwords in query parameters as well as userinfo.
    logger.info(f"Database engine built. Backend: '{url.get_backend_name()}'. "
                f"Elapsed: '{(perf_counter() - started_at) * 1000:.0f}ms'.")
    return engine


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Keep loaded fields readable after the tool's transaction commits and closes."""
    return sessionmaker(bind=engine, expire_on_commit=False)


def build_read_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Sessions for a request that only reads, which refuse to write (ADR-0030).

    On SQLite they begin deferred, so in WAL mode they neither wait for the writer nor make
    it wait. PostgreSQL's readers never waited; there the transaction is read-only too.
    """
    options = {_READ_ONLY: True}
    if engine.dialect.name == "postgresql":
        options["postgresql_readonly"] = True
    return build_session_factory(engine.execution_options(**options))


def _configure_sqlite_connection(connection: sqlite3.Connection, _connection_record) -> None:
    """Hand transaction control to SQLAlchemy, then apply WAL, busy timeout, and foreign keys."""
    # None means the driver never emits BEGIN itself. Its own implicit BEGIN is deferred, and
    # it starts before the first write rather than before the first statement, which is also
    # what breaks savepoints (ADR-0008).
    connection.isolation_level = None

    cursor = connection.cursor()
    try:
        # WAL lets readers proceed while another connection writes.
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_SECONDS * 1000}")
        # SQLite ignores foreign keys and cascades unless explicitly enabled.
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


def _begin_immediate(connection: Connection) -> None:
    """Take the write lock when the transaction starts, not when it first writes.

    A deferred transaction that reads and then writes is refused outright if anyone else
    committed in between: its snapshot is stale, and the busy timeout does not apply to that.
    Taking the lock up front means a second writer waits its turn instead. A transaction that
    only reads has nothing to wait for, so it begins deferred and may not write (ADR-0030).
    """
    if connection.get_execution_options().get(_READ_ONLY):
        connection.exec_driver_sql("BEGIN")
        connection.exec_driver_sql("PRAGMA query_only = ON")
        return
    connection.exec_driver_sql("BEGIN IMMEDIATE")


def _end_read_only(connection: Connection) -> None:
    """The pool hands this connection to writers next, so it may write again."""
    if connection.get_execution_options().get(_READ_ONLY):
        connection.exec_driver_sql("PRAGMA query_only = OFF")


def _busy_as_a_sentence(context: ExceptionContext) -> BaseException | None:
    """A lock that was not granted in time is a reason to retry, said as one.

    SQLite's busy timeout ran out ("database is locked"), or PostgreSQL chose this transaction
    to end a deadlock or a serialization conflict. Either way nothing was written.
    """
    original = context.original_exception
    message = str(original).lower()
    if context.engine is not None and context.engine.dialect.name == "sqlite":
        busy = "database is locked" in message or "database is busy" in message
    else:
        busy = getattr(original, "sqlstate", None) in ("40001", "40P01")
    return Busy(_BUSY) if busy else None
