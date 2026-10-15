"""Copies of a SQLite database that restore, and the snapshot taken before every upgrade.

In WAL mode a database is up to three files, and a running or crashed server keeps recent
writes in `-wal` beside the main file. So a backup here is never a file copy: it is
`VACUUM INTO`, which writes one self-contained file from a consistent read, safe while the
server runs. A restore checks the copy, refuses while anything has the database open, and
replaces the file with nothing stale beside it. PostgreSQL has its own tools for all of this.
"""

import logging
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import Engine

logger = logging.getLogger(__name__)

# The files SQLite keeps beside a database in WAL mode. Left beside a restored file, the old
# `-wal` is replayed into it and the restore silently brings back what it was meant to undo.
SIDE_FILES = ("-wal", "-shm")

SNAPSHOT_PREFIX = "aistack-before-"
SNAPSHOTS_KEPT = 3

_POSTGRESQL_BACKUP = ("This server's database is PostgreSQL, which AIStack does not copy itself. "
                      "Back it up with `pg_dump --format=custom --file aistack.dump "
                      "\"$DATABASE_URL\"`, and restore with `pg_restore --clean --dbname "
                      "\"$DATABASE_URL\" aistack.dump` while the server is stopped.")


class BackupRefused(Exception):
    """A sentence for the operator: what was not done, and why."""


def database_file(engine: Engine) -> Path | None:
    """The SQLite file behind the engine, or None for PostgreSQL or an in-memory database."""
    if engine.dialect.name != "sqlite" or engine.url.database in (None, "", ":memory:"):
        return None
    return Path(engine.url.database)


def checkpoint(engine: Engine) -> None:
    """Move everything in `-wal` into the main file and empty it, so a stopped server leaves
    one file that holds all its data. A no-op on PostgreSQL."""
    if database_file(engine) is None:
        return
    connection = engine.raw_connection()
    try:
        # Through the driver: SQLAlchemy would open a transaction first, and a checkpoint
        # cannot finish inside one.
        connection.driver_connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        connection.close()


def back_up(engine: Engine, target: Path) -> Path:
    """Write a copy of the database to `target`, which must not exist yet."""
    live = database_file(engine)
    if live is None:
        raise BackupRefused(_POSTGRESQL_BACKUP)
    if not live.is_file():
        # Opening it would create an empty database, and back that up.
        raise BackupRefused(f"There is no database at {live}. Check DATABASE_URL.")
    target = target.resolve()
    if target.exists():
        raise BackupRefused(f"{target} already exists. Name a new file, so no backup is "
                            "replaced.")
    if not target.parent.is_dir():
        raise BackupRefused(f"The folder {target.parent} does not exist.")
    _vacuum_into(engine, target)
    return target


def restore(engine: Engine, backup: Path) -> Path | None:
    """Replace the database with `backup`. Returns where the replaced database was kept, or
    None when there was none. The engine must have no open connections: the caller builds it
    for this and nothing else."""
    live = database_file(engine)
    if live is None:
        raise BackupRefused(_POSTGRESQL_BACKUP)
    backup = backup.resolve()
    if not backup.is_file():
        raise BackupRefused(f"There is no backup at {backup}.")
    live = live.resolve()
    if backup == live:
        raise BackupRefused(f"{backup} is the database itself, not a backup of it.")

    if live.exists():
        _require_nobody_has_it_open(live)

    # Checked on a copy beside the database: the backup itself is never opened for writing,
    # and the copy is on the same filesystem as the database, so moving it in is atomic.
    staged = live.with_name(f"{live.name}.restoring")
    _remove_with_side_files(staged)
    shutil.copyfile(backup, staged)
    try:
        _require_aistack_database(staged, backup)
    except BackupRefused:
        _remove_with_side_files(staged)
        raise

    kept = None
    if live.exists():
        kept = live.with_name(f"{live.name}.replaced-{_now()}")
        live.rename(kept)
        for suffix in SIDE_FILES:
            Path(f"{live}{suffix}").unlink(missing_ok=True)
    staged.replace(live)
    return kept


def snapshot_before_migrating(engine: Engine, current: str, head: str) -> Path | None:
    """Keep a copy of a SQLite database from before it is migrated from `current` to `head`,
    beside it, and the newest few such copies. Runs before the migration's transaction,
    because the copy is a read and must not hold the write lock while it is written."""
    live = database_file(engine)
    if live is None:
        logger.warning(f"Migrating the PostgreSQL schema from '{current}' to '{head}'. AIStack "
                       "keeps no copy of a PostgreSQL database: the way back from this "
                       "upgrade is a pg_dump taken before it.")
        return None
    target = live.with_name(f"{SNAPSHOT_PREFIX}{head}-{_now()}.db")
    if target.exists():
        # Another process starting in the same second already took this one.
        return None
    try:
        _vacuum_into(engine, target)
    except sqlite3.Error as error:
        raise BackupRefused(f"Could not save a copy of the database before upgrading it, at "
                            f"{target}: {error}. Nothing was changed.") from error
    for old in sorted(live.parent.glob(f"{SNAPSHOT_PREFIX}*.db"),
                      key=lambda path: path.stat().st_mtime)[:-SNAPSHOTS_KEPT]:
        old.unlink(missing_ok=True)
    logger.warning(f"Saved a copy of the database at schema '{current}' before upgrading it, "
                   f"at {target}.")
    return target


def _vacuum_into(engine: Engine, target: Path) -> None:
    connection = engine.raw_connection()
    try:
        # A read: it waits for no writer and holds no write lock, and the file it writes is
        # one file whatever the source's journal mode.
        connection.driver_connection.execute("VACUUM INTO ?", (str(target),))
    finally:
        connection.close()


def _require_aistack_database(path: Path, named: Path) -> None:
    connection = sqlite3.connect(path, isolation_level=None)
    try:
        intact = connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        tables = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
        revision = (connection.execute("SELECT version_num FROM alembic_version").fetchone()
                    if "alembic_version" in tables else None)
        # Folds a backup made by SQLite's online backup, still in WAL mode, into one file.
        connection.execute("PRAGMA journal_mode=DELETE")
    except sqlite3.DatabaseError as error:
        raise BackupRefused(f"{named} is not a SQLite database ({error}). Nothing was "
                            "changed.") from error
    finally:
        connection.close()
    if not intact:
        raise BackupRefused(f"{named} is damaged: SQLite's integrity check fails on it. "
                            "Nothing was changed.")
    if revision is None:
        raise BackupRefused(f"{named} is not an AIStack database: it has no schema revision. "
                            "Nothing was changed.")


def _require_nobody_has_it_open(live: Path) -> None:
    """In WAL mode an exclusive lock is refused while any other connection is open, even an
    idle one, so this fails while a server or an agent's AIStack still runs on the file."""
    connection = sqlite3.connect(live, isolation_level=None, timeout=1)
    try:
        connection.execute("PRAGMA locking_mode=EXCLUSIVE")
        connection.execute("BEGIN EXCLUSIVE")
        # Holding it, fold the old `-wal` in, so the copy kept aside is complete.
        connection.execute("COMMIT")
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except sqlite3.OperationalError as error:
        raise BackupRefused(f"{live} is in use. Stop the server, or every coding agent using "
                            "this Library, then restore again. Nothing was changed.") from error
    finally:
        connection.close()


def _remove_with_side_files(path: Path) -> None:
    for suffix in ("", *SIDE_FILES):
        Path(f"{path}{suffix}").unlink(missing_ok=True)


def _now() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
