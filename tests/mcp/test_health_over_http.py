import httpx
import pytest

from aistack.bootstrap.context import application_context

pytestmark = pytest.mark.anyio


def _health_url(server_url: str) -> str:
    return server_url.removesuffix("/mcp") + "/health"


async def test_health_answers_without_a_bearer(server_url):
    """A container runtime has no token, and the answer gives nothing away."""
    async with httpx.AsyncClient() as http:
        response = await http.get(_health_url(server_url))

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_health_reports_an_unreachable_database_without_saying_why(server_url,
                                                                       monkeypatch, caplog):
    def broken():
        raise RuntimeError("password authentication failed for user 'aistack'")

    monkeypatch.setattr(application_context, "get_read_session_factory", broken)
    monkeypatch.setattr("aistack.mcp.routes.health.get_read_session_factory", broken)

    async with httpx.AsyncClient() as http:
        response = await http.get(_health_url(server_url))

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}
    assert "password" not in response.text
    assert any("Health check failed" in record.getMessage() for record in caplog.records)


async def test_the_mcp_endpoint_still_requires_a_bearer(server_url):
    """The health route is the only thing an anonymous caller gets a 200 from."""
    async with httpx.AsyncClient() as http:
        response = await http.post(server_url, json={"jsonrpc": "2.0", "id": 1,
                                                     "method": "tools/list"})

    assert response.status_code == 401
