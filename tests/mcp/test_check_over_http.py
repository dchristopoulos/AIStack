"""`aistack check` on a computer connected to a server: it signs in with this computer's key
and says so, and it never sets up a Library on this computer."""

import json

import anyio
import pytest

from aistack.bootstrap import __main__ as cli
from tests.mcp.conftest import join

pytestmark = pytest.mark.anyio


@pytest.fixture
def home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("AISTACK_HOME", str(home / ".aistack"))
    monkeypatch.setenv("CODEX_HOME", str(home / ".codex"))
    return home


def _connect_claude_code(home, url: str, token: str) -> None:
    entry = {"type": "http", "url": url, "headers": {"Authorization": f"Bearer {token}"}}
    (home / ".claude.json").write_text(json.dumps({"mcpServers": {"aistack": entry}}))


async def _check(capsys) -> tuple[str, str | None]:
    try:
        await anyio.to_thread.run_sync(cli.check, None, False)
    except SystemExit as exit:
        return capsys.readouterr().out, str(exit.code)
    return capsys.readouterr().out, None


async def test_check_names_the_server_and_sets_up_nothing_here(server_url, home, capsys):
    _connect_claude_code(home, server_url, await join(server_url))

    printed, refused = await _check(capsys)

    assert refused is None
    address = server_url.removesuffix("/mcp").removesuffix("/mcp/")
    assert f"AIStack is connected to {address} for Claude Code." in printed
    assert "lives on this computer" not in printed
    assert not (home / ".aistack").exists()


async def test_a_refused_key_is_not_ready_and_sets_up_nothing_here(server_url, home, capsys):
    _connect_claude_code(home, server_url, "aist_not-a-token-this-server-made")

    printed, refused = await _check(capsys)

    assert refused.startswith("AIStack is not ready.") and "not-a-token" not in refused
    assert not (home / ".aistack").exists()


async def test_an_unreachable_server_is_not_ready_and_sets_up_nothing_here(home, capsys):
    _connect_claude_code(home, "http://127.0.0.1:1/mcp", "aist_token")

    printed, refused = await _check(capsys)

    assert refused.startswith("AIStack is not ready. It could not sign in to http://127.0.0.1:1:")
    assert "aist_token" not in refused
    assert not (home / ".aistack").exists()
