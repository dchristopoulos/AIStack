import logging
import sqlite3
from time import perf_counter

from sqlalchemy import Engine, create_engine, event, make_url
from sqlalchemy.orm import Session, sessionmaker

from aistack.db.models import Base

logger = logging.getLogger(__name__)

# Kept explicit because it is policy, not accident: it happens to match the sqlite3 default,
# and a future default change should not silently change how long a writer waits.
SQLITE_BUSY_TIMEOUT_SECONDS = 5


def build_engine(database_url: str) -> Engine:
    """Build the engine for whichever database `database_url` names.

    Callers never learn which dialect they got. The branch lives here so that every other
    module — services, tools, tests — is written once and runs identically on both (ADR-0002).
    """
    started_at = perf_counter()
    url = make_url(database_url)

    if url.get_backend_name() == "sqlite":
        engine = create_engine(
            url,
            # PEP 249 transaction control, handed to sqlite3 rather than left to the driver's
            # legacy implicit-BEGIN behaviour. Without it SAVEPOINT does not participate in the
            # outer transaction and ADR-0008's admin race loses the user and machine it rolls
            # back past.
            connect_args={"autocommit": False},
        )
        event.listen(engine, "connect", _apply_sqlite_pragmas)
    else:
        engine = create_engine(url)

    # render_as_string() masks the password; the raw URL must never reach a log line.
    logger.info(f"Database engine built. Backend: '{url.get_backend_name()}'. "
                f"URL: '{url.render_as_string(hide_password=True)}'. "
                f"Elapsed: '{(perf_counter() - started_at) * 1000:.0f}ms'.")
    return engine


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Build the factory every tool opens exactly one session from.

    expire_on_commit is off so a tool can still read the fields it just wrote after the
    `with session_factory.begin()` block commits — otherwise building the result would issue
    a refresh against a closed transaction.
    """
    return sessionmaker(bind=engine, expire_on_commit=False)


def create_schema(engine: Engine) -> None:
    """Create any missing tables and indexes.

    No Alembic in the MVP: the schema in docs/DESIGN.md §4 is settled and the SQLite file is
    disposable. This becomes a migration the first time a deployed schema has to change.
    """
    started_at = perf_counter()
    Base.metadata.create_all(engine)
    logger.info(f"Database schema created. Tables: '{len(Base.metadata.tables)}'. "
                f"Elapsed: '{(perf_counter() - started_at) * 1000:.0f}ms'.")


def _apply_sqlite_pragmas(connection: sqlite3.Connection, _connection_record) -> None:
    """Apply the per-connection SQLite policy: WAL, a busy timeout, and foreign keys.

    Pragmas are no-ops inside an open transaction, and `autocommit=False` means the connection
    arrives with one already started, so autocommit is flipped on for the duration.
    """
    previous_autocommit = connection.autocommit
    connection.autocommit = True
    try:
        cursor = connection.cursor()
        try:
            # WAL: one writer never blocks readers, which is what makes SQLite tolerable for a
            # small team. It is a database-level setting, re-applied per connection harmlessly.
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_SECONDS * 1000}")
            # SQLite parses ON DELETE CASCADE and then ignores it unless this is on, so a
            # missing pragma is a silent orphan-row bug, not an error.
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()
    finally:
        connection.autocommit = previous_autocommit
