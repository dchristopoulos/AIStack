"""The dashboard from a browser's side: sign in with a link, then the JSON routes."""

import hashlib
import io
import logging
import re
import secrets
import tarfile
import uuid
from contextlib import asynccontextmanager

import httpx
import pytest
from sqlalchemy import delete, select

from aistack.api.dashboard import REQUEST_HEADER, SESSION_COOKIE
from aistack.bootstrap.context import application_context
from aistack.db.models.machine import Machine
from aistack.db.models.machine_skill import MachineSkill
from aistack.mcp.mcp import mcp
from tests.archives import local_digests, skill_archive
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
    assert state["user"] == {"username": "dimitris", "full_name": None}
    assert [machine["name"] for machine in state["machines"]] == ["laptop"]


async def test_the_page_may_load_nothing_from_anywhere_else(server_url):
    async with _browser(server_url, await _join(server_url, "dimitris")) as browser:
        page = await browser.get("/app")

    policy = page.headers["content-security-policy"]
    assert "default-src 'none'" in policy and "connect-src 'self'" in policy
    assert "frame-ancestors 'none'" in policy
    assert page.headers["referrer-policy"] == "no-referrer"
    assert page.headers["cache-control"] == "no-store"
    # STD-13: only the page's own scripts run, by hash, and no banner names the server.
    scripts = re.search(r"script-src ([^;]*);", policy).group(1).split()
    assert scripts and all(source.startswith("'sha256-") for source in scripts)
    assert "server" not in page.headers


@pytest.mark.parametrize("path", ["/app", "/api/state", "/api/library.tar.gz"])
async def test_nothing_is_served_without_a_session(server_url, path):
    async with httpx.AsyncClient(base_url=_base(server_url)) as stranger:
        response = await stranger.get(path)

    assert response.status_code == 401
    assert "open my aistack dashboard" in response.text
    assert "dimitris" not in response.text


async def test_a_person_downloads_their_library_as_its_skills_folders(server_url):
    """STD-15: on a server, nobody could take their Library elsewhere."""
    token = await _join(server_url, "dimitris")
    await _push(server_url, token, "wizard", files={"scripts/run.sh": "echo hi\n"},
                executable=frozenset({"scripts/run.sh"}))
    await _push(server_url, token, "notes")
    async with _browser(server_url, token) as browser:
        response = await browser.get("/api/library.tar.gz")
        state = await _state(browser)

    assert response.status_code == 200
    assert "aistack-library.tar.gz" in response.headers["content-disposition"]
    with tarfile.open(fileobj=io.BytesIO(response.content), mode="r:gz") as archive:
        members = {member.name: member for member in archive.getmembers()}
        digests: dict[str, dict[str, str]] = {}
        for name, member in members.items():
            skill, path = name.split("/", 1)
            digests.setdefault(skill, {})[path] = hashlib.sha256(
                archive.extractfile(member).read()).hexdigest()
    assert members["wizard/scripts/run.sh"].mode & 0o111
    stored = {skill["name"]: skill for skill in state["skills"]}
    assert sorted(digests) == sorted(stored) == ["notes", "wizard"]
    # Each folder is exactly the latest revision: it hashes to what the Library holds.
    async with client_for(server_url, token) as client:
        report = (await client.call_tool("sync", {"local": digests})).structured_content
    assert report["up_to_date"] == 2 and report["ask"] == [] and report["backup"] == []


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
    assert "has been used" in again.text and "Not connected yet" not in again.text


async def test_a_link_opened_again_by_the_browser_it_signed_in_leads_to_the_page(server_url):
    """UX-02: the browser opens the link and the person clicks it too."""
    token = await _join(server_url, "dimitris")
    link = httpx.URL((await _call(server_url, token, "open_dashboard"))["url"]).path
    async with httpx.AsyncClient(base_url=_base(server_url)) as browser:
        await browser.get(link)
        again = await browser.get(link)
        state = await browser.get("/api/state")

    assert again.status_code == 303 and again.headers["location"] == "/app"
    assert "set-cookie" not in again.headers
    assert state.status_code == 200


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


