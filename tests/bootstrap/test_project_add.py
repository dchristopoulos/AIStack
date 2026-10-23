"""`aistack project add` says what it will send and sends nothing without Enter."""

import subprocess

import pytest

from aistack.bootstrap import agent_config, project_add
from aistack.services import server_sync
from aistack.services.server_connection import Connection


@pytest.fixture
def shop(tmp_path):
    top = tmp_path / "shop"
    (top / "docs").mkdir(parents=True)
    for path, text in {"AGENTS.md": "rules\n", "docs/a.md": "a\n", "app.py": "x\n"}.items():
        (top / path).write_bytes(text.encode())  # no CRLF on Windows: sizes are exact
    subprocess.run(["git", "-C", str(top), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(top), "add", "."], check=True)
    return top


@pytest.fixture
def sent(monkeypatch):
    calls = []

    async def sync_computer(connection, home, cwd, rule_choices=None, add_files=None):
        calls.append((cwd, add_files))
        return []

    monkeypatch.setattr(server_sync, "sync_computer", sync_computer)
    monkeypatch.setattr(agent_config, "remote_connection",
                        lambda agent=None: Connection("https://aistack.example/mcp", "t"))
    monkeypatch.setattr(agent_config, "connected_locally", lambda agent=None: False)
    return calls


def test_it_lists_paths_and_sizes_then_sends_them_after_enter(shop, tmp_path, sent, capsys):
    project_add.run(["add", str(shop / "docs")], home=tmp_path / "home", confirm=lambda _: "")

    printed = capsys.readouterr().out
    assert "AGENTS.md  (6 bytes)  read by" in printed and "docs/a.md  (2 bytes)" in printed
    assert "app.py" not in printed
    assert sent == [(shop.resolve(), [{"path": "AGENTS.md", "size": 6},
                                      {"path": "docs/a.md", "size": 2}])]


def test_nothing_is_sent_without_enter(shop, tmp_path, sent):
    def stop(_):
        raise KeyboardInterrupt

    with pytest.raises(SystemExit, match="Nothing was sent"):
        project_add.run(["add", str(shop)], home=tmp_path / "home", confirm=stop)
    assert sent == []


def test_a_local_library_is_sent_to_the_page_before_anything_is_asked(shop, tmp_path, sent,
                                                                       monkeypatch, capsys):
    monkeypatch.setattr(agent_config, "connected_locally", lambda agent=None: True)

    def asked(_):
        raise AssertionError("asked for Enter")

    with pytest.raises(SystemExit, match="A folder on this computer"):
        project_add.run(["add", str(shop)], home=tmp_path / "home", confirm=asked)
    assert sent == [] and capsys.readouterr().out == ""


def test_a_folder_outside_git_is_not_a_project(tmp_path, sent):
    with pytest.raises(SystemExit, match="not inside a git repository"):
        project_add.run(["add", str(tmp_path)], home=tmp_path / "home", confirm=lambda _: "")
    assert sent == []
