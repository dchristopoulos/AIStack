"""Bring a database to the schema this release expects (ADR-0016, ADR-0024)."""

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from importlib import resources
from time import perf_counter

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import (
    Connection,
    DateTime,
    Engine,
    Integer,
    String,
    column,
    delete,
    event,
    insert,
    inspect,
    table,
    text,
)
from sqlalchemy.orm import Session, SessionTransaction, sessionmaker

from aistack.commons.release import release

logger = logging.getLogger(__name__)

# The schema of every database created before migrations existed.
BASELINE_REVISION = "0001"
# The tables a database made before migrations existed always has.
_BASELINE_TABLES = {"user", "machine", "skill"}

_VERSION_TABLE = "alembic_version"
_COMPATIBILITY_TABLE = "schema_compatibility"


class ForeignDatabase(Exception):
    """The database holds another application's tables, and none of AIStack's."""

    def __init__(self) -> None:
        super().__init__("This database holds other tables and none of AIStack's, so it belongs "
                         "to something else. Nothing was changed. Point DATABASE_URL at an "
                         "empty database, or at AIStack's own.")


class NewerSchema(Exception):
    """A newer release upgraded the database in a way this release cannot run on (ADR-0024)."""

    def __init__(self, current: str, oldest: str, written_by: str | None, head: str):
        # "AIStack 0.2.0", or a plain description when the release did not record itself. A
        # build of the same version is a later commit: its image is tagged by that commit.
        if not written_by:
            self.upgraded_by = "a newer AIStack"
        elif written_by == release():
            self.upgraded_by = f"a newer build of AIStack {written_by}"
        else:
            self.upgraded_by = f"AIStack {written_by}"
        super().__init__(
            f"This database was upgraded by {self.upgraded_by} (schema '{current}'). This "
            f"release knows schemas up to '{head}', and the database now needs at least "
            f"'{oldest}'. Run that release or a newer one, or restore the backup from before "
            "the upgrade. Nothing was changed."
        )


# The key every AIStack process takes on PostgreSQL before migrating. Any fixed number works;
# this one is "AIST" in ASCII, so it reads as ours in pg_locks.
_MIGRATION_LOCK_KEY = 0x41495354


def _scripts(script_location: str | None = None) -> tuple[Config, ScriptDirectory]:
    config = Config()
    config.set_main_option(
        "script_location",
        script_location or str(resources.files("aistack.db").joinpath("migrations")),
    )
    return config, ScriptDirectory.from_config(config)


def migrate_schema(engine: Engine, script_location: str | None = None) -> None:
    """Apply every pending migration in one transaction, or none of them.

    A database made before migrations existed has the baseline's tables and no version row;
    it is marked as being at the baseline and upgraded from there.
    """
    started_at = perf_counter()
    config, scripts = _scripts(script_location)

    with engine.connect() as connection:
        # A batch migration rebuilds a table by dropping the old one. With foreign keys on,
        # SQLite treats that drop as deleting every row, and the delete cascades to the
        # tables that reference it. The pragma is ignored inside a transaction, so it is set
        # on the driver connection before SQLAlchemy begins one.
        sqlite = connection.dialect.name == "sqlite"
        if sqlite:
            connection.connection.driver_connection.execute("PRAGMA foreign_keys=OFF")
        try:
            with connection.begin():
                _hold_migration_lock(connection)
                if _runs_on_a_newer_schema(connection, scripts):
                    return
                config.attributes["connection"] = connection
                if _predates_migrations(connection):
                    command.stamp(config, BASELINE_REVISION)
                command.upgrade(config, "head")
                _record_compatibility(connection, scripts)
                if sqlite:
                    _require_intact_foreign_keys(connection)
        finally:
            if sqlite:
                connection.connection.driver_connection.execute("PRAGMA foreign_keys=ON")

    head = scripts.get_current_head()
    logger.info(f"Database schema migrated. Revision: '{head}'. "
                f"Elapsed: '{(perf_counter() - started_at) * 1000:.0f}ms'.")


