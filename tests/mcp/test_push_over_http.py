import logging

import httpx
import pytest
from fastmcp.exceptions import ToolError
from sqlalchemy import delete, select

from aistack.bootstrap.context import application_context
from aistack.db.models.machine import Machine
from aistack.db.models.machine_skill import MachineSkill
from aistack.db.models.skill import Skill
from aistack.db.models.skill_file import SkillFile
from aistack.db.models.skill_version import SkillVersion
from aistack.services.skill_archive import MAX_ARCHIVE_BYTES
from aistack.services.transfer_ticket import TicketSigner
from tests.archives import skill_archive
from tests.conftest import INVITE_CODE
from tests.mcp.conftest import client_for, share_with_everyone
from tests.teams import SERVER_TEAM

pytestmark = pytest.mark.anyio


async def _join(server_url, username="dimitris", machine_name="macbook") -> str:
    async with client_for(server_url, INVITE_CODE) as client:
        joined = await client.call_tool("join", {"username": username,
                                                 "machine_name": machine_name, "os": "MACOS"})
    return joined.structured_content["token"]


async def _upload_url(server_url, token, name="wizard", **arguments) -> str:
    async with client_for(server_url, token) as client:
        result = await client.call_tool("push_skill", {"name": name, **arguments})
    return result.structured_content["upload_url"]


async def _put(url: str, body: bytes) -> httpx.Response:
    async with httpx.AsyncClient() as http:
        return await http.put(url, content=body)


async def test_push_skill_then_upload_stores_the_skill(server_url, session_factory):
    """The whole flow: a tool call for the URL, one PUT, rows in the database."""
    token = await _join(server_url)
    async with client_for(server_url, token) as client:
        issued = (await client.call_tool("push_skill", {
            "name": "wizard", "origin": "https://github.com/mattpocock/skills",
        })).structured_content

    assert issued["name"] == "wizard"
    assert issued["expires_in_seconds"] == 300
    assert issued["upload_url"].startswith(server_url.removesuffix("/mcp") + "/transfer/upload/")

    response = await _put(issued["upload_url"], skill_archive(
        files={"scripts/run.sh": "#!/bin/sh\necho hi\n"}, executable=frozenset({"scripts/run.sh"})))

    assert response.status_code == 200
    assert response.json() == {
        "name": "wizard",
        "revision": 1,
        "created": True,
        "unchanged": False,
        "content_hash": response.json()["content_hash"],
        "file_count": 2,
        "previous_pushed_by": None,
        "stored_origin": "https://github.com/mattpocock/skills",
    }
    with session_factory() as session:
        assert session.scalar(select(Skill.name)) == "wizard"
        assert session.scalar(select(SkillVersion.content_hash)) == response.json()["content_hash"]
        assert sorted(session.scalars(select(SkillFile.path))) == ["SKILL.md", "scripts/run.sh"]
        assert session.scalar(select(MachineSkill.enabled)) is True


async def test_a_second_user_pushing_the_same_name_gets_a_skill_of_their_own(server_url):
    """A push lands in the pusher's own skills, so a namesake is nobody's predecessor."""
    first = await _join(server_url, "dimitris", "macbook")
    second = await _join(server_url, "maria", "laptop")
    await _put(await _upload_url(server_url, first), skill_archive())

    response = await _put(await _upload_url(server_url, second),
                          skill_archive(files={"notes.md": "different\n"}))

    assert response.json()["revision"] == 1
    assert response.json()["created"] is True
    assert response.json()["previous_pushed_by"] is None
    assert "possibly_unrelated" not in response.json()


async def test_sharing_over_a_skill_never_taken_is_told_who_was_there_first(server_url):
    """The warning a push used to carry, now at the moment a namesake can be replaced (#35)."""
    first = await _join(server_url, "dimitris", "macbook")
    second = await _join(server_url, "maria", "laptop")
    await _put(await _upload_url(server_url, first), skill_archive())
    await share_with_everyone(server_url, first)
    await _put(await _upload_url(server_url, second),
               skill_archive(files={"notes.md": "different\n"}))

    shared = await share_with_everyone(server_url, second)

    assert shared == {
        "name": "wizard",
        "team": SERVER_TEAM,
        "group": None,
        "revision": 2,
        "created": False,
        "unchanged": False,
        "previous_pushed_by": "dimitris",
        "possibly_unrelated": True,
    }


async def test_no_file_content_crosses_mcp(server_url):
    """ADR-0010: the tool takes a name and returns a URL, and that is all it can do."""
    token = await _join(server_url)
    async with client_for(server_url, token) as client:
        push_skill = next(tool for tool in await client.list_tools() if tool.name == "push_skill")

    assert set(push_skill.inputSchema["properties"]) == {"name", "origin", "harness"}


@pytest.mark.parametrize("name", ["Wizard", "../wizard", "code review", "x" * 65])
async def test_a_bad_name_is_refused_before_any_url_is_issued(server_url, name):
    token = await _join(server_url)

    async with client_for(server_url, token) as client:
        with pytest.raises(ToolError):
            await client.call_tool("push_skill", {"name": name})


async def test_a_rejected_archive_answers_with_the_sentence_to_act_on(server_url,
                                                                    session_factory):
    token = await _join(server_url)

    response = await _put(await _upload_url(server_url, token),
                          skill_archive(files={"logo.png": b"\x89PNG\r\n\x1a\n\x00"}))

    assert response.status_code == 400
    assert response.json() == {"error": response.json()["error"]}
    assert "'logo.png' is not UTF-8 text" in response.json()["error"]
    with session_factory() as session:
        assert session.scalars(select(Skill)).all() == []


