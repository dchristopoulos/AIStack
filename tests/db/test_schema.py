import os
import pathlib
import shutil
import threading
import uuid
from datetime import datetime, timezone
from importlib import resources

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import MetaData, func, inspect, select, text
from sqlalchemy.exc import IntegrityError

import aistack.db
import aistack.db.schema
from aistack.db.engine import build_engine, build_session_factory
from aistack.db.models import Base
from aistack.db.models.harness import Harness
from aistack.db.models.machine import Machine
from aistack.db.models.machine_harness import MachineHarness
from aistack.db.models.machine_skill import MachineSkill
from aistack.db.models.skill_file import SkillFile
from aistack.db.models.team import Team, TeamKind, TeamMember, TeamRole
from aistack.db.models.user import User
from aistack.db.schema import BASELINE_REVISION, migrate_schema
from aistack.services import skill_service, sync_service
from tests.conftest import _drop_everything

MIGRATIONS = pathlib.Path(aistack.db.__file__).parent / "migrations"


@pytest.fixture(name="empty_engine", params=(
    ["sqlite", "postgresql"] if os.environ.get("TEST_DATABASE_URL") else ["sqlite"]
))
def empty_engine_fixture(request, sqlite_url):
    """A database with nothing in it, the way a new deployment finds one."""
    if request.param == "sqlite":
        engine = build_engine(sqlite_url)
        yield engine
        engine.dispose()
        return
    engine = request.getfixturevalue("postgres_engine")
    _drop_everything(engine)
    yield engine


def _revision(engine) -> str | None:
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


def _head() -> str:
    return ScriptDirectory(str(resources.files("aistack.db").joinpath("migrations"))
                           ).get_current_head()


def _tables(engine) -> set[str]:
    return set(inspect(engine).get_table_names())


def _migrations_up_to(tmp_path, revision: str) -> str:
    """The migrations as the release that ended at `revision` shipped them."""
    location = tmp_path / f"up-to-{revision}"
    shutil.copytree(MIGRATIONS, location, ignore=shutil.ignore_patterns("__pycache__"))
    for later in (location / "versions").glob("*.py"):
        if later.name[:4] > revision:
            later.unlink()
    return str(location)


def _a_database_the_mvp_wrote(engine, tmp_path) -> None:
    """The baseline schema with a row in every table, written as that release wrote them.

    Raw inserts, never the services: those describe today's schema, and this is yesterday's.
    """
    migrate_schema(engine, script_location=_migrations_up_to(tmp_path, BASELINE_REVISION))
    now = datetime.now(timezone.utc)
    ids = {name: uuid.uuid4() for name in ("user", "machine", "skill", "version")}
    rows = {
        "user": [dict(user_id=ids["user"], username="dimitris", is_admin=True, created_on=now)],
        "machine": [dict(machine_id=ids["machine"], user_id=ids["user"], name="macbook",
                         os="MACOS", token_hash="0" * 64, created_on=now)],
        "skill": [dict(skill_id=ids["skill"], name="wizard", description="Walks.", origin=None,
                       created_on=now, pushed_by=ids["user"])],
        "skill_version": [dict(skill_version_id=ids["version"], skill_id=ids["skill"],
                               revision=1, version=None, content_hash="1" * 64,
                               frontmatter_json={"name": "wizard"}, created_on=now,
                               pushed_by=ids["user"])],
        "skill_file": [dict(skill_file_id=uuid.uuid4(), skill_version_id=ids["version"],
                            path=path, content="kept\n", sha256="2" * 64, executable=False)
                       for path in ("SKILL.md", "notes.md")],
        "machine_skill": [dict(machine_skill_id=uuid.uuid4(), machine_id=ids["machine"],
                               skill_id=ids["skill"], enabled=True, created_on=now,
                               updated_on=now)],
    }
    metadata = MetaData()
    with engine.begin() as connection:
        metadata.reflect(connection)
        # A reflected SQLite column has forgotten it held a UUID: there it is 32 hex digits.
        as_stored = (lambda value: value.hex) if engine.dialect.name == "sqlite" else str
        for table, values in rows.items():
            connection.execute(metadata.tables[table].insert(), [
                {column: as_stored(value) if isinstance(value, uuid.UUID) else value
                 for column, value in row.items()}
                for row in values
            ])


def _file_count(engine) -> int:
    with engine.connect() as connection:
        return connection.scalar(select(func.count()).select_from(SkillFile))