async def test_signing_out_ends_the_session_wherever_its_cookie_was_copied(server_url):
    """A copy taken from devtools or by an extension stops working too (ADR-0027)."""
    async with _browser(server_url, await _join(server_url, "dimitris")) as browser:
        copied = browser.cookies[SESSION_COOKIE]
        await _post(browser, "/logout")

    async with httpx.AsyncClient(base_url=_base(server_url)) as elsewhere:
        response = await elsewhere.get("/api/state", cookies={SESSION_COOKIE: copied})

    assert response.status_code == 401


async def test_somebody_elses_link_asks_before_it_replaces_the_session(server_url):
    """A link anyone can mint for their own account must not quietly become the victim's
    dashboard, where they would paste an invite code meant for themselves."""
    attacker = await _join(server_url, "mallory")
    sent_link = httpx.URL((await _call(server_url, attacker, "open_dashboard"))["url"]).path

    async with _browser(server_url, await _join(server_url, "dimitris")) as victim:
        asked = await victim.get(sent_link)
        still = await _state(victim)
        switch = re.search(r'"(/app/login/[^"]+)"', asked.text).group(1)
        switched = await victim.post(switch, headers=HEADERS)
        after = await _state(victim)

    assert asked.status_code == 200 and "set-cookie" not in asked.headers
    assert "signed in as <strong>dimitris</strong>" in asked.text
    assert "Sign in as mallory" in asked.text
    assert still["user"]["username"] == "dimitris"
    assert switched.status_code == 200
    assert after["user"]["username"] == "mallory"


async def test_switching_needs_the_header_and_a_link_that_is_still_good(server_url):
    attacker = await _join(server_url, "mallory")
    link = httpx.URL((await _call(server_url, attacker, "open_dashboard"))["url"]).path

    async with httpx.AsyncClient(base_url=_base(server_url)) as browser:
        forged = await browser.post(link)
        used = await browser.post(link, headers=HEADERS)
        again = await browser.post(link, headers=HEADERS)

    assert forged.status_code == 400 and "set-cookie" not in forged.headers
    assert used.status_code == 200
    assert again.status_code == 401 and "set-cookie" not in again.headers


async def test_opening_your_own_link_again_signs_in_without_asking(server_url):
    token = await _join(server_url, "dimitris")
    async with _browser(server_url, token) as browser:
        link = httpx.URL((await _call(server_url, token, "open_dashboard"))["url"]).path
        again = await browser.get(link)

    assert again.status_code == 303


def _rotate(session_factory, machine_name):
    """The operator's lost-laptop step in docs/OPERATING.md: a new token for one computer."""
    with session_factory.begin() as session:
        machine = session.scalar(select(Machine).where(Machine.name == machine_name))
        machine.token_hash = hashlib.sha256(secrets.token_bytes(32)).hexdigest()


async def test_a_session_ends_when_the_computer_that_opened_it_gets_a_new_token(
        server_url, session_factory):
    """The person still has another computer, so the account stays; the thief's session goes."""
    laptop = await _join(server_url, "dimitris", machine_name="laptop")
    added = await _call(server_url, laptop, "add_machine", name="desktop", os="LINUX")
    desktop = re.search(r"Bearer (aist_[\w-]+)", added["command"]).group(1)

    async with _browser(server_url, laptop) as thief, _browser(server_url, desktop) as owner:
        _rotate(session_factory, "laptop")

        assert (await thief.get("/api/state")).status_code == 401
        assert (await _post(thief, "/teams", name="acme")).status_code == 401
        assert (await owner.get("/api/state")).status_code == 200


