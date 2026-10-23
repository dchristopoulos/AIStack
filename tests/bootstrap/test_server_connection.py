import json
import socket
from pathlib import Path

import httpx
import pytest

from aistack.bootstrap import agent_config
from aistack.bootstrap.sync_lock import locked
from aistack.commons.exceptions import Busy, ValidationError
from aistack.services import server_connection
from aistack.services.server_connection import Connection, checked_server, http_client


def test_connections_must_agree_and_respect_codex_home(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    codex = tmp_path / "custom-codex"
    codex.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(codex))
    (tmp_path / ".claude.json").write_text(json.dumps({"mcpServers": {"aistack": {"url": "https://example.com/mcp", "headers": {"Authorization": "Bearer secret"}}}}))
    (codex / "config.toml").write_text('[mcp_servers.aistack]\nurl="https://example.com/mcp"\nhttp_headers={Authorization="Bearer secret"}\n')
    assert agent_config.remote_connection() == Connection("https://example.com/mcp", "secret")
    assert "secret" not in repr(agent_config.remote_connection())
    (codex / "config.toml").write_text('[mcp_servers.aistack]\nurl="https://example.com/mcp"\nhttp_headers={Authorization="Bearer different"}\n')
    with pytest.raises(agent_config.NotConnected, match="disagree"):
        agent_config.remote_connection()
    assert agent_config.remote_connection("claude-code").token == "secret"


@pytest.mark.parametrize("address,private", [("127.0.0.1", True), ("10.1.2.3", True), ("192.168.4.1", True), ("172.16.0.1", True), ("100.100.1.1", True), ("fc00::1", True), ("8.8.8.8", False), ("169.254.1.1", False)])
def test_http_policy(monkeypatch, address, private):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(None, None, None, None, (address, 80))])
    if private:
        assert "not encrypted" in checked_server("http://server/mcp")
    else:
        with pytest.raises(ValidationError, match="HTTPS"):
            checked_server("http://server/mcp")
        assert "can read" in checked_server("http://server/mcp", True)


def test_mixed_dns_is_public(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(None, None, None, None, (value, 80)) for value in ("10.0.0.1", "8.8.8.8")])
    with pytest.raises(ValidationError):
        checked_server("http://server")


def test_redirects_are_disabled():
    client = http_client(follow_redirects=True)
    assert client.follow_redirects is False


def test_two_session_start_hooks_sync_one_after_the_other(tmp_path, monkeypatch):
    import threading
    import time
    import types

    from aistack.bootstrap import sync_lock

    waiting, release, order = threading.Event(), threading.Event(), []

    def sleep(seconds):
        # The second sync found the lock taken and is waiting for it, not refusing.
        waiting.set()
        release.wait(5)

    monkeypatch.setattr(sync_lock, "time", types.SimpleNamespace(monotonic=time.monotonic, sleep=sleep))

    def second():
        with locked(tmp_path):
            order.append("second")

    with locked(tmp_path):
        order.append("first")
        thread = threading.Thread(target=second)
        thread.start()
        assert waiting.wait(5)
        order.append("first done")
        release.set()
    thread.join(5)
    assert order == ["first", "first done", "second"]


def test_a_sync_held_past_the_wait_is_busy(tmp_path):
    with locked(tmp_path):
        with pytest.raises(Busy, match="Another AIStack sync is running"):
            with locked(tmp_path, wait=0.3):
                pass


