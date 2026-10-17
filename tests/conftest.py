import os

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from aistack.db.engine import build_engine, build_session_factory
from aistack.db.schema import migrate_schema

INVITE_CODE = "test-invite-code-long-enough"


def pytest_addoption(parser):
    parser.addoption(
        "--shard",
        help="k/n: run every n-th collected test, starting at the k-th. CI splits the suite this way.",
    )


def pytest_collection_modifyitems(config, items):
    """Keep one shard of the suite. Every shard collects the same tests in the same order, so
    the n shards together run each test exactly once, and a new test file needs no listing."""
    shard = config.getoption("shard")
    if not shard:
        return
    k, n = (int(part) for part in shard.split("/"))
    kept = items[k - 1::n]
    kept_ids = {id(item) for item in kept}
    config.hook.pytest_deselected(items=[item for item in items if id(item) not in kept_ids])
    items[:] = kept


@pytest.fixture(name="sqlite_url")
def sqlite_url_fixture(tmp_path) -> str:
    """A SQLite URL backed by a real file, never ':memory:'.

    An in-memory database is per-connection, so WAL means nothing and any test that needs two
    connections, the admin race, the auth verifier's own session, silently gets two empty
    databases instead of one shared one.
    """
    return f"sqlite:///{tmp_path / 'aistack.db'}"


@pytest.fixture(name="engine")
def engine_fixture(sqlite_url: str) -> Engine:
    engine = build_engine(sqlite_url)
    migrate_schema(engine)
    yield engine
    engine.dispose()


@pytest.fixture(name="session_factory")
def session_factory_fixture(engine: Engine) -> sessionmaker[Session]:
    return build_session_factory(engine)


@pytest.fixture(name="postgres_engine")
def postgres_engine_fixture():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to run PostgreSQL tests; start compose.test.yaml.")
    engine = build_engine(url)
    if engine.dialect.name != "postgresql":
        engine.dispose()
        pytest.fail("TEST_DATABASE_URL must point to a disposable PostgreSQL database.")
    try:
        _drop_everything(engine)
        migrate_schema(engine)
        yield engine
    finally:
        _drop_everything(engine)
        engine.dispose()


def _drop_everything(engine: Engine) -> None:
    """Empty the disposable database, including tables no current model describes."""
    with engine.begin() as connection:
        connection.exec_driver_sql("DROP SCHEMA public CASCADE")
        connection.exec_driver_sql("CREATE SCHEMA public")


@pytest.fixture(name="portable_engine", params=(
    ["sqlite", "postgresql"] if os.environ.get("TEST_DATABASE_URL") else ["sqlite"]
))
def portable_engine_fixture(request):
    return request.getfixturevalue("postgres_engine" if request.param == "postgresql" else "engine")