async def test_a_session_ends_when_the_computer_that_opened_it_is_deleted(
        server_url, session_factory):
    laptop = await _join(server_url, "dimitris", machine_name="laptop")
    await _call(server_url, laptop, "add_machine", name="desktop", os="LINUX")

    async with _browser(server_url, laptop) as thief:
        with session_factory.begin() as session:
            session.execute(delete(Machine).where(Machine.name == "laptop"))

        assert (await thief.get("/api/state")).status_code == 401


async def test_a_link_from_a_computer_that_has_since_lost_its_token_signs_nobody_in(
        server_url, session_factory):
    laptop = await _join(server_url, "dimitris", machine_name="laptop")
    await _call(server_url, laptop, "add_machine", name="desktop", os="LINUX")
    link = (await _call(server_url, laptop, "open_dashboard"))["url"]
    _rotate(session_factory, "laptop")

    async with httpx.AsyncClient(base_url=_base(server_url)) as thief:
        response = await thief.get(link)

    assert response.status_code == 401 and "set-cookie" not in response.headers


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
            "code-review", [{"machine": machine, "harness": "claude_code", "revision": None,
                             "project": None}],
            False)

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


async def test_an_admin_outside_a_private_group_is_sent_it_without_its_skills(server_url):
    dimitris_token = await _join(server_url, "dimitris")
    maria_token = await _join(server_url, "maria")
    eve_token = await _join(server_url, "eve")
    await _push(server_url, dimitris_token, "pentest")

    async with _browser(server_url, dimitris_token) as dimitris, \
            _browser(server_url, maria_token) as maria, \
            _browser(server_url, eve_token) as eve:
        await _post(dimitris, "/teams", name="acme")
        for person in (maria, eve):
            code = (await _post(dimitris, "/teams/acme/invite")).json()["code"]
            await _post(person, "/teams/join", code=code)
        await _post(dimitris, "/teams/acme/groups", name="backend")
        await _post(dimitris, "/teams/acme/groups", name="vault", private=True)
        await _post(dimitris, "/teams/acme/group/members", path="vault", username="eve",
                    member=True)
        await _post(dimitris, "/skills/pentest/share", team="acme", group="vault")
        await _post(dimitris, "/teams/acme/members/maria", role="ADMIN")

        async def seen(browser) -> tuple[list[tuple[str, bool]], list[str]]:
            acme = next(team for team in (await _state(browser))["teams"]
                        if team["name"] == "acme")
            return ([(group["path"], group["sees_skills"]) for group in acme["groups"]],
                    [skill["name"] for skill in acme["skills"]])

        # Maria is an admin outside vault: shown it to manage, and sent none of its skills.
        assert await seen(maria) == ([("backend", True), ("vault", False)], [])
        refused = await _post(maria, "/teams/acme/group", path="vault", subscribed=False)
        assert refused.status_code == 404
        # Eve is a member inside it, and Dimitris an admin inside it.
        for inside in (eve, dimitris):
            assert await seen(inside) == ([("backend", True), ("vault", True)], ["pentest"])


async def test_taking_over_a_namesake_of_your_own_waits_for_replace(server_url):
    dimitris_token = await _join(server_url, "dimitris")
    maria_token = await _join(server_url, "maria")
    await _push(server_url, maria_token, "code-review", files={"notes.md": "maria's own\n"})
    await _push(server_url, dimitris_token, "code-review", files={"notes.md": "dimitris's\n"})
    async with _browser(server_url, dimitris_token) as dimitris, \
            _browser(server_url, maria_token) as maria:
        await _post(dimitris, "/teams", name="acme")
        code = (await _post(dimitris, "/teams/acme/invite")).json()["code"]
        await _post(maria, "/teams/join", code=code)
        await _post(dimitris, "/skills/code-review/share", team="acme")

        refused = await _post(maria, "/teams/acme/take", name="code-review")
        assert refused.status_code == 409
        assert "your own 'code-review' (revision 1, last pushed by maria)" in refused.json()[
            "error"]
        assert (await _post(maria, "/teams/acme/take", name="code-review",
                            replace="yes")).status_code == 400
        assert (await _state(maria))["skills"][0]["pushed_by"] == "maria"

        assert (await _post(maria, "/teams/acme/take", name="code-review",
                            replace=True)).status_code == 200
        mine = (await _state(maria))["skills"][0]
        assert (mine["revision"], mine["pushed_by"], mine["source"]["team"]) == (
            2, "dimitris", "acme")


