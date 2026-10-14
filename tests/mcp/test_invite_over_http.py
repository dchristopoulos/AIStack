"""The invite link (ADR-0019): a page that says which team, and the one sentence to paste."""

import logging

import httpx
import pytest

from tests.mcp.conftest import call, join

pytestmark = pytest.mark.anyio


def _base(server_url: str) -> str:
    return server_url.removesuffix("/mcp")


async def _invite(server_url: str) -> dict:
    dimitris = await join(server_url)
    await call(server_url, dimitris, "create_team", name="acme")
    return await call(server_url, dimitris, "invite_to_team", team="acme")


async def _get(url: str) -> httpx.Response:
    async with httpx.AsyncClient() as http:
        return await http.get(url)


async def test_invite_to_team_returns_a_link_on_this_server(server_url):
    invite = await _invite(server_url)

    assert invite["link"] == f"{_base(server_url)}/invite/{invite['code']}"


async def test_the_invite_page_names_the_team_and_what_to_paste(server_url):
    invite = await _invite(server_url)

    response = await _get(invite["link"])

    assert response.status_code == 200
    assert "acme" in response.text
    assert f"fetch {_base(server_url)}/setup and follow it" in response.text
    assert f"Invite code: {invite['code']}" in response.text
    # The code is in the address bar: no other site may learn it from a link on this page.
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["cache-control"] == "no-store"
    assert "default-src 'none'" in response.headers["content-security-policy"]


async def test_a_wrong_or_replaced_code_reads_exactly_like_any_other_wrong_code(server_url):
    dimitris = await join(server_url)
    await call(server_url, dimitris, "create_team", name="acme")
    replaced = (await call(server_url, dimitris, "invite_to_team", team="acme"))
    current = (await call(server_url, dimitris, "invite_to_team", team="acme"))["code"]

    answers = [await _get(f"{_base(server_url)}/invite/{code}")
               for code in ("aistinv_nothing", current[:-1], "anything")]
    answers.append(await _get(replaced["link"]))

    assert {(answer.status_code, answer.text) for answer in answers} == {
        (404, answers[0].text)}
    assert "acme" not in answers[0].text


async def test_an_invite_link_appears_in_no_log_line(server_url, caplog):
    with caplog.at_level(logging.DEBUG):
        invite = await _invite(server_url)
        await _get(invite["link"])
        await _get(invite["link"] + "x")

    # AIStack's own loggers: uvicorn's access log looks alive under pytest, and it is off in
    # the real server's configuration, where test_http_server_config asserts it.
    for record in caplog.records:
        if not record.name.startswith("aistack"):
            continue
        message = record.getMessage()
        assert invite["code"] not in message
        assert invite["code"].removeprefix("aistinv_") not in message
