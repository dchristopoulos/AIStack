import os
import signal
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest
from sqlalchemy import select

from aistack.db import backup
from aistack.db.backup import BackupRefused
from aistack.db.engine import build_engine, build_session_factory
from aistack.db.models.user import User
from aistack.db.schema import migrate_schema
from tests.db.test_schema import _head, _migrations_up_to

INVITE_CODE = "backup-test-invite-code-not-a-secret"


@pytest.fixture(name="database")
def database_fixture(tmp_path):
    """A migrated SQLite database with one user in it, and its file."""
    path = tmp_path / "aistack.db"
    engine = build_engine(f"sqlite:///{path}")
    migrate_schema(engine)
    _add_user(engine, "before-backup")
    yield engine, path
    engine.dispose()


def _add_user(engine, username):
    with build_session_factory(engine).begin() as session:
        session.add(User(username=username))


def _usernames(path):
    engine = build_engine(f"sqlite:///{path}")
    try:
        with engine.connect() as connection:
            return sorted(connection.scalars(select(User.username)))
    finally:
        engine.dispose()


def test_a_restore_brings_back_the_backup_and_nothing_written_after_it(database, tmp_path):
    engine, path = database
    # Taken while the server's connection is open, as an operator takes one.
    copy = backup.back_up(engine, tmp_path / "backup.db")
    _add_user(engine, "after-backup")
    # A server stopped without closing: the change is in -wal beside the file.
    assert Path(f"{path}-wal").stat().st_size > 0
    engine.dispose()

    kept = backup.restore(build_engine(f"sqlite:///{path}"), copy)

    assert _usernames(path) == ["before-backup"]
    assert _usernames(kept) == ["after-backup", "before-backup"]
    assert sorted(item.name for item in tmp_path.iterdir() if item.name.startswith(path.name)
                  ) == [path.name, kept.name]


def test_a_backup_never_replaces_a_file(database, tmp_path):
    engine, _ = database
    (tmp_path / "taken.db").write_text("an older backup")

    with pytest.raises(BackupRefused, match="already exists"):
        backup.back_up(engine, tmp_path / "taken.db")
    assert (tmp_path / "taken.db").read_text() == "an older backup"


def test_a_backup_of_a_database_that_is_not_there_creates_nothing(tmp_path):
    missing = tmp_path / "typo.db"
    with pytest.raises(BackupRefused, match="There is no database"):
        backup.back_up(build_engine(f"sqlite:///{missing}"), tmp_path / "copy.db")
    assert not missing.exists() and not (tmp_path / "copy.db").exists()


def test_a_restore_refuses_while_anything_has_the_database_open(database, tmp_path):
    engine, path = database
    copy = backup.back_up(engine, tmp_path / "backup.db")
    _add_user(engine, "after-backup")  # the server's connection stays in the pool

    with pytest.raises(BackupRefused, match="in use"):
        backup.restore(build_engine(f"sqlite:///{path}"), copy)
    engine.dispose()
    assert _usernames(path) == ["after-backup", "before-backup"]
    assert not Path(f"{path}.restoring").exists()


@pytest.mark.parametrize("contents", [
    "not a database",
    "a SQLite file that is not AIStack's",
])
def test_a_restore_refuses_what_is_not_an_aistack_backup(database, tmp_path, contents):
    engine, path = database
    engine.dispose()
    source = tmp_path / "source.db"
    if contents == "not a database":
        source.write_text("not a database")
    else:
        with sqlite3.connect(source) as other:
            other.execute("CREATE TABLE notes (body TEXT)")

    with pytest.raises(BackupRefused, match="Nothing was changed"):
        backup.restore(build_engine(f"sqlite:///{path}"), source)
    assert _usernames(path) == ["before-backup"]
    assert not Path(f"{path}.restoring").exists()


def test_postgresql_is_pointed_at_its_own_tools():
    # Building an engine connects to nothing, so no PostgreSQL is needed for this.
    engine = build_engine("postgresql+psycopg://aistack@db.invalid/aistack")
    with pytest.raises(BackupRefused, match="pg_dump"):
        backup.back_up(engine, Path("unused.db"))
    with pytest.raises(BackupRefused, match="pg_restore"):
        backup.restore(engine, Path("unused.db"))