async def _team_of_two(server_url, dimitris, maria) -> None:
    await _post(dimitris, "/teams", name="acme")
    code = (await _post(dimitris, "/teams/acme/invite")).json()["code"]
    await _post(maria, "/teams/join", code=code)


async def test_an_offered_update_shows_its_changed_lines_before_it_is_taken(server_url):
    """IMP-08: the offer was a revision number and a name, and reading it meant taking it."""
    dimitris_token = await _join(server_url, "dimitris")
    maria_token = await _join(server_url, "maria")
    await _push(server_url, dimitris_token, "code-review", files={"notes.md": "one\n"})
    async with _browser(server_url, dimitris_token) as dimitris, \
            _browser(server_url, maria_token) as maria:
        await _team_of_two(server_url, dimitris, maria)
        await _post(dimitris, "/skills/code-review/share", team="acme")
        await _post(maria, "/teams/acme/take", name="code-review")
        await _push(server_url, dimitris_token, "code-review",
                    files={"notes.md": "one\nAlso check migrations.\n", "extra.md": "new"})
        await _post(dimitris, "/skills/code-review/share", team="acme")

        changes = (await maria.get("/api/teams/acme/skills/code-review/changes")).json()

        assert (changes["from_revision"], changes["to_revision"], changes["pushed_by"],
                changes["truncated"]) == (1, 2, "dimitris", False)
        assert [(file["path"], file["change"]) for file in changes["files"]] == [
            ("extra.md", "added"), ("notes.md", "changed")]
        assert "+Also check migrations.\n" in changes["files"][1]["diff"]
        # Looking took nothing.
        assert (await _state(maria))["skills"][0]["revision"] == 1


async def test_an_older_revision_comes_back_as_the_newest_and_every_computer_follows(
        server_url):
    """PH-08: 'it stays in your history' promised a way back that nothing offered."""
    token = await _join(server_url, "maria")
    await _push(server_url, token, files={"notes.md": "one\n"})
    await _push(server_url, token, files={"notes.md": "two\n"})
    async with _browser(server_url, token) as maria:
        history = (await maria.get("/api/skills/wizard/history")).json()["revisions"]
        assert [(entry["revision"], entry["pushed_by"], entry["files"]) for entry in history] == [
            (2, "maria", 2), (1, "maria", 2)]

        restored = await _post(maria, "/skills/wizard/restore", revision=1)
        assert restored.json() == {"revision": 3, "unchanged": False}
        assert (await _post(maria, "/skills/wizard/restore", revision=7)).status_code == 404
        assert (await _post(maria, "/skills/wizard/restore", revision="1")).status_code == 400

    report = await _call(server_url, token, "sync",
                         local={"wizard": local_digests(files={"notes.md": "two\n"})})
    assert [(entry["name"], entry["to_revision"]) for entry in report["update"]] == [
        ("wizard", 3)]
    on_disk = await _call(server_url, token, "sync",
                          local={"wizard": local_digests(files={"notes.md": "one\n"})})
    assert on_disk["update"] == [] and on_disk["up_to_date"] == 1


