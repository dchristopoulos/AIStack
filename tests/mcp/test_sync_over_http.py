import hashlib
import pathlib

import httpx
import pytest
from fastmcp.client import BearerAuth, Client, StreamableHttpTransport
from fastmcp.exceptions import ToolError

from aistack.services.skill_archive import ArchivedFile
from aistack.services.skill_validation import validated_skill
from tests.archives import local_digests, skill_archive
from tests.mcp.conftest import call as _call
from tests.mcp.conftest import client_for
from tests.mcp.conftest import join as _join
from tests.mcp.conftest import push as _push
from tests.mcp.conftest import second_machine

pytestmark = pytest.mark.anyio

SYNC_SKILL = (pathlib.Path(__file__).parents[2] / "src" / "aistack" / "bundled" / "skills"
              / "sync-aistack")


async def test_a_whole_backup_list_is_one_push_skill_call(server_url):
    """IMP-11: a first sync with many skills cost one tool call per backup."""
    token = await _join(server_url)

    issued = await _call(server_url, token, "push_skill", names=["wizard", "notes", "Bad Name"])

    assert [entry["name"] for entry in issued["uploads"]] == ["wizard", "notes"]
    assert [entry["name"] for entry in issued["refused"]] == ["Bad Name"]
    async with httpx.AsyncClient() as http:
        for entry in issued["uploads"]:
            stored = (await http.put(entry["upload_url"],
                                     content=skill_archive(entry["name"]))).json()
            assert stored["revision"] == 1
    with pytest.raises(ToolError, match="either name"):
        await _call(server_url, token, "push_skill", name="wizard", names=["notes"])


async def test_an_edit_pushed_on_one_machine_reaches_the_other_through_sync(server_url):
    """The reason the product exists: push on A, sync on B, B is told to update."""
    machine_a = await _join(server_url)
    machine_b = await second_machine(server_url, machine_a)
    await _push(server_url, machine_a, files={"notes.md": "one\n"})
    await _call(server_url, machine_b, "get_skill", name="wizard")
    on_machine_b = {"wizard": local_digests(files={"notes.md": "one\n"})}

    before = await _call(server_url, machine_b, "sync", local=on_machine_b)
    skill_url = f"{server_url.removesuffix('/mcp')}/setup/sync-aistack/SKILL.md"
    assert before == {"install": [], "update": [], "ask": [], "backup": [],
                      "cannot_back_up": [],
                      "team_updates": [], "up_to_date": 1, "sync_skill_url": skill_url,
                      "first_sync": True, "project": None, "left_to_repository": [],
                      "from_other_computers": []}

    await _push(server_url, machine_a, files={"notes.md": "two\n"})

    after = await _call(server_url, machine_b, "sync", local=on_machine_b)
    assert after == {
        "install": [],
        "update": [{"name": "wizard", "from_revision": 1, "to_revision": 2,
                    "pushed_by": "dimitris"}],
        "ask": [],
        "backup": [],
        "cannot_back_up": [],
        "team_updates": [],
        "up_to_date": 0,
        "sync_skill_url": skill_url,
        "first_sync": False,
        "project": None,
        "left_to_repository": [],
        "from_other_computers": [],
    }


async def test_a_fresh_machine_is_told_to_install_what_it_enabled(server_url):
    machine_a = await _join(server_url)
    machine_b = await second_machine(server_url, machine_a)
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

    assert set(sync.inputSchema["properties"]) == {"local", "harness", "here", "project",
                                                   "repository"}
    assert sync.inputSchema["required"] == ["local"]
    # The agent sees which folders there are, and what omitting one means.
    assert sync.inputSchema["properties"]["harness"]["enum"] == ["claude_code", "agents"]
    assert sync.inputSchema["properties"]["harness"]["default"] == "claude_code"


