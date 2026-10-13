import pathlib

import httpx
import pytest

from aistack.services.skill_archive import ArchivedFile
from aistack.services.skill_validation import validated_skill
from tests.archives import local_digests, skill_archive
from tests.conftest import INVITE_CODE
from tests.mcp.conftest import client_for

pytestmark = pytest.mark.anyio

SYNC_SKILL = pathlib.Path(__file__).parents[2] / "skills" / "sync-aistack"


async def _join(server_url, username="dimitris", machine_name="macbook") -> str:
    async with client_for(server_url, INVITE_CODE) as client:
        joined = await client.call_tool("join", {"username": username,
                                                 "machine_name": machine_name, "os": "MACOS"})
    return joined.structured_content["token"]


async def _call(server_url, token, tool, **arguments) -> dict:
    async with client_for(server_url, token) as client:
        return (await client.call_tool(tool, arguments)).structured_content


async def _push(server_url, token, name="wizard", **archive) -> dict:
    issued = await _call(server_url, token, "push_skill", name=name)
    async with httpx.AsyncClient() as http:
        return (await http.put(issued["upload_url"],
                               content=skill_archive(name, **archive))).json()


async def test_an_edit_pushed_on_one_machine_reaches_the_other_through_sync(server_url):
    """The reason the product exists: push on A, sync on B, B is told to update."""
    machine_a = await _join(server_url, "dimitris", "macbook")
    machine_b = await _join(server_url, "maria", "laptop")
    await _push(server_url, machine_a, files={"notes.md": "one\n"})
    await _call(server_url, machine_b, "get_skill", name="wizard")
    on_machine_b = {"wizard": local_digests(files={"notes.md": "one\n"})}

    before = await _call(server_url, machine_b, "sync", local=on_machine_b)
    assert before == {"install": [], "update": [], "up_to_date": 1}

    await _push(server_url, machine_a, files={"notes.md": "two\n"})

    after = await _call(server_url, machine_b, "sync", local=on_machine_b)
    assert after == {
        "install": [],
        "update": [{"name": "wizard", "from_revision": 1, "to_revision": 2,
                    "pushed_by": "dimitris"}],
        "up_to_date": 0,
    }


async def test_a_fresh_machine_is_told_to_install_what_it_enabled(server_url):
    machine_a = await _join(server_url, "dimitris", "macbook")
    machine_b = await _join(server_url, "maria", "laptop")
    await _push(server_url, machine_a)
    await _call(server_url, machine_b, "get_skill", name="wizard")

    report = await _call(server_url, machine_b, "sync", local={})

    assert report["install"] == [{"name": "wizard", "revision": 1, "pushed_by": "dimitris"}]


async def test_sync_returns_metadata_and_never_file_content(server_url):
    token = await _join(server_url)
    await _push(server_url, token, files={"notes.md": "a recognizable line of content\n"})

    report = await _call(server_url, token, "sync", local={})

    assert "a recognizable line of content" not in str(report)
    assert set(report["install"][0]) == {"name", "revision", "pushed_by"}


async def test_sync_takes_digests_and_nothing_else(server_url):
    token = await _join(server_url)

    async with client_for(server_url, token) as client:
        sync = next(tool for tool in await client.list_tools() if tool.name == "sync")

    assert set(sync.inputSchema["properties"]) == {"local"}
    assert sync.inputSchema["required"] == ["local"]


def test_the_shipped_sync_skill_is_one_the_vault_would_accept():
    """setup-aistack writes this folder to disk, so it has to pass the rules it will meet."""
    files = [ArchivedFile(str(path.relative_to(SYNC_SKILL)), path.read_bytes(), False)
             for path in SYNC_SKILL.rglob("*") if path.is_file()]

    skill = validated_skill("sync-aistack", files)

    assert skill.description.startswith("Sync this machine's skills")
    assert "sync aistack" in skill.description
