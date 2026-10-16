"""`/metrics`: counts for the operator's monitoring, to its own bearer only (STD-19)."""

import logging
import re

import httpx
import pytest
from pydantic import SecretStr

from aistack.bootstrap.configuration.settings.settings_config import Settings
from aistack.bootstrap.context import application_context
from aistack.commons import request_id
from aistack.mcp.routes import metrics
from tests.conftest import INVITE_CODE
from tests.mcp.conftest import call, join

pytestmark = pytest.mark.anyio

TOKEN = "metrics-token-for-the-operators-monitoring"


def _base(server_url: str) -> str:
    return server_url.removesuffix("/mcp")


async def _get(server_url: str, path: str, bearer: str | None = None) -> httpx.Response:
    headers = {} if bearer is None else {"Authorization": f"Bearer {bearer}"}
    async with httpx.AsyncClient(base_url=_base(server_url)) as client:
        return await client.get(path, headers=headers)


async def test_the_operators_bearer_reads_the_counts(server_url, monkeypatch):
    monkeypatch.setattr(metrics, "get_metrics_token", lambda: SecretStr(TOKEN))
    token = await join(server_url, "dimitris", "laptop")
    await call(server_url, token, "sync", local={})

    response = await _get(server_url, "/metrics", TOKEN)

    assert response.status_code == 200
    assert 'aistack_tool_calls_total{tool="sync",outcome="ok"}' in response.text
    assert "aistack_info{version=" in response.text


@pytest.mark.parametrize("configured, presented", [
    (None, TOKEN), (TOKEN, None), (TOKEN, "a-wrong-token-of-the-same-sort-entirely")],
    ids=["no-setting", "no-bearer", "wrong-bearer"])
async def test_without_the_setting_or_its_bearer_there_is_no_such_route(
        server_url, monkeypatch, caplog, configured, presented):
    monkeypatch.setattr(metrics, "get_metrics_token",
                        lambda: None if configured is None else SecretStr(configured))
    caplog.set_level(logging.DEBUG)

    refused = await _get(server_url, "/metrics", presented)
    nowhere = await _get(server_url, "/no-such-route")

    assert (refused.status_code, refused.text) == (nowhere.status_code, nowhere.text) == (
        404, "Not Found")
    assert TOKEN not in caplog.text and (presented or TOKEN) not in caplog.text


def test_a_metrics_token_that_is_easy_to_guess_stops_the_server(sqlite_url):
    with pytest.raises(ValueError, match="AISTACK_METRICS_TOKEN is too easy to guess"):
        application_context.build_application_context(Settings(
            _env_file=None, database_url=sqlite_url, aistack_invite_code=INVITE_CODE,
            aistack_metrics_token="short"))
    application_context.dispose_application_context()


async def test_the_lines_one_request_writes_carry_its_id(server_url, caplog):
    request_id.install()
    token = await join(server_url, "dimitris", "laptop")
    caplog.set_level(logging.INFO, logger="aistack")

    await call(server_url, token, "sync", local={})
    await call(server_url, token, "sync", local={})

    ids = [record.request_id for record in caplog.records
           if record.name == "aistack.mcp.tools.sync"]
    assert len(ids) == 2 and all(re.fullmatch(r"[0-9a-f]{8}", each) for each in ids)
    assert ids[0] != ids[1]
