import contextlib

import httpx
import pytest

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
