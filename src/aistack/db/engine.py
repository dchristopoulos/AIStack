import logging
import sqlite3
from time import perf_counter

from sqlalchemy import Engine, create_engine, event, make_url
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
        engine = create_engine(
            url,
            # Start a transaction even before the first write. In legacy mode, releasing a
            # savepoint opened before any DML can commit rows that outer rollback cannot undo.
            connect_args={"autocommit": False},
        )
        event.listen(engine, "connect", _apply_sqlite_pragmas)
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


def _apply_sqlite_pragmas(connection: sqlite3.Connection, _connection_record) -> None:
    """Apply WAL, busy timeout, and foreign keys outside the connection's transaction."""
    previous_autocommit = connection.autocommit
    connection.autocommit = True
    try:
        cursor = connection.cursor()
        try:
            # WAL lets readers proceed while another connection writes.
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_SECONDS * 1000}")
            # SQLite ignores foreign keys and cascades unless explicitly enabled.
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()
    finally:
        connection.autocommit = previous_autocommit
