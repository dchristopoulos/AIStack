"""The dashboard from a browser's side: sign in with a link, then the JSON routes."""

import logging
from contextlib import asynccontextmanager

import httpx
import pytest
from sqlalchemy import delete

from aistack.api.dashboard import REQUEST_HEADER, SESSION_COOKIE
from aistack.bootstrap.context import application_context
from aistack.db.models.machine import Machine
from aistack.db.models.machine_skill import MachineSkill
from tests.archives import skill_archive
from tests.conftest import INVITE_CODE
from tests.mcp.conftest import client_for

pytestmark = pytest.mark.anyio

HEADERS = {REQUEST_HEADER: "1"}


def _base(server_url: str) -> str:
    return server_url.removesuffix("/mcp")


async def _join(server_url, username, machine_name="laptop") -> str:
    async with client_for(server_url, INVITE_CODE) as client:
        joined = await client.call_tool("join", {"username": username,
                                                 "machine_name": machine_name, "os": "LINUX"})
    return joined.structured_content["token"]


async def _call(server_url, token, tool, **arguments) -> dict:
    async with client_for(server_url, token) as client:
        return (await client.call_tool(tool, arguments)).structured_content


async def _push(server_url, token, name="wizard", **archive) -> dict:
    issued = await _call(server_url, token, "push_skill", name=name)
    async with httpx.AsyncClient() as http:
        return (await http.put(issued["upload_url"],
                               content=skill_archive(name, **archive))).json()


@asynccontextmanager
async def _browser(server_url, token):
    """A browser that opened the link `open_dashboard` returned."""
    link = (await _call(server_url, token, "open_dashboard"))["url"]
    async with httpx.AsyncClient(base_url=_base(server_url)) as browser:
        signed_in = await browser.get(link)
        assert signed_in.status_code == 303 and signed_in.headers["location"] == "/app"
        yield browser


async def _post(browser, route, **body) -> httpx.Response:
    return await browser.post(f"/api{route}", json=body, headers=HEADERS)


async def _state(browser) -> dict:
    response = await browser.get("/api/state")
    assert response.status_code == 200, response.text
    return response.json()


# --- signing in -----------------------------------------------------------------------------

async def test_a_link_from_chat_signs_the_browser_in_and_leaves_the_address_bar(server_url):
    token = await _join(server_url, "dimitris")
    link = (await _call(server_url, token, "open_dashboard"))["url"]

    async with httpx.AsyncClient(base_url=_base(server_url)) as browser:
        signed_in = await browser.get(link)
        page = await browser.get("/app")
        state = await _state(browser)

    cookie = signed_in.headers["set-cookie"].lower()
    assert link.startswith(f"{_base(server_url)}/app/login/")
    assert signed_in.status_code == 303 and signed_in.headers["location"] == "/app"
    assert "httponly" in cookie and "samesite=lax" in cookie
    assert page.status_code == 200 and page.headers["content-type"].startswith("text/html")
    assert state["user"] == {"username": "dimitris"}
    assert [machine["name"] for machine in state["machines"]] == ["laptop"]


async def test_the_page_may_load_nothing_from_anywhere_else(server_url):
    async with _browser(server_url, await _join(server_url, "dimitris")) as browser:
        page = await browser.get("/app")

    policy = page.headers["content-security-policy"]
    assert "default-src 'none'" in policy and "connect-src 'self'" in policy
    assert "frame-ancestors 'none'" in policy
    assert page.headers["referrer-policy"] == "no-referrer"
    assert page.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("path", ["/app", "/api/state"])
async def test_nothing_is_served_without_a_session(server_url, path):
    async with httpx.AsyncClient(base_url=_base(server_url)) as stranger:
        response = await stranger.get(path)

    assert response.status_code == 401
    assert "open my aistack dashboard" in response.text
    assert "dimitris" not in response.text


async def test_the_servers_address_leads_a_stranger_to_how_to_connect(server_url):
    async with httpx.AsyncClient(base_url=_base(server_url), follow_redirects=True) as stranger:
        response = await stranger.get("/")

    assert response.url.path == "/app" and response.status_code == 401
    # Someone whose agent is not connected yet gets the sentence that connects it.
    assert f"fetch {_base(server_url)}/setup and follow it" in response.text
    assert 'name=viewport' in response.text


