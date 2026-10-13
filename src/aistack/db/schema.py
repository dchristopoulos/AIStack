"""Bring a database to the schema this release expects (ADR-0016)."""

import logging
from importlib import resources
from time import perf_counter

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, Engine, inspect

logger = logging.getLogger(__name__)

# The schema of every database created before migrations existed.
BASELINE_REVISION = "0001"

_VERSION_TABLE = "alembic_version"


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
                config.attributes["connection"] = connection
                if _predates_migrations(connection):
                    command.stamp(config, BASELINE_REVISION)
                command.upgrade(config, "head")
                if sqlite:
                    _require_intact_foreign_keys(connection)
        finally:
            if sqlite:
                connection.connection.driver_connection.execute("PRAGMA foreign_keys=ON")

    head = ScriptDirectory.from_config(config).get_current_head()
    logger.info(f"Database schema migrated. Revision: '{head}'. "
                f"Elapsed: '{(perf_counter() - started_at) * 1000:.0f}ms'.")


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