def _with_extra_migration(tmp_path, body: str) -> str:
    """The real migrations plus one more, for testing what an upgrade does when it runs."""
    location = tmp_path / "migrations"
    shutil.copytree(MIGRATIONS, location, ignore=shutil.ignore_patterns("__pycache__"))
    head = max(path.name[:4] for path in (location / "versions").glob("*.py"))
    (location / "versions" / "9999_extra.py").write_text(
        "import sqlalchemy as sa\nfrom alembic import op\n\n"
        f"revision = '9999'\ndown_revision = '{head}'\n\n\ndef upgrade():\n{body}\n")
    return str(location)


def test_a_fresh_database_gets_exactly_the_schema_the_models_describe(empty_engine):
    migrate_schema(empty_engine)

    with empty_engine.connect() as connection:
        differences = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    assert differences == []
    assert _revision(empty_engine) is not None


def test_migrating_twice_changes_nothing(empty_engine, tmp_path):
    _a_database_the_mvp_wrote(empty_engine, tmp_path)
    migrate_schema(empty_engine)
    before = _revision(empty_engine)

    migrate_schema(empty_engine)

    assert _revision(empty_engine) == before
    # The skill's two files, and the copy of them in its user's own skills.
    assert _file_count(empty_engine) == 4


def test_a_database_from_before_migrations_is_adopted_with_its_data(empty_engine, tmp_path):
    """Every server deployed so far: the baseline's tables, and no record of a revision."""
    _a_database_the_mvp_wrote(empty_engine, tmp_path)
    with empty_engine.begin() as connection:
        connection.execute(text("DROP TABLE alembic_version"))

    migrate_schema(empty_engine)

    assert _revision(empty_engine) is not None
    # The skill's two files, and the copy of them in its user's own skills.
    assert _file_count(empty_engine) == 4
    with empty_engine.connect() as connection:
        assert connection.scalars(select(User.username)).all() == ["dimitris"]


def test_a_fresh_server_has_no_team_at_all(empty_engine):
    """`everyone` was made by migration 0002 and retired by 0005 while still empty."""
    migrate_schema(empty_engine)

    with empty_engine.connect() as connection:
        assert connection.scalars(select(Team.name)).all() == []


def test_an_upgraded_server_shows_everyone_what_it_showed_them_before(empty_engine, tmp_path):
    """Teams arrive (ADR-0015). What was shared stays shared, in what was the server's team and
    is an ordinary one since ADR-0019, and what a user's machine had installed becomes one of
    their own skills, history and all."""
    _a_database_the_mvp_wrote(empty_engine, tmp_path)

    migrate_schema(empty_engine)

    with build_session_factory(empty_engine).begin() as session:
        user_id = session.scalars(select(User.user_id)).one()
        machine_id = session.scalars(select(Machine.machine_id)).one()
        teams = dict(session.execute(select(Team.kind, Team.name)).all())
        roles = dict(session.execute(
            select(Team.kind, TeamMember.role)
            .join(Team, Team.team_id == TeamMember.team_id)
            .where(TeamMember.user_id == user_id)).all())
        listing = skill_service.list_skills(session, user_id)
        report = sync_service.sync(session, machine_id, user_id, {})

    assert teams == {TeamKind.SHARED: "everyone", TeamKind.PERSONAL: "dimitris"}
    # The server's admin is the admin of what was the server's team.
    assert roles == {TeamKind.SHARED: TeamRole.ADMIN, TeamKind.PERSONAL: TeamRole.ADMIN}
    assert [(skill.team, skill.name, skill.revision) for skill in listing] == [
        (None, "wizard", 1), ("everyone", "wizard", 1)]
    # Still enabled on the machine that had it, now from his own copy, which is level with
    # the shared one: nothing to install twice and no update on offer.
    assert [entry.name for entry in report.install] == ["wizard"]
    assert report.team_updates == () and report.backup == ()


def test_every_placement_made_before_harnesses_is_claude_codes(empty_engine, tmp_path):
    """Harnesses arrive (ADR-0018). Claude Code's folder was the only one AIStack installed
    into, so every decision a machine held is a decision about that folder."""
    _a_database_the_mvp_wrote(empty_engine, tmp_path)
    migrate_schema(empty_engine, script_location=_migrations_up_to(tmp_path, "0002"))
    assert _revision(empty_engine) == "0002"

    migrate_schema(empty_engine)

    with build_session_factory(empty_engine).begin() as session:
        decisions = session.execute(select(MachineSkill.harness, MachineSkill.enabled)).all()
        harnesses = session.scalars(select(MachineHarness.harness)).all()
        user_id = session.scalars(select(User.user_id)).one()
        machine_id = session.scalars(select(Machine.machine_id)).one()
        claude_code = sync_service.sync(session, machine_id, user_id, {})
        agents = sync_service.sync(session, machine_id, user_id, {}, "agents")

    assert decisions == [(Harness.CLAUDE_CODE, True)]
    # Filled in by each machine's next sync, not guessed at here.
    assert harnesses == []
    assert [entry.name for entry in claude_code.install] == ["wizard"]
    assert agents.install == () and agents.ask == ()


