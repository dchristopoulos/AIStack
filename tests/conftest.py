import os

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from aistack.db.engine import build_engine, build_session_factory, create_schema
from aistack.db.models import Base

INVITE_CODE = "test-invite-code-long-enough"


@pytest.fixture(name="sqlite_url")
def sqlite_url_fixture(tmp_path) -> str:
    """A SQLite URL backed by a real file, never ':memory:'.

    An in-memory database is per-connection, so WAL means nothing and any test that needs two
    connections — the admin race, the auth verifier's own session — silently gets two empty
    databases instead of one shared one.
    """
    return f"sqlite:///{tmp_path / 'aistack.db'}"


@pytest.fixture(name="engine")
def engine_fixture(sqlite_url: str) -> Engine:
    engine = build_engine(sqlite_url)
    create_schema(engine)
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
        Base.metadata.drop_all(engine)
        create_schema(engine)
        yield engine
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture(name="portable_engine", params=(
    ["sqlite", "postgresql"] if os.environ.get("TEST_DATABASE_URL") else ["sqlite"]
))
def portable_engine_fixture(request):
    return request.getfixturevalue("postgres_engine" if request.param == "postgresql" else "engine")
