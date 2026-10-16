import json
import re
import tomllib

import httpx
import pytest

from aistack.bootstrap.context import application_context
from aistack.bundled import sync_skill_document
from aistack.mcp.mcp import mcp
from tests.conftest import INVITE_CODE
from tests.mcp.conftest import client_for

pytestmark = pytest.mark.anyio

MCP_HEADERS = {"Content-Type": "application/json",
               "Accept": "application/json, text/event-stream"}


def _base(server_url: str) -> str:
    return server_url.removesuffix("/mcp")


async def _get(url: str) -> httpx.Response:
    async with httpx.AsyncClient() as http:
        return await http.get(url)


async def _join_with_one_request(server_url: str, bearer: str, **arguments) -> httpx.Response:
    """Exactly the request the setup instructions tell the agent to send with curl."""
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "join", "arguments": arguments}}
    async with httpx.AsyncClient() as http:
        return await http.post(server_url, content=json.dumps(body),
                               headers={**MCP_HEADERS, "Authorization": f"Bearer {bearer}"})


async def test_the_setup_page_is_public_and_names_this_servers_own_address(server_url):
    response = await _get(f"{_base(server_url)}/setup")

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/markdown; charset=utf-8"
    assert f"curl -sS {server_url} -H" in response.text
    assert f"{_base(server_url)}/setup/sync-aistack/SKILL.md" in response.text
    # Every placeholder was filled in.
    assert not re.search(r"\{(server_url|mcp_url)\}", response.text)


async def test_the_setup_page_uses_the_public_url_behind_a_proxy(server_url, monkeypatch):
    monkeypatch.setattr(application_context.get_settings(), "public_url",
                        "https://aistack.example.com")

    response = await _get(f"{_base(server_url)}/setup")

    assert "https://aistack.example.com/mcp" in response.text
    assert "127.0.0.1" not in response.text


async def test_the_setup_page_holds_nothing_secret(server_url):
    """It is served to anyone who asks, before they have shown any credential."""
    response = await _get(f"{_base(server_url)}/setup")

    assert INVITE_CODE not in response.text
    assert "aist_" not in response.text


async def test_the_setup_page_gets_the_details_that_are_easy_to_get_wrong(server_url):
    text = (await _get(f"{_base(server_url)}/setup")).text

    # Default scope is one project: without this the vault works in one folder only.
    assert "--scope user aistack" in text
    # Claude Code watches only a skills directory that existed when it started.
    assert text.index("mkdir -p ~/.claude/skills") < text.index("claude mcp add")
    # Already set up is checked before anything is created.
    assert text.index("claude mcp list") < text.index("mkdir -p")
    assert "Restart Claude Code once" in text


async def test_setup_checks_both_agents_before_registering_this_computer(server_url):
    """AUTO-11: run from the second agent, a check of only its own let it register the same
    computer twice, and the two then undid each other's removals."""
    text = (await _get(f"{_base(server_url)}/setup")).text
    step_one = text[text.index("## 1."):text.index("## 2.")]

    assert "claude mcp list\ngrep -c '^\\[mcp_servers.aistack\\]'" in step_one
    assert "If `aistack` is listed, or the count is 1, stop." in step_one
    assert "Never register this computer a second time" in step_one


async def test_the_setup_page_connects_codex_with_one_block_of_valid_toml(server_url):
    """Codex cannot set a header from its CLI, so the agent writes this block (ADR-0021)."""
    text = (await _get(f"{_base(server_url)}/setup")).text
    block = re.search(r"```toml\n(.*?)\n```", text, re.S).group(1)

    server = tomllib.loads(block)["mcp_servers"]["aistack"]
    assert server["url"] == server_url
    assert server["http_headers"] == {"Authorization": "Bearer <token>"}
    # Only what sync does without asking is pre-approved; sharing and teams still ask.
    approved = {name for name, tool in server["tools"].items() if tool["approval_mode"] == "approve"}
    # list_skills too: a first sync lists the Library to offer what other computers have.
    assert approved == {"sync", "list_skills", "get_skill", "push_skill"}
    assert approved <= {tool.name for tool in await mcp._list_tools()}
    # Codex reads skills from the shared folder, so that is where setup puts the sync skill.
    assert "mkdir -p ~/.agents/skills/sync-aistack" in text
    assert text.index("grep -c '^\\[mcp_servers.aistack\\]'") < text.index("mkdir -p ~/.agents/skills")


