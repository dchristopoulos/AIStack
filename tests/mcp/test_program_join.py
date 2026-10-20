"""The joining program uses real HTTP while local installation stays in a temporary home."""

import asyncio
import json
import os
import stat
import tomllib
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from aistack.bootstrap import server_join
from aistack.commons.exceptions import ValidationError
from aistack.db.models.computer_code import ComputerCode
from aistack.db.models.machine import Machine
from aistack.services import computer_codes, hardware, operator_service
from aistack.services.token_service import hash_token
from tests.archives import skill_document
from tests.mcp.conftest import call, join, push

pytestmark = pytest.mark.anyio


@pytest.fixture
def joining_home(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.delenv("CODEX_HOME", raising=False)
    monkeypatch.setattr(hardware, "hardware_id", lambda: "joining-test-computer")
    monkeypatch.setattr(server_join.socket, "gethostname", lambda: "new-computer")
    monkeypatch.setattr(server_join, "POLL_INTERVAL", 0.01)
    program = tmp_path / "bin/aistack"
    program.parent.mkdir()
    program.touch()
    monkeypatch.setattr(server_join, "_program", lambda: program)
    codex = tmp_path / ".codex"
    codex.mkdir()
    (codex / "config.toml").write_text(
        'model = "favorite"\n[mcp_servers.other]\ncommand = "keep"\n'
    )
    (codex / "hooks.json").write_text(
        json.dumps(
            {"hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "keep-me"}]}]}}
        )
    )
    return tmp_path


def _code_hash(code: dict) -> str:
    return hash_token(computer_codes.normalized(code["code"]))


async def _reserved_user(session_factory, code: dict) -> uuid.UUID:
    for _ in range(200):
        with session_factory.begin() as session:
            row = session.get(ComputerCode, uuid.UUID(code["id"]))
            if row.request_hash is not None:
                return row.user_id
        await asyncio.sleep(0.01)
    raise AssertionError("the joining program never reserved its code")


async def _completed(session_factory, code: dict) -> bool:
    with session_factory.begin() as session:
        return session.get(ComputerCode, uuid.UUID(code["id"])).completed_on is not None


async def test_join_waits_for_approval_and_finishes_setup(
    server_url, session_factory, joining_home, caplog
):
    owner = await join(server_url)
    await push(server_url, owner)
    code = await call(
        server_url, owner, "add_machine", computer_code=True, options={"agents": "codex"}
    )
    lines = []
    running = asyncio.create_task(
        server_join.join_computer(server_url, code["code"], say=lines.append)
    )
    for _ in range(200):
        with session_factory.begin() as session:
            row = session.get(ComputerCode, uuid.UUID(code["id"]))
            pending = row.request_hash is not None
            if pending:
                assert row.completed_on is None
                assert session.get(Machine, row.machine_id) is None
                user = row.user_id
        if pending:
            break
        await asyncio.sleep(0.01)
    assert pending
    with session_factory.begin() as session:
        computer_codes.decide(session, user, code["id"], "approve")
    result = await running
    assert result == {"agents": ["codex"], "skills": 1}
    config = tomllib.loads((joining_home / ".codex/config.toml").read_text())
    assert config["model"] == "favorite" and config["mcp_servers"]["other"]["command"] == "keep"
    assert config["mcp_servers"]["aistack"]["tools"]["get_skill"]["approval_mode"] == "approve"
    token = config["mcp_servers"]["aistack"]["http_headers"]["Authorization"].removeprefix(
        "Bearer "
    )
    assert (
        token not in "\n".join(lines)
        and token not in caplog.text
        and code["code"] not in caplog.text
    )
    assert not (joining_home / ".aistack/joining.json").exists()
    assert (joining_home / ".agents/skills/wizard/SKILL.md").is_file()
    hooks = (joining_home / ".codex/hooks.json").read_text()
    assert (
        "keep-me" in hooks and "sync --hook" in hooks and str(joining_home / "bin/aistack") in hooks
    )
    if os.name != "nt":
        assert stat.S_IMODE((joining_home / ".codex/config.toml").stat().st_mode) == 0o600
    with session_factory.begin() as session:
        row = session.get(ComputerCode, uuid.UUID(code["id"]))
        assert row.request["setup"] == result
        assert session.get(Machine, row.machine_id).fingerprint_hash is not None
    # A used code says already connected only after authenticating the local key.
    again = []
    assert (await server_join.join_computer(server_url, code["code"], say=again.append))[
        "already_connected"
    ]
    assert "already connected" in "\n".join(again)


async def test_partial_config_failure_resumes_without_another_machine(
    server_url, session_factory, joining_home, monkeypatch
):
    owner = await join(server_url)
    code = await call(
        server_url,
        owner,
        "add_machine",
        computer_code=True,
        options={"agents": "codex", "approval": False, "skills": "empty"},
    )
    write = server_join._write

    def fail_config(path, text):
        if path.name == "config.toml":
            raise OSError("disk full")
        return write(path, text)

    with monkeypatch.context() as patch:
        patch.setattr(server_join, "_write", fail_config)
        with pytest.raises(OSError):
            await server_join.join_computer(server_url, code["code"], say=lambda line: None)
    state = json.loads((joining_home / ".aistack/joining.json").read_text())
    assert state["token"].startswith("aist_")
    if os.name != "nt":
        assert stat.S_IMODE((joining_home / ".aistack/joining.json").stat().st_mode) == 0o600
    result = await server_join.join_computer(server_url, code["code"], say=lambda line: None)
    assert result["skills"] == 0
    with session_factory.begin() as session:
        assert len(list(session.scalars(select(Machine)))) == 2


async def test_local_different_skill_is_kept_and_asked_about(server_url, joining_home):
    owner = await join(server_url)
    await push(server_url, owner)
    local = joining_home / ".agents/skills/wizard/SKILL.md"
    local.parent.mkdir(parents=True)
    local.write_text(skill_document("wizard") + "\nlocal changes\n")
    before = local.read_bytes()
    code = await call(
        server_url,
        owner,
        "add_machine",
        computer_code=True,
        options={"agents": "codex", "approval": False},
    )
    lines = []
    await server_join.join_computer(server_url, code["code"], say=lines.append)
    assert local.read_bytes() == before
    assert "Kept local 'wizard'" in "\n".join(lines)
    assert "overwrites_local" in "\n".join(lines) or "Decide whether" in "\n".join(lines)


async def test_malformed_config_refuses_before_reservation(
    server_url, session_factory, joining_home
):
    owner = await join(server_url)
    code = await call(
        server_url,
        owner,
        "add_machine",
        computer_code=True,
        options={"agents": "codex", "approval": False},
    )
    path = joining_home / ".codex/config.toml"
    path.write_text('password = "never-echo-this"\nbroken = [')
    with pytest.raises(ValidationError, match="could not be read") as caught:
        await server_join.join_computer(server_url, code["code"], say=lambda line: None)
    assert "never-echo-this" not in str(caught.value)
    with session_factory.begin() as session:
        assert session.get(ComputerCode, uuid.UUID(code["id"])).request_hash is None


async def test_copied_recovery_file_refuses_before_configuration_or_skills(
    server_url, session_factory, joining_home
):
    from fastmcp.exceptions import ToolError

    owner = await join(server_url)
    code = await call(
        server_url,
        owner,
        "add_machine",
        computer_code=True,
        options={"agents": "codex", "approval": False},
    )
    reserved = await call(
        server_url, code["code"], "join", pairing="reserve", machine_name="copied", os="LINUX"
    )
    connected = await call(
        server_url,
        reserved["request_bearer"],
        "join",
        pairing="poll",
        fingerprint=hardware.fingerprint(uuid.UUID(reserved["machine_id"]), "other-computer"),
    )
    state = reserved | connected | {"url": server_url, "code_hash": _code_hash(code)}
    server_join._json(joining_home / ".aistack/joining.json", state)
    config = joining_home / ".codex/config.toml"
    before = config.read_bytes()
    with pytest.raises(ToolError, match="different computer"):
        try:
            await server_join.join_computer(server_url, code["code"], say=lambda line: None)
        finally:
            assert config.read_bytes() == before
            assert not (joining_home / ".agents/skills").exists()


async def test_claude_setup_preserves_settings_and_custom_codex_home(
    server_url, joining_home, monkeypatch
):
    custom = joining_home / "custom-codex"
    custom.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(custom))
    (custom / "config.toml").write_text('model = "chosen"\n')
    (joining_home / ".claude").mkdir()
    (joining_home / ".claude.json").write_text(
        json.dumps({"theme": "dark", "mcpServers": {"other": {"command": "keep"}}})
    )
    owner = await join(server_url)
    code = await call(
        server_url,
        owner,
        "add_machine",
        computer_code=True,
        options={"approval": False, "skills": "empty", "agents": "find"},
    )
    result = await server_join.join_computer(server_url, code["code"], say=lambda line: None)
    assert result["agents"] == ["claude-code", "codex"]
    config = json.loads((joining_home / ".claude.json").read_text())
    assert config["theme"] == "dark" and config["mcpServers"]["other"]["command"] == "keep"
    assert config["mcpServers"]["aistack"]["url"] == server_url
    assert tomllib.loads((custom / "config.toml").read_text())["model"] == "chosen"
    assert (custom / "hooks.json").exists()
    assert (joining_home / ".claude/skills/sync-aistack/SKILL.md").exists()


async def test_initial_library_choice_installs_persons_own_sync_skill(server_url, joining_home):
    owner = await join(server_url)
    await push(server_url, owner, name="sync-aistack", files={"mine.md": "my own instructions"})
    code = await call(
        server_url,
        owner,
        "add_machine",
        computer_code=True,
        options={"agents": "codex", "approval": False, "hook": False},
    )
    hooks = joining_home / ".codex/hooks.json"
    before = hooks.read_bytes()
    result = await server_join.join_computer(server_url, code["code"], say=lambda line: None)
    assert result["skills"] == 1
    assert (
        joining_home / ".agents/skills/sync-aistack/mine.md"
    ).read_text() == "my own instructions"
    assert hooks.read_bytes() == before


async def test_lost_setup_confirmation_leaves_only_configured_key(
    server_url, joining_home, monkeypatch
):
    owner = await join(server_url)
    code = await call(
        server_url,
        owner,
        "add_machine",
        computer_code=True,
        options={"agents": "codex", "approval": False, "skills": "empty"},
    )
    invoke = server_join._call

    async def missing_confirmation(connection, tool, **arguments):
        if arguments.get("pairing") == "confirm":
            raise RuntimeError("private response must not be printed")
        return await invoke(connection, tool, **arguments)

    monkeypatch.setattr(server_join, "_call", missing_confirmation)
    lines = []
    result = await server_join.join_computer(server_url, code["code"], say=lines.append)
    assert result["agents"] == ["codex"]
    assert not (joining_home / ".aistack/joining.json").exists()
    assert "dashboard could not confirm" in "\n".join(lines)
    assert "private response" not in "\n".join(lines)
    assert (await server_join.join_computer(server_url, code["code"], say=lambda line: None))[
        "already_connected"
    ]


async def test_new_code_after_a_denied_request_starts_over(server_url, session_factory, joining_home):
    from fastmcp.exceptions import ToolError

    owner = await join(server_url)
    denied = await call(
        server_url, owner, "add_machine", computer_code=True, options={"agents": "codex", "skills": "empty"}
    )
    running = asyncio.create_task(
        server_join.join_computer(server_url, denied["code"], say=lambda line: None)
    )
    user = await _reserved_user(session_factory, denied)
    with session_factory.begin() as session:
        computer_codes.decide(session, user, denied["id"], "deny")
    with pytest.raises(ToolError, match="make another"):
        await running
    assert (joining_home / ".aistack/joining.json").exists()
    again = await call(
        server_url,
        owner,
        "add_machine",
        computer_code=True,
        options={"agents": "codex", "approval": False, "skills": "empty"},
    )
    assert (await server_join.join_computer(server_url, again["code"], say=lambda line: None))[
        "agents"
    ] == ["codex"]
    assert await _completed(session_factory, again)
    assert not (joining_home / ".aistack/joining.json").exists()


async def test_new_code_after_a_lost_key_starts_over(server_url, session_factory, joining_home):
    owner = await join(server_url)
    lost = await call(
        server_url,
        owner,
        "add_machine",
        computer_code=True,
        options={"agents": "codex", "approval": False, "skills": "empty"},
    )
    reserved = await call(
        server_url, lost["code"], "join", pairing="reserve", machine_name="new-computer", os="LINUX"
    )
    server_join._json(
        joining_home / ".aistack/joining.json",
        reserved | {"url": server_url, "code_hash": _code_hash(lost)},
    )
    # The server committed the token, and its response never reached this computer.
    await call(server_url, reserved["request_bearer"], "join", pairing="poll")
    with pytest.raises(ValidationError, match="remove the incomplete computer"):
        await server_join.join_computer(server_url, lost["code"], say=lambda line: None)
    # Exactly what that message tells the person to do.
    with session_factory.begin() as session:
        operator_service.remove_machine(session, "dimitris", "new-computer")
    again = await call(
        server_url,
        owner,
        "add_machine",
        computer_code=True,
        options={"agents": "codex", "approval": False, "skills": "empty"},
    )
    await server_join.join_computer(server_url, again["code"], say=lambda line: None)
    assert await _completed(session_factory, again)


async def test_removed_computer_joins_again_from_a_new_code(server_url, session_factory, joining_home):
    owner = await join(server_url)
    options = {"agents": "codex", "approval": False, "skills": "empty"}
    first = await call(server_url, owner, "add_machine", computer_code=True, options=options)
    await server_join.join_computer(server_url, first["code"], say=lambda line: None)
    with session_factory.begin() as session:
        operator_service.remove_machine(session, "dimitris", "new-computer")
    # The agent configuration still holds the removed computer's key.
    second = await call(server_url, owner, "add_machine", computer_code=True, options=options)
    result = await server_join.join_computer(server_url, second["code"], say=lambda line: None)
    assert "already_connected" not in result
    assert await _completed(session_factory, second)
    config = tomllib.loads((joining_home / ".codex/config.toml").read_text())
    token = config["mcp_servers"]["aistack"]["http_headers"]["Authorization"].removeprefix("Bearer ")
    assert (await call(server_url, token, "sync", local={}, identify=True))["machine_id"]


async def test_accepted_plain_http_reaches_the_session_start_hook(server_url, joining_home):
    owner = await join(server_url)
    code = await call(
        server_url,
        owner,
        "add_machine",
        computer_code=True,
        options={"agents": "codex", "approval": False, "skills": "empty"},
    )
    await server_join.join_computer(server_url, code["code"], allow_http=True, say=lambda line: None)
    entries = json.loads((joining_home / ".codex/hooks.json").read_text())["hooks"]["SessionStart"]
    commands = [hook["command"] for entry in entries for hook in entry["hooks"]]
    assert commands[0] == "keep-me"
    assert commands[1].endswith(" sync --hook --allow-http") and len(commands) == 2


async def test_the_program_installs_before_the_code_is_reserved(server_url, session_factory, joining_home, monkeypatch):
    owner = await join(server_url)
    code = await call(server_url, owner, "add_machine", computer_code=True, options={"agents": "codex"})

    def no_uv():
        raise ValidationError("Install uv first, then run the join command again.")

    monkeypatch.setattr(server_join, "_program", no_uv)
    with pytest.raises(ValidationError, match="Install uv first"):
        await server_join.join_computer(server_url, code["code"], say=lambda line: None)
    with session_factory.begin() as session:
        assert session.get(ComputerCode, uuid.UUID(code["id"])).request_hash is None


async def test_rerun_on_a_connected_computer_sets_up_its_agents_again(server_url, joining_home):
    (joining_home / ".claude").mkdir()
    owner = await join(server_url)
    code = await call(
        server_url,
        owner,
        "add_machine",
        computer_code=True,
        options={"agents": "find", "approval": False, "skills": "empty"},
    )
    await server_join.join_computer(server_url, code["code"], say=lambda line: None)
    recorded = json.loads((joining_home / ".aistack/setup.json").read_text())
    assert recorded == {"url": server_url, "agents": ["claude-code", "codex"], "hook": True}
    # Codex lost its connection and its hook; Claude Code still holds the key.
    (joining_home / ".codex/config.toml").write_text('model = "favorite"\n')
    (joining_home / ".codex/hooks.json").write_text(json.dumps({"hooks": {"SessionStart": []}}))
    lines = []
    result = await server_join.join_computer(server_url, code["code"], say=lines.append)
    assert result["already_connected"] and result["agents"] == ["claude-code", "codex"]
    config = tomllib.loads((joining_home / ".codex/config.toml").read_text())
    token = json.loads((joining_home / ".claude.json").read_text())["mcpServers"]["aistack"]["headers"]["Authorization"]
    assert config["model"] == "favorite"
    assert config["mcp_servers"]["aistack"]["http_headers"]["Authorization"] == token
    assert "sync --hook" in (joining_home / ".codex/hooks.json").read_text()
    assert token.removeprefix("Bearer ") not in "\n".join(lines)
    assert "aist_" not in (joining_home / ".aistack/setup.json").read_text()
