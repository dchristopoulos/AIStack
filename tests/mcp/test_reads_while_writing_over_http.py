"""On SQLite, a request that only reads does not wait for a writer (ADR-0030)."""

import sqlite3
from contextlib import contextmanager
from time import perf_counter

import httpx
import pytest
from fastmcp.exceptions import ToolError

from tests.mcp.conftest import call, join

pytestmark = pytest.mark.anyio

# Well under the five-second busy timeout a request would otherwise wait out.
PROMPTLY = 1.5


@pytest.fixture(name="database_file")
def database_file_fixture(portable_engine):
    if portable_engine.dialect.name != "sqlite":
        pytest.skip("PostgreSQL's readers never waited for a writer; this is SQLite's lock")
    return portable_engine.url.database


@contextmanager
def _a_write_in_progress(database_file):
    """Another connection holding SQLite's only write lock, as a slow push would."""
    writer = sqlite3.connect(database_file, isolation_level=None)
    try:
        writer.execute("BEGIN IMMEDIATE")
        yield
    finally:
        writer.execute("ROLLBACK")
        writer.close()


async def test_health_answers_ok_while_another_request_writes(server_url, database_file):
    async with httpx.AsyncClient() as http:
        with _a_write_in_progress(database_file):
            started = perf_counter()
            response = await http.get(server_url.removesuffix("/mcp") + "/health")

    assert response.json() == {"status": "ok"}
    assert perf_counter() - started < PROMPTLY


async def test_a_bearer_is_checked_and_skills_listed_while_another_request_writes(
        server_url, database_file):
    token = await join(server_url)

    with _a_write_in_progress(database_file):
        started = perf_counter()
        listed = await call(server_url, token, "list_skills")

    assert listed["skills"] == []
    assert perf_counter() - started < PROMPTLY


async def test_an_unknown_bearer_is_refused_while_another_request_writes(server_url,
                                                                       database_file):
    with _a_write_in_progress(database_file):
        started = perf_counter()
        async with httpx.AsyncClient() as http:
            response = await http.post(server_url, json={"jsonrpc": "2.0", "id": 1,
                                                         "method": "tools/list"},
                                       headers={"Authorization": "Bearer aist_unknown"})

    assert response.status_code == 401
    assert perf_counter() - started < PROMPTLY


async def test_the_dashboard_state_loads_while_another_request_writes(server_url,
                                                                    database_file):
    token = await join(server_url)
    link = (await call(server_url, token, "open_dashboard"))["url"]
    async with httpx.AsyncClient(base_url=server_url.removesuffix("/mcp")) as browser:
        await browser.get(link)
        with _a_write_in_progress(database_file):
            started = perf_counter()
            response = await browser.get("/api/state")

    assert response.status_code == 200
    assert response.json()["user"]["username"] == "dimitris"
    assert perf_counter() - started < PROMPTLY


async def test_a_write_that_waits_too_long_says_to_try_again(server_url, database_file):
    token = await join(server_url)

    with _a_write_in_progress(database_file):
        with pytest.raises(ToolError, match="The server is busy right now.*Nothing was changed. "
                                            "Make the same call again in a few seconds."):
            await call(server_url, token, "sync", local={})