async def test_the_setup_page_offers_a_session_start_hook_that_only_prompts_a_sync(server_url):
    """A hook cannot call an MCP tool at startup, and sync stays read-only (ADR-0018)."""
    text = (await _get(f"{_base(server_url)}/setup")).text
    hook = json.loads(re.search(r"```json\n(\{\"matcher\".*?)\n```", text, re.S).group(1))

    assert hook["matcher"] == "startup"
    assert [handler["type"] for handler in hook["hooks"]] == ["command"]
    assert hook["hooks"][0]["command"].startswith("echo ")
    assert "sync-aistack" in hook["hooks"][0]["command"]
    # Offered, not imposed, and only once the server is connected.
    assert text.index("claude mcp add") < text.index("SessionStart")
    assert "If they decline" in text


async def test_the_sync_skill_is_served_exactly_as_shipped(server_url):
    """A fresh vault cannot install the skill that talks to it, so setup fetches it here."""
    response = await _get(f"{_base(server_url)}/setup/sync-aistack/SKILL.md")

    assert response.status_code == 200
    assert response.text == sync_skill_document()
    assert response.text.startswith("---\nname: sync-aistack\n")


def test_the_sync_skill_stops_when_aistack_is_not_connected():
    """Without the tools, an agent left to improvise reached the server with a token it read
    from its own configuration. The skill stops it first and says what to check instead."""
    document = sync_skill_document()

    assert document.index("Check that AIStack is connected") < document.index("Call `sync`")
    assert "never read a token out of a configuration file" in document
    assert "claude mcp get aistack" in document and "codex mcp get aistack" in document


def test_the_sync_skill_explains_a_listing_too_big_to_send():
    """ENT-12: the MCP SDK refuses a body over 4 MiB with a bare 413, before sync's own
    sentence about node_modules can run, so the skill says what that 413 means."""
    document = sync_skill_document()
    explained = document[document.index("HTTP 413"):]

    assert "node_modules" in explained.split("\n", 1)[0]
    assert "list and sync again" in explained.split("\n", 1)[0]


async def test_the_documented_join_request_works_with_no_mcp_client(server_url):
    """One POST, no handshake, no session: what the stateless endpoint is for (ADR-0013)."""
    response = await _join_with_one_request(server_url, INVITE_CODE, username="maria",
                                            machine_name="laptop", os="LINUX")

    assert response.status_code == 200
    result = response.json()["result"]
    assert result["isError"] is False
    token = result["structuredContent"]["token"]

    # The token that one request returned is a working machine credential.
    async with client_for(server_url, token) as client:
        assert "sync" in {tool.name for tool in await client.list_tools()}


async def test_running_setup_twice_does_not_create_a_second_user(server_url, session_factory):
    await _join_with_one_request(server_url, INVITE_CODE, username="maria",
                                 machine_name="laptop", os="LINUX")

    again = await _join_with_one_request(server_url, INVITE_CODE, username="maria",
                                         machine_name="laptop", os="LINUX")

    result = again.json()["result"]
    assert result["isError"] is True
    # The instructions tell the agent what this message means: use add_machine instead.
    assert "already taken" in result["content"][0]["text"]
    assert "add the machine" in result["content"][0]["text"]


async def test_a_wrong_invite_code_is_a_401_with_no_result(server_url):
    response = await _join_with_one_request(server_url, "not-the-invite-code",
                                            username="maria", machine_name="laptop",
                                            os="LINUX")

    assert response.status_code == 401
    assert "not-the-invite-code" not in response.text


async def test_the_server_keeps_no_session(server_url):
    """Two unrelated requests, no session header between them, both answered."""
    first = await _join_with_one_request(server_url, INVITE_CODE, username="one",
                                         machine_name="box", os="LINUX")
    second = await _join_with_one_request(server_url, INVITE_CODE, username="two",
                                          machine_name="box", os="LINUX")

    assert first.status_code == second.status_code == 200
    assert "mcp-session-id" not in first.headers
