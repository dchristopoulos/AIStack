import contextlib
import uuid

import httpx
import pytest

from aistack.bootstrap.context import application_context
from aistack.services import library_log, skill_service
from tests.local_dashboard import local_dashboard

pytestmark = pytest.mark.anyio

REQUEST_HEADER = {"X-AIStack-Request": "1"}


@pytest.fixture(name="anyio_backend")
def anyio_backend_fixture():
    return "asyncio"


@pytest.fixture(name="dashboard")
async def dashboard_fixture(tmp_path, portable_engine):
    async with local_dashboard(tmp_path, portable_engine.url.render_as_string(
            hide_password=False)) as served:
        yield served


@contextlib.asynccontextmanager
async def _signed_in(base: str, link: str):
    async with httpx.AsyncClient(base_url=base) as client:
        assert (await client.get(link)).status_code == 303
        yield client


async def test_the_link_signs_in_to_the_persons_own_library(dashboard):
    base, link = dashboard
    async with _signed_in(base, link) as client:
        state = (await client.get("/api/state")).json()

    assert state["server"] is False
    assert state["library"]["kind"] in ("this_computer", "postgresql")
    assert state["user"]["username"] == "maria"
    assert [skill["name"] for skill in state["skills"]] == ["wizard"]


async def test_nothing_is_reachable_without_signing_in(dashboard):
    base, _ = dashboard
    async with httpx.AsyncClient(base_url=base) as client:
        assert (await client.get("/api/state")).status_code == 401
        assert (await client.get("/app")).status_code == 401


async def test_team_routes_and_the_server_routes_are_not_served(dashboard):
    """A team needs a server everyone reaches, and nothing but the page belongs on localhost."""
    base, link = dashboard
    async with _signed_in(base, link) as client:
        assert (await client.post("/api/teams", json={"name": "backend"},
                                  headers=REQUEST_HEADER)).status_code == 404
        assert (await client.post("/api/teams/join", json={"code": "aistinv_x"},
                                  headers=REQUEST_HEADER)).status_code == 404
        for path in ("/mcp", "/setup", "/health", "/invite/aistinv_x"):
            assert (await client.get(path)).status_code == 404, path


async def test_a_page_on_another_host_name_is_turned_away(dashboard):
    """DNS rebinding: a site that points its own name at 127.0.0.1 sends its own Host."""
    base, link = dashboard
    async with httpx.AsyncClient(base_url=base, headers={"Host": "evil.example"}) as client:
        assert (await client.get(link)).status_code == 400


async def test_a_change_needs_the_pages_own_header(dashboard):
    base, link = dashboard
    async with _signed_in(base, link) as client:
        response = await client.post("/api/skills/wizard/remove", json={})
        assert response.status_code == 400
        assert [skill["name"] for skill in (await client.get("/api/state")).json()["skills"]] \
            == ["wizard"]


async def test_a_moved_library_refuses_the_page_and_its_changes(dashboard):
    """AUTO-05: a change made here after a move would reach none of the other computers."""
    base, link = dashboard
    caller = application_context.get_local_principal()
    moved = library_log.Event(uuid.uuid4(), "2026-10-15T09:00:00.000000Z", caller.machine_id,
                              library_log.LIBRARY_MOVED,
                              {"place": {"kind": "github", "repository": "maria/skills"}})
    with application_context.get_session_factory().begin() as session:
        # As replay stores it: this release records no move of its own.
        library_log._store_event(session, moved, published=True)

    async with _signed_in(base, link) as client:
        for response in (await client.get("/api/state"),
                         await client.post("/api/skills/wizard/remove", json={},
                                           headers=REQUEST_HEADER)):
            assert response.status_code == 409
            assert "moved to the GitHub repository maria/skills" in response.json()["error"]

    with application_context.get_session_factory().begin() as session:
        assert [skill.name for skill in skill_service.list_skills(session, caller.user_id)] \
            == ["wizard"]


async def test_a_project_folder_is_not_placed_into_from_the_local_dashboard_yet(dashboard):
    """Its log event is replayed by this release and recorded by a later one (ADR-0026)."""
    base, link = dashboard
    async with _signed_in(base, link) as client:
        machine = (await client.get("/api/state")).json()["machines"][0]["id"]
        refused = await client.post(f"/api/skills/wizard/machines/{machine}",
                                    json={"enabled": True, "project": "github.com/a/b"},
                                    headers=REQUEST_HEADER)
        added = await client.post(f"/api/machines/{machine}/projects",
                                  json={"project": "github.com/a/b"}, headers=REQUEST_HEADER)

    assert refused.status_code == 400 and "on an AIStack server for now" in refused.json()["error"]
    assert added.status_code == 404