async def test_a_share_over_a_different_skill_is_offered_as_one(server_url):
    """UX-06: teammates who took the original saw an ordinary update."""
    dimitris_token = await _join(server_url, "dimitris")
    maria_token = await _join(server_url, "maria")
    await _push(server_url, dimitris_token, "deploy-steps", files={"notes.md": "ours\n"})
    await _push(server_url, maria_token, "deploy-steps", files={"notes.md": "unrelated\n"})
    async with _browser(server_url, dimitris_token) as dimitris, \
            _browser(server_url, maria_token) as maria:
        await _team_of_two(server_url, dimitris, maria)
        await _post(dimitris, "/skills/deploy-steps/share", team="acme")

        shared = (await _post(maria, "/skills/deploy-steps/share", team="acme")).json()

        assert shared["possibly_unrelated"] is True
        offer = (await _state(dimitris))["skills"][0]["source"]
        assert (offer["update_available"], offer["different_skill"]) == (True, True)

    report = await _call(server_url, dimitris_token, "sync", local={})
    assert [(entry["name"], entry["different_skill"]) for entry in report["team_updates"]] == [
        ("deploy-steps", True)]


async def test_an_admin_runs_a_teams_groups_and_skills_from_the_dashboard(server_url):
    """IMP-04: these admin and destructive paths never ran in any test."""
    tokens = {name: await _join(server_url, name) for name in ("dimitris", "maria", "alex")}
    await _push(server_url, tokens["dimitris"], "wizard")
    await _push(server_url, tokens["dimitris"], "notes")
    async with _browser(server_url, tokens["dimitris"]) as dimitris, \
            _browser(server_url, tokens["maria"]) as maria, \
            _browser(server_url, tokens["alex"]) as alex:
        await _team_of_two(server_url, dimitris, maria)
        code = (await _post(dimitris, "/teams/acme/invite")).json()["code"]
        await _post(alex, "/teams/join", code=code)
        await _post(dimitris, "/teams/acme/groups", name="backend")
        await _post(dimitris, "/teams/acme/group/members", path="backend", username="alex",
                    member=True)
        await _post(dimitris, "/skills/wizard/share", team="acme")
        await _post(dimitris, "/skills/notes/share", team="acme")

        async def sees(browser) -> tuple[list[str], list[str]]:
            acme = next(team for team in (await _state(browser))["teams"]
                        if team["name"] == "acme")
            return ([group["path"] for group in acme["groups"]],
                    [skill["name"] for skill in acme["skills"]])

        # Into the group, which then turns private: Maria, outside it, loses both.
        assert (await _post(dimitris, "/teams/acme/skills/wizard/move",
                            group="backend")).status_code == 200
        assert (await _post(dimitris, "/teams/acme/group", path="backend",
                            private=True)).status_code == 200
        assert await sees(maria) == ([], ["notes"])
        assert await sees(alex) == (["backend"], ["notes", "wizard"])
        listed = await _call(server_url, tokens["maria"], "list_skills", team="acme")
        assert [skill["name"] for skill in listed["skills"]] == ["notes"]
        await _post(dimitris, "/teams/acme/group", path="backend", private=False)
        assert await sees(maria) == (["backend"], ["notes", "wizard"])

        # Unsubscribing is the member's own switch.
        assert (await _post(maria, "/teams/acme/group", path="backend",
                            subscribed=False)).status_code == 200
        backend, = [group for group in next(team for team in (await _state(maria))["teams"]
                                            if team["name"] == "acme")["groups"]]
        assert backend["subscribed"] is False

        # Removing the team's copy leaves Maria's own, now linked to nothing.
        await _post(maria, "/teams/acme/take", name="notes")
        assert (await _post(dimitris, "/teams/acme/skills/notes/remove")).status_code == 200
        mine, = (await _state(maria))["skills"]
        assert (mine["name"], mine["source"]) == ("notes", None)
        assert await sees(maria) == (["backend"], ["wizard"])


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
            await _post(maria, "/teams/acme/delete"),
        ]
        members = next(team for team in (await _state(dimitris))["teams"]
                       if team["name"] == "acme")["members"]

    for refusal in refusals:
        assert refusal.status_code == 400 and "Only an admin" in refusal.json()["error"]
    assert [(member["username"], member["role"]) for member in members] == [
        ("dimitris", "ADMIN"), ("maria", "MEMBER")]