@pytest.mark.parametrize("ticket", ["nonsense", "a.b.c", ""])
async def test_a_link_that_is_not_one_signs_nobody_in(server_url, ticket):
    async with httpx.AsyncClient(base_url=_base(server_url)) as stranger:
        response = await stranger.get(f"/app/login/{ticket}")

    assert response.status_code in (401, 404)
    assert "set-cookie" not in response.headers


async def test_a_link_is_not_a_session_and_a_session_is_not_a_link(server_url):
    """Each is a signed ticket with its own purpose, so neither can stand in for the other."""
    token = await _join(server_url, "dimitris")
    link_ticket = (await _call(server_url, token, "open_dashboard"))["url"].rsplit("/", 1)[1]
    async with _browser(server_url, token) as browser:
        session_ticket = browser.cookies[SESSION_COOKIE]

    async with httpx.AsyncClient(base_url=_base(server_url)) as stranger:
        link_as_session = await stranger.get("/api/state", cookies={SESSION_COOKIE: link_ticket})
        session_as_link = await stranger.get(f"/app/login/{session_ticket}")

    assert link_as_session.status_code == 401
    assert session_as_link.status_code == 401 and "set-cookie" not in session_as_link.headers


async def test_a_link_signs_a_browser_in_once(server_url):
    """A link copied afterwards, from a chat log or a browser's history, signs nobody in."""
    token = await _join(server_url, "dimitris")
    link = httpx.URL((await _call(server_url, token, "open_dashboard"))["url"]).path
    async with httpx.AsyncClient(base_url=_base(server_url)) as first:
        used = await first.get(link)
    async with httpx.AsyncClient(base_url=_base(server_url)) as second:
        again = await second.get(link)

    assert used.status_code == 303 and "set-cookie" in used.headers
    assert again.status_code == 401 and "set-cookie" not in again.headers


async def test_a_transfer_url_is_not_a_way_in(server_url):
    token = await _join(server_url, "dimitris")
    upload_ticket = (await _call(server_url, token, "push_skill", name="wizard"))[
        "upload_url"].rsplit("/", 1)[1]

    async with httpx.AsyncClient(base_url=_base(server_url)) as stranger:
        as_link = await stranger.get(f"/app/login/{upload_ticket}")
        as_session = await stranger.get("/api/state", cookies={SESSION_COOKIE: upload_ticket})

    assert as_link.status_code == 401 and as_session.status_code == 401


async def test_a_change_needs_the_header_a_cross_site_page_cannot_send(server_url):
    async with _browser(server_url, await _join(server_url, "dimitris")) as browser:
        forged = await browser.post("/api/teams", json={"name": "acme"})
        real = await _post(browser, "/teams", name="acme")
        teams = [team["name"] for team in (await _state(browser))["teams"]]

    assert forged.status_code == 400 and "did not come from the dashboard" in forged.text
    assert real.status_code == 200
    assert teams == ["acme"]


async def test_signing_out_ends_the_session_in_that_browser(server_url):
    async with _browser(server_url, await _join(server_url, "dimitris")) as browser:
        await _post(browser, "/logout")
        after = await browser.get("/api/state")

    assert after.status_code == 401


# --- what it shows and does -----------------------------------------------------------------

