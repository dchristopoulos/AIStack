"""Bring a database to the schema this release expects (ADR-0016)."""

import logging
from importlib import resources
from time import perf_counter

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, Engine, inspect, text

logger = logging.getLogger(__name__)

# The schema of every database created before migrations existed.
BASELINE_REVISION = "0001"

_VERSION_TABLE = "alembic_version"

# The key every AIStack process takes on PostgreSQL before migrating. Any fixed number works;
# this one is "AIST" in ASCII, so it reads as ours in pg_locks.
_MIGRATION_LOCK_KEY = 0x41495354


def migrate_schema(engine: Engine, script_location: str | None = None) -> None:
    """Apply every pending migration in one transaction, or none of them.

    A database made before migrations existed has the baseline's tables and no version row;
    it is marked as being at the baseline and upgraded from there.
    """
    started_at = perf_counter()
    config = Config()
    config.set_main_option(
        "script_location",
        script_location or str(resources.files("aistack.db").joinpath("migrations")),
    )

    scripts = ScriptDirectory.from_config(config)

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
                _refuse_a_newer_schema(connection, scripts)
                config.attributes["connection"] = connection
                if _predates_migrations(connection):
                    command.stamp(config, BASELINE_REVISION)
                command.upgrade(config, "head")
                if sqlite:
                    _require_intact_foreign_keys(connection)
        finally:
            if sqlite:
                connection.connection.driver_connection.execute("PRAGMA foreign_keys=ON")

    head = scripts.get_current_head()
    logger.info(f"Database schema migrated. Revision: '{head}'. "
                f"Elapsed: '{(perf_counter() - started_at) * 1000:.0f}ms'.")


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


def _refuse_a_newer_schema(connection: Connection, scripts: ScriptDirectory) -> None:
    """A release must not run against a schema a newer release made: it does not know it."""
    if _VERSION_TABLE not in inspect(connection).get_table_names():
        return
    current = connection.execute(text(f"SELECT version_num FROM {_VERSION_TABLE}")).scalar()
    known = {script.revision for script in scripts.walk_revisions()}
    if current is not None and current not in known:
        raise RuntimeError(
            f"This database is at schema '{current}', which a newer release of AIStack made, "
            f"and this release knows up to '{scripts.get_current_head()}'. Upgrade AIStack on "
            "this computer. Nothing was changed."
        )


def _predates_migrations(connection: Connection) -> bool:
    tables = set(inspect(connection).get_table_names())
    return bool(tables) and _VERSION_TABLE not in tables


def _require_intact_foreign_keys(connection: Connection) -> None:
    """With enforcement off for the rebuild, check before commit what it would have caught."""
    broken = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
    if broken:
        raise RuntimeError(
            f"The migration left {len(broken)} rows pointing at rows that no longer exist, "
            f"first in table '{broken[0][0]}'. Nothing was changed."
        )