# Every dashboard route that names a team, with a body that is valid apart from the team. A
# new team route fails `test_every_team_route_has_an_outsider_row` until it has a row here,
# which is the decision about what it tells someone outside the team.
OUTSIDER_ROUTES = {
    "/teams/{team}/leave": {},
    "/teams/{team}/delete": {},
    "/teams/{team}/invite": {},
    "/teams/{team}/invites/{invite_id}/cancel": {},
    "/teams/{team}/take": {"name": "wizard"},
    "/teams/{team}/members/{username}": {"role": "ADMIN"},
    "/teams/{team}/members/{username}/remove": {},
    "/teams/{team}/groups": {"name": "x"},
    "/teams/{team}/group": {"path": "x", "subscribed": False},
    "/teams/{team}/group/members": {"path": "x", "username": "dimitris", "member": True},
    "/teams/{team}/group/rename": {"path": "x", "name": "y"},
    "/teams/{team}/group/delete": {"path": "x"},
    "/teams/{team}/skills/{name}/move": {"group": None},
    "/teams/{team}/skills/{name}/remove": {},
    "/skills/{name}/share": {"team": "{team}"},
    # None: a GET, which reads and changes nothing.
    "/teams/{team}/skills/{name}/changes": None,
}
_FILLED = {"{invite_id}": "00000000-0000-0000-0000-000000000000", "{username}": "dimitris",
           "{name}": "wizard"}


def test_every_team_route_has_an_outsider_row():
    registered = {route.path.removeprefix("/api") for route in mcp._additional_http_routes
                  if route.path.startswith("/api/teams/{team}")}

    assert registered == {route for route in OUTSIDER_ROUTES if route.startswith("/teams/")}


async def test_someone_outside_a_team_is_told_what_they_would_be_told_if_it_did_not_exist(
        server_url):
    dimitris_token = await _join(server_url, "dimitris")
    eve_token = await _join(server_url, "eve")
    await _push(server_url, dimitris_token, "wizard")
    await _push(server_url, eve_token, "wizard")
    async with _browser(server_url, dimitris_token) as dimitris, \
            _browser(server_url, eve_token) as eve:
        await _post(dimitris, "/teams", name="acme")
        await _post(dimitris, "/skills/wizard/share", team="acme")

        for path, body in OUTSIDER_ROUTES.items():
            for placeholder, value in _FILLED.items():
                path = path.replace(placeholder, value)
            answers = []
            for team in ("acme", "nowhere"):
                if body is None:
                    response = await eve.get(f"/api{path.replace('{team}', team)}")
                    answers.append((response.status_code,
                                    response.json()["error"].replace(team, "X")))
                    continue
                filled = {key: value.replace("{team}", team) if isinstance(value, str)
                          else value for key, value in body.items()}
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
                                                     "harness": "claude_code", "revision": 1,
                                                     "project": None}]

        await _post(browser, f"/skills/wizard/machines/{desktop}", enabled=True)
        await _post(browser, f"/skills/wizard/machines/{desktop}", enabled=True,
                    harness="agents")
        await _post(browser, f"/skills/wizard/machines/{laptop}", enabled=False)
        assert (await _state(browser))["skills"][0]["placements"] == [
            {"machine": desktop, "harness": "agents", "revision": None, "project": None},
            {"machine": desktop, "harness": "claude_code", "revision": None, "project": None}]

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


# --- a person's own computers ---------------------------------------------------------------

async def _two_computers(server_url):
    laptop = await _join(server_url, "dimitris", machine_name="laptop")
    added = await _call(server_url, laptop, "add_machine", name="desktop", os="LINUX")
    return laptop, re.search(r"Bearer (aist_[\w-]+)", added["command"]).group(1)


def _machine_id(state, name):
    return next(machine["id"] for machine in state["machines"] if machine["name"] == name)