async def test_every_answer_to_a_question_is_an_existing_tool(server_url, session_factory):
    """Edit locally, get asked, and resolve it each way. No hidden verb is needed."""
    machine_a = await _join(server_url)
    machine_b = await second_machine(server_url, machine_a)
    await _push(server_url, machine_a)
    await _call(server_url, machine_b, "get_skill", name="wizard")
    edited = {"notes.md": "a local edit\n"}
    on_machine_b = {"wizard": local_digests(files=edited), "new-here": local_digests("new-here")}

    report = await _call(server_url, machine_b, "sync", local=on_machine_b)

    assert report["install"] == [] and report["update"] == []
    assert report["backup"] == ["new-here"]
    assert report["ask"] == [{
        "name": "wizard",
        "desired": "enabled",
        "local": "unknown",
        "local_revision": None,
        # Pushed from here, then edited: an edit of the latest, so a push buries nothing.
        "edited_from": 1,
        "latest_revision": 1,
        "pushed_by": "dimitris",
        "options": [
            {"choice": "restore", "overwrites_local": True, "loses_local_edits": True},
            {"choice": "push", "overwrites_local": False, "loses_local_edits": False},
            {"choice": "skip", "overwrites_local": False, "loses_local_edits": False},
        ],
        "removed_from_library": False,
    }]

    # Answer "push": the edit becomes revision 2 and the question is gone.
    pushed = await _push(server_url, machine_b, files=edited)
    assert pushed["revision"] == 2
    after_push = await _call(server_url, machine_b, "sync", local=on_machine_b)
    assert after_push["ask"] == [] and after_push["up_to_date"] == 1

    # Back up the skill found only here: it stops being listed.
    await _push(server_url, machine_b, name="new-here")
    assert (await _call(server_url, machine_b, "sync", local=on_machine_b))["backup"] == []

    # Machine A is now behind, unmodified: a silent update, not a question.
    on_machine_a = {"wizard": local_digests()}
    behind = await _call(server_url, machine_a, "sync", local=on_machine_a)
    assert behind["ask"] == []
    assert behind["update"] == [{"name": "wizard", "from_revision": 1, "to_revision": 2,
                                 "pushed_by": "dimitris"}]


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

    for term in ("`enable`", "`restore`", "`push`", "`remove`", "`skip`", "`overwrites_local`",
                 "`loses_local_edits`", "`backup`", "`team_updates`", "`sync_skill_url`",
                 "`undecided`", "`disabled`"):
        assert term in document


async def test_sync_hands_out_the_servers_sync_skill_until_the_machine_has_it(server_url):
    """A machine added with add_machine never ran setup, and setup only ever ran once."""
    machine = await _join(server_url)

    offered = (await _call(server_url, machine, "sync", local={}))["sync_skill_url"]
    async with httpx.AsyncClient() as http:
        document = (await http.get(offered)).content
    installed = {"sync-aistack": {"SKILL.md": hashlib.sha256(document).hexdigest()}}

    assert document.startswith(b"---\nname: sync-aistack\n")
    assert (await _call(server_url, machine, "sync", local=installed))["sync_skill_url"] is None


async def test_a_codex_only_computer_added_with_add_machine_gets_the_sync_skill(server_url):
    """PH-06: Codex is the agent connected there, so the shared folder is where it goes."""
    first = await _join(server_url)
    await _push(server_url, first)
    codex_box = await second_machine(server_url, first, "codex-box")

    report = await _call(server_url, codex_box, "sync", local={}, harness="agents")
    async with httpx.AsyncClient() as http:
        document = (await http.get(report["sync_skill_url"])).content
    installed = {"sync-aistack": {"SKILL.md": hashlib.sha256(document).hexdigest()}}

    assert report["first_sync"] is True
    # The skill's first-sync step is what offers the Library's wizard here.
    assert "## 5. The first sync on this computer" in document.decode()
    assert (await _call(server_url, codex_box, "list_skills"))["skills"][0]["name"] == "wizard"
    assert (await _call(server_url, codex_box, "sync", local=installed,
                        harness="agents"))["sync_skill_url"] is None


async def test_the_sync_description_lists_files_the_way_the_skill_does(server_url):
    """The digest commands live in the skill, which every computer is given; the description
    keeps what to skip, so an agent without the skill still sends nothing it should not."""
    async with client_for(server_url, await _join(server_url)) as client:
        description = next(tool.description for tool in await client.list_tools()
                           if tool.name == "sync")
    document = (SYNC_SKILL / "SKILL.md").read_text()

    for exclusion in ("! -name .DS_Store", "! -path './.*'", "! -path './synced/*'",
                      "! -path '*/.git/*'"):
        assert exclusion in document
    assert "Skip 'synced', dot-folders, .git and .DS_Store." in description
    assert "as the sync-aistack skill says" in description


async def test_a_skill_backed_up_from_the_agents_folder_stays_in_that_folder(server_url):
    """ADR-0018 over the wire: the upload URL carries the harness it was issued for, and each
    folder on each computer is synced and installed into on its own."""
    machine_a = await _join(server_url)
    machine_b = await second_machine(server_url, machine_a)
    issued = await _call(server_url, machine_a, "push_skill", name="wizard", harness="agents")
    async with httpx.AsyncClient() as http:
        pushed = (await http.put(issued["upload_url"], content=skill_archive())).json()
    assert pushed["revision"] == 1

    agents_a = await _call(server_url, machine_a, "sync", harness="agents",
                           local={"wizard": local_digests()})
    claude_code_a = await _call(server_url, machine_a, "sync", local={})
    assert (agents_a["up_to_date"], claude_code_a["install"]) == (1, [])

    installed = await _call(server_url, machine_b, "get_skill", name="wizard",
                            harness="agents")
    assert installed["folder"] == "~/.agents/skills"
    agents_b = await _call(server_url, machine_b, "sync", harness="agents", local={})
    claude_code_b = await _call(server_url, machine_b, "sync", local={})
    assert [entry["name"] for entry in agents_b["install"]] == ["wizard"]
    assert claude_code_b["install"] == []
