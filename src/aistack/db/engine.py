import logging
import sqlite3
from time import perf_counter

from sqlalchemy import Connection, Engine, create_engine, event, make_url
from sqlalchemy.orm import Session, sessionmaker

from aistack.db.models import Base

logger = logging.getLogger(__name__)

# Explicit policy, independent of sqlite3 defaults.
SQLITE_BUSY_TIMEOUT_SECONDS = 5


def build_engine(database_url: str) -> Engine:
    """Build an engine, keeping all database-specific setup here. See ADR-0002."""
    started_at = perf_counter()
    url = make_url(database_url)

    if url.get_backend_name() == "sqlite":
        engine = create_engine(url)
        # sqlite3 is told to open no transactions of its own, and SQLAlchemy opens them
        # explicitly with BEGIN IMMEDIATE. See ADR-0014.
        event.listen(engine, "connect", _configure_sqlite_connection)
        event.listen(engine, "begin", _begin_immediate)
    else:
        engine = create_engine(url)

    # Connection URLs can carry passwords in query parameters as well as userinfo.
    logger.info(f"Database engine built. Backend: '{url.get_backend_name()}'. "
                f"Elapsed: '{(perf_counter() - started_at) * 1000:.0f}ms'.")
    return engine


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Keep loaded fields readable after the tool's transaction commits and closes."""
    return sessionmaker(bind=engine, expire_on_commit=False)


def create_schema(engine: Engine) -> None:
    """Create missing tables and indexes; existing schemas require a future migration."""
    started_at = perf_counter()
    Base.metadata.create_all(engine)
    logger.info(f"Database schema created. Tables: '{len(Base.metadata.tables)}'. "
                f"Elapsed: '{(perf_counter() - started_at) * 1000:.0f}ms'.")


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
    Taking the lock up front means a second writer waits its turn instead.
    """
    connection.exec_driver_sql("BEGIN IMMEDIATE")
