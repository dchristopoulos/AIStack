import pathlib

import httpx
import pytest
from fastmcp.client import BearerAuth, Client, StreamableHttpTransport

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
    assert before == {"install": [], "update": [], "ask": [], "orphans": [], "up_to_date": 1}

    await _push(server_url, machine_a, files={"notes.md": "two\n"})

    after = await _call(server_url, machine_b, "sync", local=on_machine_b)
    assert after == {
        "install": [],
        "update": [{"name": "wizard", "from_revision": 1, "to_revision": 2,
                    "pushed_by": "dimitris"}],
        "ask": [],
        "orphans": [],
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


async def test_every_answer_to_a_question_is_an_existing_tool(server_url, session_factory):
    """Edit locally, get asked, and resolve it each way. No hidden verb is needed."""
    machine_a = await _join(server_url, "dimitris", "macbook")
    machine_b = await _join(server_url, "maria", "laptop")
    await _push(server_url, machine_a)
    await _call(server_url, machine_b, "get_skill", name="wizard")
    edited = {"notes.md": "maria's local edit\n"}
    on_machine_b = {"wizard": local_digests(files=edited), "her-own": local_digests("her-own")}

    report = await _call(server_url, machine_b, "sync", local=on_machine_b)

    assert report["install"] == [] and report["update"] == []
    assert report["orphans"] == ["her-own"]
    assert report["ask"] == [{
        "name": "wizard",
        "desired": "enabled",
        "local": "unknown",
        "local_revision": None,
        "latest_revision": 1,
        "pushed_by": "dimitris",
        "options": [
            {"choice": "enable", "overwrites_local": True, "loses_local_edits": True},
            {"choice": "push", "overwrites_local": False, "loses_local_edits": False},
            {"choice": "skip", "overwrites_local": False, "loses_local_edits": False},
        ],
    }]

    # Answer "push": her edit becomes revision 2 and the question is gone.
    pushed = await _push(server_url, machine_b, files=edited)
    assert pushed["revision"] == 2
    after_push = await _call(server_url, machine_b, "sync", local=on_machine_b)
    assert after_push["ask"] == [] and after_push["up_to_date"] == 1

    # Answer "push" for the orphan: it stops being one.
    await _push(server_url, machine_b, name="her-own")
    assert (await _call(server_url, machine_b, "sync", local=on_machine_b))["orphans"] == []

    # Machine A is now behind, unmodified: a silent update, not a question.
    on_machine_a = {"wizard": local_digests()}
    behind = await _call(server_url, machine_a, "sync", local=on_machine_a)
    assert behind["ask"] == []
    assert behind["update"] == [{"name": "wizard", "from_revision": 1, "to_revision": 2,
                                 "pushed_by": "maria"}]


async def test_removing_and_then_finding_the_folder_again_is_a_question(server_url):
    token = await _join(server_url)
    await _push(server_url, token)
    await _call(server_url, token, "disable_skill", name="wizard")

    report = await _call(server_url, token, "sync", local={"wizard": local_digests()})

    assert [(entry["name"], entry["desired"], entry["local"]) for entry in report["ask"]] == [
        ("wizard", "disabled", "current")]
    assert [option["choice"] for option in report["ask"][0]["options"]] == ["enable", "remove"]

    # Answer "enable": get_skill flips the row back and the next sync is quiet.
    await _call(server_url, token, "get_skill", name="wizard")
    quiet = await _call(server_url, token, "sync", local={"wizard": local_digests()})
    assert quiet["ask"] == [] and quiet["up_to_date"] == 1


async def test_sync_declares_no_elicitation(server_url):
    """ADR-0012: questions are data in the result. The tool never blocks on a human."""
    token = await _join(server_url)
    await _push(server_url, token)

    async def refuse_to_answer(*args, **kwargs):
        raise AssertionError("sync must not ask through the protocol")

    # A client that advertises elicitation, so the server could use it if it wanted to.
    client = Client(StreamableHttpTransport(server_url, auth=BearerAuth(token)),
                    elicitation_handler=refuse_to_answer)
    async with client:
        report = (await client.call_tool("sync", {
            "local": {"wizard": local_digests(files={"x.md": "edited\n"})},
        })).structured_content

    assert len(report["ask"]) == 1


def test_the_shipped_sync_skill_is_one_the_vault_would_accept():
    """setup-aistack writes this folder to disk, so it has to pass the rules it will meet."""
    files = [ArchivedFile(str(path.relative_to(SYNC_SKILL)), path.read_bytes(), False)
             for path in SYNC_SKILL.rglob("*") if path.is_file()]

    skill = validated_skill("sync-aistack", files)

    assert skill.description.startswith("Sync this machine's skills")
    assert "sync aistack" in skill.description


def test_the_shipped_sync_skill_explains_every_choice_and_both_flags():
    """The tool returns facts; this file is what turns them into a question worth answering."""
    document = (SYNC_SKILL / "SKILL.md").read_text()

    for term in ("`enable`", "`push`", "`remove`", "`skip`", "`overwrites_local`",
                 "`loses_local_edits`", "`orphans`", "`undecided`", "`disabled`"):
        assert term in document