def test_the_database_refuses_a_harness_it_does_not_know(empty_engine, tmp_path):
    _a_database_the_mvp_wrote(empty_engine, tmp_path)
    migrate_schema(empty_engine)

    with pytest.raises(IntegrityError):
        with empty_engine.begin() as connection:
            connection.execute(text("UPDATE machine_skill SET harness = 'codex'"))


def test_a_migration_that_fails_leaves_the_database_as_it_was(empty_engine, tmp_path):
    _a_database_the_mvp_wrote(empty_engine, tmp_path)
    migrate_schema(empty_engine)
    before = _revision(empty_engine)
    broken = _with_extra_migration(tmp_path, (
        "    op.create_table('half_done', sa.Column('id', sa.Integer(), primary_key=True))\n"
        "    op.execute('DELETE FROM skill_file')\n"
        "    raise RuntimeError('step two of this migration failed')"))

    with pytest.raises(RuntimeError, match="step two"):
        migrate_schema(empty_engine, script_location=broken)

    assert "half_done" not in _tables(empty_engine)
    assert _revision(empty_engine) == before
    # The skill's two files, and the copy of them in its user's own skills.
    assert _file_count(empty_engine) == 4


def test_a_failed_first_start_leaves_an_empty_database_empty(empty_engine, tmp_path):
    broken = _with_extra_migration(tmp_path, "    raise RuntimeError('never finished')")

    with pytest.raises(RuntimeError, match="never finished"):
        migrate_schema(empty_engine, script_location=broken)

    assert _tables(empty_engine) == set()


def test_rebuilding_a_table_does_not_cascade_into_the_rows_that_reference_it(empty_engine,
                                                                            tmp_path):
    """SQLite alters a constraint by dropping the table and making it again. With foreign keys
    on, that drop deletes every row, and skill_file cascades from skill_version."""
    _a_database_the_mvp_wrote(empty_engine, tmp_path)
    migrate_schema(empty_engine)
    rebuild = _with_extra_migration(tmp_path, (
        "    with op.batch_alter_table('skill_version') as batch:\n"
        "        batch.alter_column('version', type_=sa.String(64))"))

    migrate_schema(empty_engine, script_location=rebuild)

    # The skill's two files, and the copy of them in its user's own skills.
    assert _file_count(empty_engine) == 4


def test_foreign_keys_are_enforced_again_after_a_migration(engine):
    with engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1


# --- one database, several processes (ADR-0020) --------------------------------------------

def test_a_database_upgraded_by_a_newer_release_refuses_this_one(empty_engine):
    """A computer that has not upgraded must not write to a schema it does not know."""
    migrate_schema(empty_engine)
    with empty_engine.begin() as connection:
        connection.execute(text("UPDATE alembic_version SET version_num = '9999'"))

    with pytest.raises(RuntimeError) as refusal:
        migrate_schema(empty_engine)

    assert "newer release of AIStack" in str(refusal.value)
    assert "'9999'" in str(refusal.value) and "Upgrade AIStack" in str(refusal.value)
    assert _revision(empty_engine) == "9999"


def test_two_processes_starting_at_once_migrate_the_database_once(empty_engine, monkeypatch):
    if empty_engine.dialect.name == "sqlite":
        pytest.skip("SQLite admits one writer at a time (ADR-0014), so two migrations never "
                    "overlap; the lock is for PostgreSQL")
    # Both are inside their transaction, about to take the lock, before either has migrated.
    both_began = threading.Barrier(2)
    take_lock = aistack.db.schema._hold_migration_lock

    def after_both_began(connection):
        both_began.wait(timeout=5)
        take_lock(connection)

    monkeypatch.setattr(aistack.db.schema, "_hold_migration_lock", after_both_began)
    failures = []

    def start():
        try:
            migrate_schema(empty_engine)
        except Exception as error:  # noqa: BLE001 - the assertion reports which one
            failures.append(error)

    threads = [threading.Thread(target=start) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert failures == []
    assert _revision(empty_engine) == _head()