async def test_a_person_removes_their_own_lost_computer_and_its_token_stops_at_once(
        server_url):
    laptop, desktop = await _two_computers(server_url)

    async with _browser(server_url, desktop) as owner:
        laptop_id = _machine_id(await _state(owner), "laptop")
        removed = await _post(owner, f"/machines/{laptop_id}/remove")
        after = await _state(owner)

    assert removed.status_code == 200 and removed.json() == {"removed": "laptop"}
    assert [machine["name"] for machine in after["machines"]] == ["desktop"]
    with pytest.raises(httpx.HTTPStatusError, match="401"):
        await _call(server_url, laptop, "list_skills")


async def test_removing_the_computer_behind_a_session_ends_that_session(server_url):
    laptop, _ = await _two_computers(server_url)

    async with _browser(server_url, laptop) as browser:
        laptop_id = _machine_id(await _state(browser), "laptop")
        assert (await _post(browser, f"/machines/{laptop_id}/remove")).status_code == 200

        assert (await browser.get("/api/state")).status_code == 401


async def test_the_last_computer_cannot_be_removed(server_url):
    async with _browser(server_url, await _join(server_url, "dimitris")) as browser:
        only = _machine_id(await _state(browser), "laptop")
        refused = await _post(browser, f"/machines/{only}/remove")
        still = await _state(browser)

    assert refused.status_code == 409
    assert "your only computer" in refused.json()["error"]
    assert [machine["name"] for machine in still["machines"]] == ["laptop"]


@pytest.mark.parametrize("action,body", [("remove", {}), ("rename", {"name": "mine-now"})])
async def test_somebody_elses_computer_is_one_that_does_not_exist(server_url, action, body):
    maria = await _join(server_url, "maria")
    await _call(server_url, maria, "add_machine", name="desktop", os="LINUX")
    async with _browser(server_url, maria) as browser:
        marias = _machine_id(await _state(browser), "desktop")

    async with _browser(server_url, await _join(server_url, "dimitris")) as browser:
        unknown = str(uuid.uuid4())
        hers = await _post(browser, f"/machines/{marias}/{action}", **body)
        nobodys = await _post(browser, f"/machines/{unknown}/{action}", **body)

    assert hers.status_code == nobodys.status_code == 404
    assert (hers.json()["error"].replace(marias, "?")
            == nobodys.json()["error"].replace(unknown, "?"))


async def test_a_computer_is_renamed_and_names_stay_unique(server_url):
    _, desktop = await _two_computers(server_url)

    async with _browser(server_url, desktop) as browser:
        laptop_id = _machine_id(await _state(browser), "laptop")
        renamed = await _post(browser, f"/machines/{laptop_id}/rename", name="  old laptop ")
        taken = await _post(browser, f"/machines/{laptop_id}/rename", name="desktop")
        names = [machine["name"] for machine in (await _state(browser))["machines"]]

    assert renamed.json() == {"name": "old laptop"}
    assert taken.status_code == 409 and "already have a computer named" in taken.text
    assert names == ["old laptop", "desktop"]


async def test_each_computer_says_when_it_was_added_from_where_and_when_it_last_synced(
        server_url):
    laptop, desktop = await _two_computers(server_url)
    await _call(server_url, laptop, "sync", local={})

    async with _browser(server_url, desktop) as browser:
        before = {machine["name"]: machine for machine in (await _state(browser))["machines"]}
        await _post(browser, f"/machines/{before['laptop']['id']}/remove")
        after = {machine["name"]: machine for machine in (await _state(browser))["machines"]}

    assert before["laptop"]["added_by"] is None and before["desktop"]["added_by"] == "laptop"
    assert before["laptop"]["last_synced"]["claude_code"] is not None
    # It never synced, so it shows no folder at all (UX-07).
    assert before["desktop"]["last_synced"] == {}
    assert before["laptop"]["added_on"] <= before["desktop"]["added_on"]
    # The computer that added it is gone, and that is still worth saying.
    assert after["desktop"]["added_by"] is None and after["desktop"]["added_by_removed"]
