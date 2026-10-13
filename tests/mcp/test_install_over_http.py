import io
import logging
import tarfile

import httpx
import pytest
from fastmcp.exceptions import ToolError
from sqlalchemy import select

from aistack.db.models.machine_skill import MachineSkill
from tests.archives import skill_archive, skill_document
from tests.mcp.conftest import call as _call
from tests.mcp.conftest import client_for
from tests.mcp.conftest import join as _join
from tests.mcp.conftest import push as _push
from tests.mcp.conftest import second_machine, share_with_everyone
from tests.teams import SERVER_TEAM

pytestmark = pytest.mark.anyio


async def _download(url: str) -> httpx.Response:
    async with httpx.AsyncClient() as http:
        return await http.get(url)


def _extracted(archive: bytes) -> dict[str, tuple[bytes, bool]]:
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
        return {member.name: (tar.extractfile(member).read(), bool(member.mode & 0o111))
                for member in tar}


async def test_a_skill_shared_from_one_machine_installs_on_another(server_url, session_factory):
    """The product, end to end: push and share on A, list and take on B, same bytes."""
    machine_a = await _join(server_url, "dimitris", "macbook")
    machine_b = await _join(server_url, "maria", "laptop")
    script = "#!/bin/sh\r\necho hi\r\n"
    pushed = await _push(server_url, machine_a, files={"scripts/run.sh": script},
                         executable=frozenset({"scripts/run.sh"}))
    await share_with_everyone(server_url, machine_a)

    listing = await _call(server_url, machine_b, "list_skills")
    assert listing == {"skills": [{
        "name": "wizard",
        "team": SERVER_TEAM,
        "group": None,
        "description": "Walks a human through steps.",
        "revision": 1,
        "pushed_by": "dimitris",
    }]}

    skill = await _call(server_url, machine_b, "get_skill", name="wizard", team=SERVER_TEAM)
    assert skill["revision"] == 1
    assert skill["version"] is None
    assert skill["pushed_by"] == "dimitris"
    assert skill["content_hash"] == pushed["content_hash"]
    assert skill["expires_in_seconds"] == 300
    assert [file["path"] for file in skill["files"]] == ["SKILL.md", "scripts/run.sh"]

    response = await _download(skill["download_url"])
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/gzip"
    assert response.headers["content-disposition"] == 'attachment; filename="wizard.tgz"'
    assert _extracted(response.content) == {
        "SKILL.md": (skill_document().encode(), False),
        "scripts/run.sh": (script.encode(), True),
    }

    with session_factory() as session:
        assert session.scalars(select(MachineSkill.enabled)).all() == [True, True]


async def test_get_skill_carries_no_file_content(server_url):
    """ADR-0010: paths, digests, and a URL. The bytes take the other road."""
    token = await _join(server_url)
    await _push(server_url, token)

    skill = await _call(server_url, token, "get_skill", name="wizard")

    assert set(skill["files"][0]) == {"path", "sha256", "executable"}
    assert skill_document() not in str(skill)


async def test_list_skills_raises_its_own_result_ceiling(server_url):
    """A few hundred descriptions pass Claude Code's default limit; the listing is the search."""
    token = await _join(server_url)

    async with client_for(server_url, token) as client:
        list_skills = next(tool for tool in await client.list_tools()
                           if tool.name == "list_skills")

    assert list_skills.meta["anthropic/maxResultSizeChars"] == 500_000


async def test_a_download_url_keeps_serving_the_revision_it_was_issued_for(server_url):
    token = await _join(server_url)
    await _push(server_url, token, files={"notes.md": "one\n"})
    skill = await _call(server_url, token, "get_skill", name="wizard")
    await _push(server_url, token, files={"notes.md": "two\n"})

    response = await _download(skill["download_url"])

    assert _extracted(response.content)["notes.md"][0] == b"one\n"


async def test_an_upload_url_cannot_download_and_a_download_url_cannot_upload(server_url):
    token = await _join(server_url)
    await _push(server_url, token)
    upload_ticket = (await _call(server_url, token, "push_skill",
                                 name="wizard"))["upload_url"].rsplit("/", 1)[1]
    download_url = (await _call(server_url, token, "get_skill", name="wizard"))["download_url"]
    base, download_ticket = download_url.rsplit("/", 1)

    crossed_download = await _download(f"{base}/{upload_ticket}")
    async with httpx.AsyncClient() as http:
        crossed_upload = await http.put(
            f"{base.removesuffix('/download')}/upload/{download_ticket}",
            content=skill_archive())

    assert crossed_download.status_code == 403
    assert crossed_upload.status_code == 403
    assert "get_skill" in crossed_download.json()["error"]


@pytest.mark.parametrize("ticket", ["not-a-ticket", "a.b.c"])
async def test_a_forged_download_ticket_is_refused(server_url, ticket):
    await _join(server_url)

    response = await _download(f"{server_url.removesuffix('/mcp')}/transfer/download/{ticket}")

    assert response.status_code == 403
    assert response.json() == {"error": response.json()["error"]}


async def test_get_skill_on_an_unknown_name_is_a_tool_error_that_says_where_to_look(server_url):
    token = await _join(server_url)

    async with client_for(server_url, token) as client:
        with pytest.raises(ToolError) as rejection:
            await client.call_tool("get_skill", {"name": "sorcerer"})

    assert "list_skills" in str(rejection.value)


async def test_remove_then_reinstall(server_url, session_factory):
    token = await _join(server_url)
    await _push(server_url, token)

    disabled = await _call(server_url, token, "disable_skill", name="wizard")
    assert disabled == {"name": "wizard", "enabled": False}
    with session_factory() as session:
        assert session.scalars(select(MachineSkill.enabled)).all() == [False]

    await _call(server_url, token, "get_skill", name="wizard")
    with session_factory() as session:
        assert session.scalars(select(MachineSkill.enabled)).all() == [True]


async def test_disabling_a_skill_never_enabled_here_is_refused(server_url):
    pusher = await _join(server_url)
    other = await second_machine(server_url, pusher)
    await _push(server_url, pusher)

    async with client_for(server_url, other) as client:
        with pytest.raises(ToolError) as rejection:
            await client.call_tool("disable_skill", {"name": "wizard"})

    assert "never enabled on this machine" in str(rejection.value)


async def test_the_download_ticket_appears_in_no_log_line(server_url, caplog):
    token = await _join(server_url)
    await _push(server_url, token)

    with caplog.at_level(logging.DEBUG):
        skill = await _call(server_url, token, "get_skill", name="wizard")
        await _download(skill["download_url"])

    ticket = skill["download_url"].rsplit("/", 1)[1]
    messages = [record.getMessage() for record in caplog.records
                if record.name.startswith(("aistack", "fastmcp", "mcp.server", "uvicorn.error"))]
    assert any("Skill downloaded" in message for message in messages)
    for message in messages:
        assert ticket.split(".")[2] not in message
