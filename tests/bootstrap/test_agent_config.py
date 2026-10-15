import json
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest

from aistack.bootstrap import agent_config
from aistack.bootstrap.agent_config import NotConnected

PROGRAM = Path("/home/maria/.local/bin/aistack-mcp")
PLACE = {"AISTACK_DATABASE_URL": "postgresql://maria:pa'ss\"word@db.example/aistack"}


@pytest.fixture(autouse=True)
def home_fixture(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.delenv("CODEX_HOME", raising=False)
    return tmp_path


def _recorder():
    calls = []

    def run(command, **_):
        calls.append(command)
        return SimpleNamespace(returncode=0, stderr="")
    return calls, run


def test_claude_code_gets_the_name_before_its_settings_and_the_full_path(monkeypatch):
    """`-e` takes every value after it, so a name after it is read as one more setting and
    `claude mcp add` fails with nothing added."""
    monkeypatch.setattr(agent_config.shutil, "which", lambda _: "/usr/bin/claude")
    calls, run = _recorder()

    agent_config.connect_claude_code(PROGRAM, PLACE, run)

    add = calls[-1]
    assert add[:6] == ["/usr/bin/claude", "mcp", "add", "--scope", "user", "aistack"]
    assert add[6:8] == ["-e", f"AISTACK_DATABASE_URL={PLACE['AISTACK_DATABASE_URL']}"]
    assert add[-2:] == ["--", str(PROGRAM)]
    assert calls[0][:3] == ["/usr/bin/claude", "mcp", "remove"]


def test_a_failure_from_claude_never_repeats_the_place(monkeypatch):
    monkeypatch.setattr(agent_config.shutil, "which", lambda _: "/usr/bin/claude")
    secret = PLACE["AISTACK_DATABASE_URL"]

    def run(command, **_):
        return SimpleNamespace(returncode=1, stderr=f"Invalid value: AISTACK_DATABASE_URL={secret}")

    with pytest.raises(NotConnected) as refusal:
        agent_config.connect_claude_code(PROGRAM, PLACE, run)
    assert secret not in str(refusal.value) and "<hidden>" in str(refusal.value)


def test_codex_keeps_every_other_setting_and_writes_one_table_however_often_it_runs(home_fixture):
    config = home_fixture / ".codex" / "config.toml"
    config.parent.mkdir()
    config.write_text('model = "o4"\n\n[mcp_servers.other]\ncommand = "other"\n\n'
                      '[mcp_servers.aistack]\ncommand = "/old/aistack-mcp"\n\n'
                      '[mcp_servers.aistack.env]\nAISTACK_HOME = "/old"\n\n'
                      '[profiles.work]\nmodel = "o3"\n')

    agent_config.connect_codex(PROGRAM, PLACE)
    once = config.read_text()
    agent_config.connect_codex(PROGRAM, PLACE)

    assert config.read_text() == once
    settings = tomllib.loads(once)
    assert settings["model"] == "o4" and settings["profiles"]["work"]["model"] == "o3"
    assert settings["mcp_servers"]["other"] == {"command": "other"}
    ours = settings["mcp_servers"]["aistack"]
    assert ours["command"] == str(PROGRAM)
    assert ours["env"] == PLACE
    assert ours["startup_timeout_sec"] == 60
    assert {tool: value["approval_mode"] for tool, value in ours["tools"].items()} == {
        "sync": "approve", "list_skills": "approve", "get_skill": "approve",
        "push_skill": "approve"}


def test_codex_config_that_is_not_valid_toml_is_left_alone(home_fixture):
    config = home_fixture / ".codex" / "config.toml"
    config.parent.mkdir()
    config.write_text("[mcp_servers\n")

    with pytest.raises(NotConnected, match="not valid TOML"):
        agent_config.connect_codex(PROGRAM, PLACE)
    assert config.read_text() == "[mcp_servers\n"


def test_the_hook_is_added_once_and_keeps_the_hooks_already_there(home_fixture):
    settings = home_fixture / ".claude" / "settings.json"
    settings.parent.mkdir()
    theirs = {"matcher": "startup", "hooks": [{"type": "command", "command": "echo hi"}]}
    settings.write_text(json.dumps({"theme": "dark", "hooks": {"SessionStart": [theirs]}}))

    agent_config.add_session_start_hook("claude-code")
    once = settings.read_text()
    agent_config.add_session_start_hook("claude-code")

    assert settings.read_text() == once
    written = json.loads(once)
    assert written["theme"] == "dark"
    assert [entry["hooks"][0]["command"] for entry in written["hooks"]["SessionStart"]] == [
        "echo hi", agent_config.HOOK_COMMAND]


def test_a_settings_file_that_is_not_valid_json_is_left_alone(home_fixture):
    settings = home_fixture / ".codex" / "hooks.json"
    settings.parent.mkdir()
    settings.write_text("{ not json")

    with pytest.raises(NotConnected, match="not valid JSON"):
        agent_config.add_session_start_hook("codex")
    assert settings.read_text() == "{ not json"


def test_the_place_is_read_back_from_the_agent_without_asking_anyone_to_print_it(home_fixture):
    (home_fixture / ".claude.json").write_text(json.dumps({"mcpServers": {"aistack": {
        "command": str(PROGRAM), "env": PLACE | {"UNRELATED": "x"}}}}))
    assert agent_config.configured_place("claude-code") == PLACE

    agent_config.connect_codex(PROGRAM, {"AISTACK_LIBRARY_REPO": "maria/aistack-library"})
    assert agent_config.configured_place("codex") == {
        "AISTACK_LIBRARY_REPO": "maria/aistack-library"}


def _aistack(home: Path, *arguments: str, environment: dict | None = None):
    """The installed command as an agent's shell runs it, standing in for a uv tool install."""
    import os
    import subprocess
    import sys
    script = ("import sys; from aistack.bootstrap import self_update; "
              "self_update.installed_as_uv_tool = lambda: True; "
              f"sys.argv = [{str(PROGRAM)!r}, *sys.argv[1:]]; "
              "from aistack.bootstrap.__main__ import run; run()")
    env = {**os.environ, "HOME": str(home), "USERPROFILE": str(home), **(environment or {})}
    for name in agent_config.PLACE_VARIABLES:
        if name not in (environment or {}):
            env.pop(name, None)
    return subprocess.run([sys.executable, "-c", script, *arguments], env=env,
                          capture_output=True, text=True)


def test_connect_checks_the_library_installs_the_skill_and_connects_codex(home_fixture):
    library = str(home_fixture / "library-home")

    done = _aistack(home_fixture, "connect", "codex", "--hook",
                    environment={"AISTACK_HOME": library})

    assert done.returncode == 0, done.stderr
    assert "AIStack is ready" in done.stdout
    assert (home_fixture / ".agents" / "skills" / "sync-aistack" / "SKILL.md").is_file()
    ours = tomllib.loads((home_fixture / ".codex" / "config.toml").read_text())
    assert ours["mcp_servers"]["aistack"]["env"] == {"AISTACK_HOME": library}
    hooks = json.loads((home_fixture / ".codex" / "hooks.json").read_text())
    assert len(hooks["hooks"]["SessionStart"]) == 1

    # Later, with nothing in the environment, the agent's own connection says where it is.
    again = _aistack(home_fixture, "check", "--agent", "codex")
    assert again.returncode == 0, again.stderr
    assert "on this computer only" in again.stdout
    assert not (home_fixture / ".aistack").exists()


def test_connect_after_a_move_follows_the_library_and_not_the_old_connection(home_fixture):
    """`move` records the new place, and the agent's connection still names the old one.
    Reading the connection first would connect the agent back to where the Library was."""
    from aistack.bootstrap.configuration.settings.settings_config import record_place
    moved = (home_fixture / "moved.db").as_posix()
    agent_config.connect_codex(PROGRAM, {"AISTACK_LIBRARY_REPO": "maria/old-library"})
    record_place(home_fixture / ".aistack", {"kind": "sqlite", "path": moved})

    done = _aistack(home_fixture, "connect", "codex")

    assert done.returncode == 0, done.stderr
    ours = tomllib.loads((home_fixture / ".codex" / "config.toml").read_text())
    assert ours["mcp_servers"]["aistack"]["env"] == {
        "AISTACK_DATABASE_URL": f"sqlite:///{moved}"}


def test_connect_refuses_to_name_a_program_that_is_not_installed(home_fixture):
    import os
    import subprocess
    import sys
    done = subprocess.run([sys.executable, "-m", "aistack.bootstrap", "connect", "codex"],
                          env={**os.environ, "HOME": str(home_fixture)},
                          capture_output=True, text=True)
    assert done.returncode == 1
    assert "uv tool install aistack-mcp" in done.stderr
    assert not (home_fixture / ".codex").exists()