def test_server_hook_preserves_other_hooks_and_has_full_sync_timeout(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    path = tmp_path / ".claude/settings.json"
    path.parent.mkdir()
    path.write_text(json.dumps({"hooks": {"SessionStart": [{"hooks": [{"command": "keep me"}]}]}}))
    command = agent_config.server_hook_command(Path("/installed/aistack"))
    agent_config.add_session_start_hook("claude-code", command)
    agent_config.add_session_start_hook("claude-code", command)
    entries = json.loads(path.read_text())["hooks"]["SessionStart"]
    assert len(entries) == 2
    assert entries[1]["hooks"][0]["timeout"] > 150
    accepted = agent_config.server_hook_command(Path("/installed/aistack"), allow_http=True)
    assert accepted == command + " --allow-http"
    agent_config.add_session_start_hook("claude-code", accepted)
    entries = json.loads(path.read_text())["hooks"]["SessionStart"]
    assert [entry["hooks"][0]["command"] for entry in entries] == ["keep me", accepted]
    assert entries[1]["hooks"][0]["timeout"] > 150


@pytest.mark.parametrize("hook", [False, True])
def test_only_manual_sync_repeats_the_plain_http_warning(tmp_path, monkeypatch, capsys, hook):
    import sys

    from aistack.bootstrap import __main__ as command
    from aistack.services import server_sync

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(sys, "argv", ["aistack", "sync", *(["--hook"] if hook else [])])
    monkeypatch.setattr(agent_config, "remote_connection", lambda _: Connection("http://127.0.0.1/mcp", "secret"))

    asked = {}

    async def nothing_to_do(*args, **keywords):
        asked.update(keywords)
        return []

    monkeypatch.setattr(server_sync, "sync_computer", nothing_to_do)
    command.run()
    # Only a manual sync covers every project; the session-start hook stays fast.
    assert asked == {"every_project": not hook}
    printed = capsys.readouterr().out
    assert ("not encrypted" in printed) is not hook
    assert printed == "" if hook else "up to date" in printed


def test_sync_command_explains_a_copied_connection(tmp_path, monkeypatch):
    import sys

    from fastmcp.exceptions import ToolError

    from aistack.bootstrap import __main__ as command
    from aistack.services import server_sync

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(sys, "argv", ["aistack", "sync"])
    monkeypatch.setattr(agent_config, "remote_connection", lambda _: Connection("https://server/mcp", "secret"))

    async def copied(*args, **_):
        raise ToolError("This looks like a different computer. Add it as its own computer from the dashboard.")

    monkeypatch.setattr(server_sync, "sync_computer", copied)
    with pytest.raises(SystemExit, match="different computer.*dashboard"):
        command.run()


def test_sync_against_a_local_library_syncs_its_rules_here(tmp_path, monkeypatch, capsys):
    import sys

    from aistack.bootstrap import __main__ as command

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.delenv("CODEX_HOME", raising=False)
    (tmp_path / ".claude.json").write_text(json.dumps(
        {"mcpServers": {"aistack": {"command": "/bin/aistack-mcp", "args": []}}}))
    monkeypatch.setattr(sys, "argv", ["aistack", "sync", "--rule-choice", "a:b=push"])
    asked = []
    monkeypatch.setattr(command, "sync_local", lambda agent, choices: asked.append(
        (agent, choices)) or [{"completed": [], "failures": [], "rule_questions": []}])

    command.run()

    assert asked == [(None, {"a:b": "push"})]
    assert "AIStack rules are up to date." in capsys.readouterr().out
    assert agent_config.connected_locally() and not agent_config.connected_locally("codex")


def test_a_failure_cause_is_one_line_with_no_address_in_it():
    request = httpx.Request("GET", "https://aistack.example/transfer/archive/eyJ.ticket")
    refused = httpx.HTTPStatusError("Client error '404 Not Found' for url "
                                    "'https://aistack.example/transfer/archive/eyJ.ticket'",
                                    request=request, response=httpx.Response(404, request=request))
    assert server_connection.failure_cause(refused) == "the server answered 404"
    grouped = ExceptionGroup("unhandled errors in a TaskGroup", [
        httpx.ConnectError("Cannot reach https://aistack.example/mcp\nnow")])
    assert server_connection.failure_cause(grouped) == "Cannot reach an address\\nnow"
    assert server_connection.failure_cause(KeyboardInterrupt()) == "KeyboardInterrupt"