async def test_a_team_from_creation_to_an_update_taken_entirely_on_the_dashboard(server_url):
    """Two people, one team, one nested private group, and a change offered and accepted."""
    dimitris_token = await _join(server_url, "dimitris")
    maria_token = await _join(server_url, "maria")
    await _push(server_url, dimitris_token, "code-review", files={"notes.md": "one\n"})

    async with _browser(server_url, dimitris_token) as dimitris, \
            _browser(server_url, maria_token) as maria:
        assert (await _post(dimitris, "/teams", name="acme")).status_code == 200
        code = (await _post(dimitris, "/teams/acme/invite")).json()["code"]
        assert (await _post(maria, "/teams/join", code=code)).json() == {"team": "acme"}

        assert (await _post(dimitris, "/teams/acme/groups", name="backend")).json() == {
            "path": "backend"}
        nested = await _post(dimitris, "/teams/acme/groups", name="aistack", parent="backend",
                             private=True)
        assert nested.json() == {"path": "backend/aistack"}

        shared = (await _post(dimitris, "/skills/code-review/share", team="acme",
                              group="backend/aistack")).json()
        assert (shared["group"], shared["revision"], shared["created"]) == (
            "backend/aistack", 1, True)

        # Maria is in the team and not in the private group: she is shown neither.
        acme = next(team for team in (await _state(maria))["teams"] if team["name"] == "acme")
        assert acme["skills"] == [] and [group["path"] for group in acme["groups"]] == [
            "backend"]

        await _post(dimitris, "/teams/acme/group/members", path="backend/aistack",
                    username="maria", member=True)
        acme = next(team for team in (await _state(maria))["teams"] if team["name"] == "acme")
        assert [(skill["name"], skill["group"], skill["pushed_by"], skill["in_library"])
                for skill in acme["skills"]] == [
            ("code-review", "backend/aistack", "dimitris", False)]

        assert (await _post(maria, "/teams/acme/take", name="code-review")).status_code == 200
        machine = (await _state(maria))["machines"][0]["id"]
        await _post(maria, f"/skills/code-review/machines/{machine}", enabled=True)
        mine = (await _state(maria))["skills"][0]
        assert (mine["name"], mine["placements"], mine["source"]["update_available"]) == (
            "code-review", [{"machine": machine, "harness": "claude_code"}], False)

        # Dimitris changes it and shares again: Maria is offered it, and takes it.
        await _push(server_url, dimitris_token, "code-review", files={"notes.md": "two\n"})
        await _post(dimitris, "/skills/code-review/share", team="acme")
        offered = (await _state(maria))["skills"][0]["source"]
        assert (offered["revision"], offered["latest_revision"], offered["latest_pushed_by"],
                offered["update_available"]) == (1, 2, "dimitris", True)

        await _post(maria, "/teams/acme/take", name="code-review")
        taken = (await _state(maria))["skills"][0]
        assert taken["source"]["update_available"] is False and taken["revision"] == 2

    # And her computer hears about it the ordinary way, at its next sync.
    report = await _call(server_url, maria_token, "sync", local={})
    assert [entry["name"] for entry in report["install"]] == ["code-review"]


async def test_what_only_an_admin_may_do_is_refused_to_a_member_with_a_sentence(server_url):
    dimitris_token = await _join(server_url, "dimitris")
    maria_token = await _join(server_url, "maria")
    async with _browser(server_url, dimitris_token) as dimitris, \
            _browser(server_url, maria_token) as maria:
        await _post(dimitris, "/teams", name="acme")
        code = (await _post(dimitris, "/teams/acme/invite")).json()["code"]
        await _post(maria, "/teams/join", code=code)

        refusals = [
            await _post(maria, "/teams/acme/invite"),
            await _post(maria, "/teams/acme/groups", name="backend"),
            await _post(maria, "/teams/acme/members/dimitris/remove"),
            await _post(maria, "/teams/acme/members/maria", role="ADMIN"),
        ]
        members = next(team for team in (await _state(dimitris))["teams"]
                       if team["name"] == "acme")["members"]

    for refusal in refusals:
        assert refusal.status_code == 400 and "Only an admin" in refusal.json()["error"]
    assert [(member["username"], member["role"]) for member in members] == [
        ("dimitris", "ADMIN"), ("maria", "MEMBER")]


async def test_someone_outside_a_team_is_told_what_they_would_be_told_if_it_did_not_exist(
        server_url):
    dimitris_token = await _join(server_url, "dimitris")
    eve_token = await _join(server_url, "eve")
    await _push(server_url, eve_token, "wizard")
    async with _browser(server_url, dimitris_token) as dimitris, \
            _browser(server_url, eve_token) as eve:
        await _post(dimitris, "/teams", name="acme")

        for path, body in (("/teams/{team}/leave", {}), ("/teams/{team}/invite", {}),
                           ("/teams/{team}/take", {"name": "wizard"}),
                           ("/teams/{team}/groups", {"name": "x"}),
                           ("/skills/wizard/share", {"team": "{team}"})):
            answers = []
            for team in ("acme", "nowhere"):
                filled = {key: value.replace("{team}", team) for key, value in body.items()}
                response = await _post(eve, path.replace("{team}", team), **filled)
                answers.append((response.status_code,
                                response.json()["error"].replace(team, "X")))
            assert answers[0] == answers[1] and answers[0][0] == 404, path

        assert (await _state(eve))["teams"] == []