async def test_a_body_that_is_not_an_archive_is_refused(server_url):
    token = await _join(server_url)

    response = await _put(await _upload_url(server_url, token), b"SKILL.md contents, sent raw")

    assert response.status_code == 400
    assert "not gzip data" in response.json()["error"]


async def test_an_oversized_upload_is_cut_off(server_url, session_factory):
    token = await _join(server_url)

    response = await _put(await _upload_url(server_url, token), b"\x00" * (MAX_ARCHIVE_BYTES + 1))

    assert response.status_code == 400
    assert "larger than" in response.json()["error"]
    with session_factory() as session:
        assert session.scalars(select(Skill)).all() == []


@pytest.mark.parametrize("ticket", ["not-a-ticket", "a.b.c", "x" * 400])
async def test_a_forged_ticket_is_refused_before_the_body_is_looked_at(server_url, ticket,
                                                                     session_factory):
    await _join(server_url)

    response = await _put(f"{server_url.removesuffix('/mcp')}/transfer/upload/{ticket}",
                          skill_archive())

    assert response.status_code == 403
    assert "not valid" in response.json()["error"]
    assert ticket not in response.text
    with session_factory() as session:
        assert session.scalars(select(Skill)).all() == []


async def test_an_expired_ticket_is_refused(server_url, monkeypatch):
    token = await _join(server_url)
    url = await _upload_url(server_url, token)
    ticket = url.rsplit("/", 1)[1]
    # Re-sign the same claims as already expired, with the server's own key.
    signer = application_context.get_ticket_signer()
    expired = TicketSigner(signer._key, lifetime_seconds=-1).sign_upload(
        signer.verified_upload(ticket))

    response = await _put(url.replace(ticket, expired), skill_archive())

    assert response.status_code == 403
    assert "expired" in response.json()["error"]
    assert "push_skill" in response.json()["error"]


async def test_a_ticket_from_before_a_restart_is_refused(server_url, monkeypatch):
    """The signing key lives in memory, so a new process honors no old URL."""
    token = await _join(server_url)
    url = await _upload_url(server_url, token)
    monkeypatch.setattr(application_context, "_ticket_signer", TicketSigner(b"k" * 32))

    response = await _put(url, skill_archive())

    assert response.status_code == 403


async def test_a_machine_revoked_after_the_url_was_issued_cannot_use_it(server_url,
                                                                      session_factory):
    token = await _join(server_url)
    url = await _upload_url(server_url, token)
    with session_factory.begin() as session:
        session.execute(delete(Machine))

    response = await _put(url, skill_archive())

    assert response.status_code == 403
    assert "no longer registered" in response.json()["error"]


async def test_a_machine_given_a_new_token_after_the_url_was_issued_cannot_use_it(
        server_url, session_factory):
    """The operator's lost-laptop rotation keeps the machine's id, so the id alone is not
    enough: the URL names the token that minted it (ADR-0027)."""
    token = await _join(server_url)
    url = await _upload_url(server_url, token)
    with session_factory.begin() as session:
        session.scalar(select(Machine)).token_hash = "0" * 64

    response = await _put(url, skill_archive())

    assert response.status_code == 403
    assert "no longer registered" in response.json()["error"]
    with session_factory() as session:
        assert session.scalar(select(Skill)) is None


async def test_the_upload_url_is_bound_to_the_name_it_was_issued_for(server_url):
    token = await _join(server_url)

    response = await _put(await _upload_url(server_url, token, name="wizard"),
                          skill_archive("sorcerer"))

    assert response.status_code == 400
    assert "but the push is for 'wizard'" in response.json()["error"]


async def test_the_upload_route_only_answers_put(server_url):
    token = await _join(server_url)
    url = await _upload_url(server_url, token)

    async with httpx.AsyncClient() as http:
        assert (await http.get(url)).status_code == 405
        assert (await http.post(url, content=skill_archive())).status_code == 405


async def test_the_ticket_appears_in_no_log_line(server_url, caplog):
    token = await _join(server_url)

    with caplog.at_level(logging.DEBUG):
        url = await _upload_url(server_url, token)
        accepted = await _put(url, skill_archive())
        rejected = await _put(url, b"not an archive")

    assert accepted.status_code == 200 and rejected.status_code == 400
    ticket = url.rsplit("/", 1)[1]
    # AIStack's own loggers, plus the framework's. httpx is this test's client, and uvicorn's
    # access logger only looks alive under pytest (see test_http_server_config.py).
    messages = [record.getMessage() for record in caplog.records
                if record.name.startswith(("aistack", "fastmcp", "mcp.server", "uvicorn.error"))]
    assert any("Skill pushed" in message for message in messages)
    assert any("upload_skill failed" in message for message in messages)
    for message in messages:
        assert ticket not in message
        # The signature alone is enough to recognize a leak of any part of it.
        assert ticket.split(".")[2] not in message


async def test_an_unexpected_failure_is_masked(server_url, monkeypatch):
    token = await _join(server_url)
    url = await _upload_url(server_url, token)

    def explode(*args, **kwargs):
        raise RuntimeError("psycopg.OperationalError: password authentication failed for 'x'")

    monkeypatch.setattr("aistack.services.skill_service.push", explode)

    response = await _put(url, skill_archive())

    assert response.status_code == 500
    assert response.json() == {"error": "upload_skill failed unexpectedly."}
