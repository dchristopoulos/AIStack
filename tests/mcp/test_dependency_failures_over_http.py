"""PostgreSQL failures leave no partial upload and give the caller a safe sentence."""

import httpx
import pytest
from sqlalchemy import event, select

from aistack.bootstrap.context.application_context import get_session_factory
from aistack.db.models.skill import Skill
from aistack.db.models.skill_version import SkillVersion
from tests.archives import skill_archive
from tests.mcp.conftest import call, join

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("fault", ["statement-timeout", "connection-dropped"])
async def test_a_postgres_failure_rolls_back_the_upload_and_the_same_ticket_can_retry(
        server_url, portable_engine, fault):
    if portable_engine.dialect.name != "postgresql":
        pytest.skip("Statement deadlines and backend termination are PostgreSQL-specific.")
    token = await join(server_url)
    upload = (await call(server_url, token, "push_skill", name="wizard"))["upload_url"]
    factory = get_session_factory()
    engine = factory.kw["bind"]
    reached = []
    errors = []

    def failed(context):
        errors.append((getattr(context.original_exception, "sqlstate", None), context.is_disconnect))

    def interrupt(connection, cursor, statement, parameters, context, executemany):
        if reached or not statement.startswith("INSERT INTO skill_version "):
            return
        reached.append(statement)
        if fault == "statement-timeout":
            connection.exec_driver_sql("SET LOCAL statement_timeout = '25ms'")
            connection.exec_driver_sql("SELECT pg_sleep(10)")
        else:
            pid = connection.exec_driver_sql("SELECT pg_backend_pid()").scalar_one()
            with portable_engine.begin() as killer:
                assert killer.exec_driver_sql(
                    "SELECT pg_terminate_backend(%s)", (pid,)).scalar_one() is True

    event.listen(engine, "before_cursor_execute", interrupt)
    event.listen(engine, "handle_error", failed)
    try:
        async with httpx.AsyncClient() as http:
            response = await http.put(upload, content=skill_archive())
    finally:
        event.remove(engine, "before_cursor_execute", interrupt)
        event.remove(engine, "handle_error", failed)

    assert len(reached) == 1
    assert response.status_code == 500
    assert response.json() == {"error": "Something went wrong on the server. Its log says what."}
    if fault == "statement-timeout":
        assert any(state == "57014" for state, _ in errors)
    else:
        assert any(disconnected for _, disconnected in errors)
    with factory.begin() as session:
        assert session.scalar(select(Skill).where(Skill.name == "wizard")) is None
        assert session.scalars(select(SkillVersion)).all() == []

    async with httpx.AsyncClient() as http:
        retried = await http.put(upload, content=skill_archive())
    assert retried.status_code == 200 and retried.json()["revision"] == 1
    with factory.begin() as session:
        [version] = session.scalars(select(SkillVersion)).all()
        assert version.revision == 1