async def test_a_computer_that_is_not_yours_is_one_that_does_not_exist(server_url):
    dimitris_token = await _join(server_url, "dimitris")
    maria_token = await _join(server_url, "maria")
    await _push(server_url, dimitris_token)
    async with _browser(server_url, dimitris_token) as dimitris, \
            _browser(server_url, maria_token) as maria:
        marias = (await _state(maria))["machines"][0]["id"]

        theirs = await _post(dimitris, f"/skills/wizard/machines/{marias}", enabled=True)
        nobody = await _post(dimitris, "/skills/wizard/machines/not-a-machine", enabled=True)

    assert theirs.status_code == nobody.status_code == 404
    assert (await _call(server_url, maria_token, "sync", local={}))["install"] == []


@pytest.mark.parametrize("body", [b"not json", b"[1, 2]", b'{"name": 5}', b"x" * 20_000])
async def test_a_malformed_request_is_a_sentence_not_a_crash(server_url, body):
    async with _browser(server_url, await _join(server_url, "dimitris")) as browser:
        response = await browser.post("/api/teams", content=body, headers=HEADERS)

    assert response.status_code == 400 and response.json()["error"]


async def test_removing_a_skill_and_switching_it_per_computer_and_harness(server_url):
    token = await _join(server_url, "dimitris")
    await _call(server_url, token, "add_machine", name="desktop", os="LINUX")
    await _push(server_url, token)
    async with _browser(server_url, token) as browser:
        state = await _state(browser)
        laptop, desktop = (machine["id"] for machine in state["machines"])
        assert state["skills"][0]["placements"] == [{"machine": laptop,
                                                     "harness": "claude_code"}]

        await _post(browser, f"/skills/wizard/machines/{desktop}", enabled=True)
        await _post(browser, f"/skills/wizard/machines/{desktop}", enabled=True,
                    harness="agents")
        await _post(browser, f"/skills/wizard/machines/{laptop}", enabled=False)
        assert (await _state(browser))["skills"][0]["placements"] == [
            {"machine": desktop, "harness": "agents"},
            {"machine": desktop, "harness": "claude_code"}]

        unknown = await _post(browser, f"/skills/wizard/machines/{desktop}", enabled=True,
                              harness="cursor")
        assert unknown.status_code == 400
        assert unknown.json()["error"] == (
            "harness must be one of claude_code, agents. Received: 'cursor'.")

        await _post(browser, "/skills/wizard/remove")
        assert (await _state(browser))["skills"] == []


# --- secrets --------------------------------------------------------------------------------

async def test_no_link_session_or_invite_code_reaches_a_log_line(server_url, caplog):
    caplog.set_level(logging.DEBUG)
    token = await _join(server_url, "dimitris")
    link = (await _call(server_url, token, "open_dashboard"))["url"]
    async with httpx.AsyncClient(base_url=_base(server_url)) as browser:
        await browser.get(link)
        session = browser.cookies[SESSION_COOKIE]
        await _post(browser, "/teams", name="acme")
        code = (await _post(browser, "/teams/acme/invite")).json()["code"]
        await _post(browser, "/teams/join", code="aistinv_wrong-code")
        await browser.get("/app/login/not-a-ticket")

    # The server's own loggers. This test's HTTP client logs the URLs it requests, at DEBUG.
    logged = "\n".join(
        record.getMessage() for record in caplog.records
        if record.name.startswith(("aistack", "fastmcp", "mcp.server", "uvicorn.error")))
    assert "Dashboard session started" in logged and "Team invite made" in logged
    # A JWT's signature is its last part: the part that makes it a credential.
    for secret in (link.rsplit(".", 1)[1], session.rsplit(".", 1)[1], code,
                   "aistinv_wrong-code"):
        assert secret not in logged


async def test_a_session_does_not_outlive_the_servers_key(server_url, monkeypatch):
    """The key is in memory (ADR-0010), so a restart signs every browser out."""
    async with _browser(server_url, await _join(server_url, "dimitris")) as browser:
        from aistack.services.transfer_ticket import SIGNING_KEY_BYTES, TicketSigner
        monkeypatch.setattr(application_context, "_ticket_signer",
                            TicketSigner(b"k" * SIGNING_KEY_BYTES))

        assert (await browser.get("/api/state")).status_code == 401


async def test_a_session_ends_when_its_users_last_computer_is_taken_off_the_server(
        server_url, session_factory):
    """How an operator removes someone: their machines are deleted (docs/OPERATING.md)."""
    async with _browser(server_url, await _join(server_url, "dimitris")) as browser:
        with session_factory.begin() as session:
            session.execute(delete(MachineSkill))
            session.execute(delete(Machine))

        assert (await browser.get("/api/state")).status_code == 401
        assert (await _post(browser, "/teams", name="acme")).status_code == 401
