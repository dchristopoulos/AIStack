import os
import pathlib
import shutil

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import func, inspect, select, text

import aistack.db
from aistack.db.engine import build_engine, build_session_factory
from aistack.db.models import Base
from aistack.db.models.skill_file import SkillFile
from aistack.db.models.user import User
from aistack.db.schema import BASELINE_REVISION, migrate_schema
from aistack.services import onboarding_service, skill_service
from tests.archives import skill_archive
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


def _tables(engine) -> set[str]:
    return set(inspect(engine).get_table_names())


def _seed(engine) -> None:
    """One user, one machine, one pushed skill: a row in every table."""
    with build_session_factory(engine).begin() as session:
        joined = onboarding_service.join(session, "dimitris", "macbook", "MACOS")
        skill_service.push(session, machine_id=joined.machine.machine_id,
                           user_id=joined.user.user_id, name="wizard", origin=None,
                           archive=skill_archive(files={"notes.md": "kept\n"}))


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


def test_migrating_twice_changes_nothing(empty_engine):
    migrate_schema(empty_engine)
    _seed(empty_engine)
    before = _revision(empty_engine)

    migrate_schema(empty_engine)

    assert _revision(empty_engine) == before
    assert _file_count(empty_engine) == 2


def test_a_database_from_before_migrations_is_adopted_with_its_data(empty_engine, tmp_path):
    """Every server deployed so far: the baseline's tables, and no record of a revision."""
    baseline_only = tmp_path / "baseline"
    shutil.copytree(MIGRATIONS, baseline_only, ignore=shutil.ignore_patterns("__pycache__"))
    for later in (baseline_only / "versions").glob("*.py"):
        if not later.name.startswith(BASELINE_REVISION):
            later.unlink()
    migrate_schema(empty_engine, script_location=str(baseline_only))
    _seed(empty_engine)
    with empty_engine.begin() as connection:
        connection.execute(text("DROP TABLE alembic_version"))

    migrate_schema(empty_engine)

    assert _revision(empty_engine) is not None
    assert _file_count(empty_engine) == 2
    with empty_engine.connect() as connection:
        assert connection.scalars(select(User.username)).all() == ["dimitris"]


def test_a_migration_that_fails_leaves_the_database_as_it_was(empty_engine, tmp_path):
    migrate_schema(empty_engine)
    _seed(empty_engine)
    before = _revision(empty_engine)
    broken = _with_extra_migration(tmp_path, (
        "    op.create_table('half_done', sa.Column('id', sa.Integer(), primary_key=True))\n"
        "    op.execute('DELETE FROM skill_file')\n"
        "    raise RuntimeError('step two of this migration failed')"))

    with pytest.raises(RuntimeError, match="step two"):
        migrate_schema(empty_engine, script_location=broken)

    assert "half_done" not in _tables(empty_engine)
    assert _revision(empty_engine) == before
    assert _file_count(empty_engine) == 2


def test_a_failed_first_start_leaves_an_empty_database_empty(empty_engine, tmp_path):
    broken = _with_extra_migration(tmp_path, "    raise RuntimeError('never finished')")

    with pytest.raises(RuntimeError, match="never finished"):
        migrate_schema(empty_engine, script_location=broken)

    assert _tables(empty_engine) == set()


def test_rebuilding_a_table_does_not_cascade_into_the_rows_that_reference_it(empty_engine,
                                                                            tmp_path):
    """SQLite alters a constraint by dropping the table and making it again. With foreign keys
    on, that drop deletes every row, and skill_file cascades from skill_version."""
    migrate_schema(empty_engine)
    _seed(empty_engine)
    rebuild = _with_extra_migration(tmp_path, (
        "    with op.batch_alter_table('skill_version') as batch:\n"
        "        batch.alter_column('version', type_=sa.String(64))"))

    migrate_schema(empty_engine, script_location=rebuild)

    assert _file_count(empty_engine) == 2


def test_foreign_keys_are_enforced_again_after_a_migration(engine):
    with engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
