import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from aistack.db.engine import build_engine, build_session_factory, create_schema

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