def _snapshots(folder):
    return sorted(folder.glob(f"{backup.SNAPSHOT_PREFIX}*.db"))


def test_an_upgrade_keeps_a_copy_at_the_schema_it_upgraded_from(tmp_path):
    path = tmp_path / "aistack.db"
    engine = build_engine(f"sqlite:///{path}")
    migrate_schema(engine, _migrations_up_to(tmp_path, "0005"))
    assert _snapshots(tmp_path) == []  # a new database has nothing to go back to

    migrate_schema(engine)
    migrate_schema(engine)  # already at head: no second copy
    engine.dispose()

    [snapshot] = _snapshots(tmp_path)
    assert f"-{_head()}-" in snapshot.name
    with sqlite3.connect(snapshot) as copy:
        assert copy.execute("SELECT version_num FROM alembic_version").fetchone() == ("0005",)


def test_only_the_newest_copies_are_kept(tmp_path):
    for age in range(5):
        old = tmp_path / f"{backup.SNAPSHOT_PREFIX}000{age}-2026010{age}T000000Z.db"
        old.write_text("old")
        os.utime(old, (age, age))
    path = tmp_path / "aistack.db"
    engine = build_engine(f"sqlite:///{path}")
    migrate_schema(engine, _migrations_up_to(tmp_path, "0005"))
    migrate_schema(engine)
    engine.dispose()

    kept = _snapshots(tmp_path)
    assert len(kept) == backup.SNAPSHOTS_KEPT
    assert any(f"-{_head()}-" in snapshot.name for snapshot in kept)
    assert not (tmp_path / f"{backup.SNAPSHOT_PREFIX}0000-20260100T000000Z.db").exists()


def _free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.mark.skipif(sys.platform == "win32", reason="SIGTERM ends a Windows process at once")
def test_a_server_stopped_like_docker_stop_leaves_one_file_with_everything(tmp_path):
    path = tmp_path / "aistack.db"
    port = _free_port()
    environment = {**os.environ, "DATABASE_URL": f"sqlite:///{path}",
                   "AISTACK_INVITE_CODE": INVITE_CODE, "AISTACK_HOST": "127.0.0.1",
                   "AISTACK_PORT": str(port)}
    server = subprocess.Popen([sys.executable, "-m", "aistack.bootstrap", "serve"],
                              env=environment, cwd=tmp_path,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1)
                break
            except OSError:
                time.sleep(0.1)
        engine = build_engine(f"sqlite:///{path}")
        _add_user(engine, "written-while-running")
        engine.dispose()
    finally:
        server.send_signal(signal.SIGTERM)
        server.wait(timeout=30)

    assert [item.name for item in tmp_path.iterdir() if item.name.startswith("aistack")] == [
        "aistack.db"]
    with sqlite3.connect(path) as alone:
        assert alone.execute("SELECT username FROM \"user\"").fetchall() == [
            ("written-while-running",)]


def test_the_commands_need_only_the_database_address(database, tmp_path):
    engine, path = database
    engine.dispose()
    environment = {name: value for name, value in os.environ.items()
                   if name not in ("AISTACK_INVITE_CODE", "DATABASE_URL")}
    environment["DATABASE_URL"] = f"sqlite:///{path}"

    def aistack(*arguments):
        return subprocess.run([sys.executable, "-m", "aistack.bootstrap", *arguments],
                              env=environment, cwd=tmp_path, capture_output=True, text=True)

    taken = aistack("backup", str(tmp_path / "copy.db"))
    assert taken.returncode == 0, taken.stderr
    restored = aistack("restore", str(tmp_path / "copy.db"))
    assert restored.returncode == 0, restored.stderr
    assert "The one it replaced is kept at" in restored.stdout
    refused = aistack("restore", str(tmp_path / "missing.db"))
    assert refused.returncode == 1 and "There is no backup at" in refused.stderr