def guard_schema(session_factory: sessionmaker[Session],
                 refused: Callable[[NewerSchema], Exception]) -> None:
    """Check, as each transaction begins, that the schema is still one this release runs on.

    `migrate_schema` checks once, at start. Another process on the same database (a second
    agent on a newer release, a replica already upgraded) can migrate it later, so every
    transaction first reads the version row, which costs one primary-key read. A schema
    this release may still run on is accepted once and remembered. One it may not makes the
    transaction raise `refused(error)` before its first statement, so nothing is written
    (ADR-0031).
    """
    _, scripts = _scripts()
    known = {script.revision for script in scripts.walk_revisions()}
    accepted = {scripts.get_current_head()}

    def check(_session: Session, transaction: SessionTransaction, connection: Connection):
        if transaction.nested:
            return
        current = connection.execute(text(f"SELECT version_num FROM {_VERSION_TABLE}")).scalar()
        if current in accepted:
            return
        try:
            if _runs_on_a_newer_schema(connection, scripts) or current in known:
                accepted.add(current)
        except NewerSchema as error:
            logger.error(str(error))
            raise refused(error) from None

    event.listen(session_factory, "after_begin", check)


def _hold_migration_lock(connection: Connection) -> None:
    """Make every other process that starts now wait until this one has migrated (ADR-0020).

    Several processes can share one PostgreSQL database: computers in local mode, or two
    replicas of a server. The lock is released when this transaction ends, and whoever takes
    it next finds the schema already current. SQLite needs none: its transaction already
    holds the only write lock (ADR-0014).
    """
    if connection.dialect.name == "postgresql":
        connection.execute(text("SELECT pg_advisory_xact_lock(:key)"),
                           {"key": _MIGRATION_LOCK_KEY})


def _runs_on_a_newer_schema(connection: Connection, scripts: ScriptDirectory) -> bool:
    """True when a newer release migrated the database and this one may still run on it.

    It may when the database says the oldest schema that can use it is one this release
    knows: everything since only added (ADR-0024). Otherwise it refuses, and nothing changes.
    """
    tables = set(inspect(connection).get_table_names())
    if _VERSION_TABLE not in tables:
        return False
    current = connection.execute(text(f"SELECT version_num FROM {_VERSION_TABLE}")).scalar()
    known = {script.revision for script in scripts.walk_revisions()}
    if current is None or current in known:
        return False

    recorded = None
    if _COMPATIBILITY_TABLE in tables:
        recorded = connection.execute(text(
            f"SELECT oldest_compatible_revision, written_by_release FROM {_COMPATIBILITY_TABLE}"
        )).one_or_none()
    oldest, written_by = recorded or (current, None)
    if oldest not in known:
        raise NewerSchema(current, oldest, written_by, scripts.get_current_head())
    logger.warning(f"Running on schema '{current}', which AIStack {written_by} made and which "
                   "still supports this release. Update AIStack here to use what it added.")
    return True


def _record_compatibility(connection: Connection, scripts: ScriptDirectory) -> None:
    """Write the oldest schema that can use this database: the newest breaking migration.

    A migration from before ADR-0024 declares nothing and counts as breaking, which is what it
    was: releases of that time refuse any schema newer than they know.
    """
    if _COMPATIBILITY_TABLE not in inspect(connection).get_table_names():
        return
    oldest = next(
        script.revision for script in scripts.walk_revisions()
        if not getattr(script.module, "older_releases_compatible", False)
    )
    # Declared here rather than imported: this runs against whatever schema the database has.
    compatibility = table(
        _COMPATIBILITY_TABLE,
        column("row_id", Integer),
        column("oldest_compatible_revision", String),
        column("written_by_release", String),
        column("updated_on", DateTime(timezone=True)),
    )
    connection.execute(delete(compatibility))
    connection.execute(insert(compatibility).values(
        row_id=1, oldest_compatible_revision=oldest, written_by_release=release(),
        updated_on=datetime.now(UTC)))


def _predates_migrations(connection: Connection) -> bool:
    """A database from before migrations: the baseline's tables and no version row. Any other
    non-empty database without the version row is somebody else's, and is refused untouched,
    because stamping it would run every migration over another application's data."""
    tables = set(inspect(connection).get_table_names())
    if not tables or _VERSION_TABLE in tables:
        return False
    if not _BASELINE_TABLES <= tables:
        raise ForeignDatabase()
    return True


def _require_intact_foreign_keys(connection: Connection) -> None:
    """With enforcement off for the rebuild, check before commit what it would have caught."""
    broken = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
    if broken:
        raise RuntimeError(
            f"The migration left {len(broken)} rows pointing at rows that no longer exist, "
            f"first in table '{broken[0][0]}'. Nothing was changed."
        )
