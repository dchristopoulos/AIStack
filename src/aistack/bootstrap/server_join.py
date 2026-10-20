"""Terminal pairing and resumable local setup through the existing MCP tools (ADR-0035)."""

import argparse
import asyncio
import json
import os
import platform
import shutil
import socket
import subprocess
import tempfile
import time
import tomllib
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from fastmcp.exceptions import ToolError

from aistack.bootstrap import agent_config, self_update, sync_lock
from aistack.commons.exceptions import AIStackError, ValidationError
from aistack.commons.text import sanitized
from aistack.db.models.harness import Harness
from aistack.services import computer_codes, hardware, local_skills, server_connection, server_sync
from aistack.services.content_hash import canonical_content_hash
from aistack.services.server_connection import Connection
from aistack.services.skill_validation import validated_skill_name
from aistack.services.token_service import hash_token

JOIN_TIMEOUT = 600
POLL_INTERVAL = 2
RECOVERY = "If the connection finished but its key was lost, remove the incomplete computer and make another code with Add a computer."


def _endpoint(server: str) -> str:
    server_connection.checked_server(server, allow_http=True)
    return server.rstrip("/") + ("/mcp" if urlsplit(server).path in ("", "/") else "")


def _read(path: Path, toml: bool = False) -> dict:
    try:
        if not path.exists():
            return {}
        value = (
            tomllib.loads(path.read_text(encoding="utf-8"))
            if toml
            else json.loads(path.read_text(encoding="utf-8"))
        )
        if not isinstance(value, dict):
            raise ValueError
        return value
    except (ValueError, OSError):
        raise ValidationError(
            f"Repair {path}: it could not be read as {'TOML' if toml else 'JSON'}. No credential was printed."
        ) from None


def _write(path: Path, text: str) -> None:
    """Replace a complete file with a private temporary file on the same filesystem."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".aistack-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _json(path: Path, value: dict) -> None:
    _write(path, json.dumps(value, indent=2) + "\n")


def _agents(choice: str) -> list[str]:
    if choice != "find":
        return [choice]
    found = []
    if shutil.which("claude") or (Path.home() / ".claude").is_dir():
        found.append("claude-code")
    if shutil.which("codex") or agent_config.codex_home().is_dir():
        found.append("codex")
    if not found:
        raise ValidationError(
            "No Claude Code or Codex installation was found. Install one, or choose its name in the code's Options and try again."
        )
    return found


def _documents(agents: list[str], connection: Connection) -> dict[Path, str]:
    """Build and validate all credential-bearing documents before replacing any of them."""
    documents = {}
    for agent in agents:
        if agent == "claude-code":
            path = Path.home() / ".claude.json"
            config = _read(path)
            servers = config.setdefault("mcpServers", {})
            if not isinstance(servers, dict):
                raise ValidationError(f"Repair mcpServers in {path} before joining.")
            servers["aistack"] = {
                "type": "http",
                "url": connection.url,
                "headers": {"Authorization": "Bearer " + connection.token},
            }
            documents[path] = json.dumps(config, indent=2) + "\n"
        else:
            path = agent_config.codex_home() / "config.toml"
            _read(path, toml=True)
            text = path.read_text(encoding="utf-8") if path.exists() else ""
            kept = agent_config._without_server_tables(text)
            if "aistack" in tomllib.loads(kept).get("mcp_servers", {}):
                raise ValidationError(
                    f"Remove the inline aistack entry in {path} before joining; it cannot be replaced safely."
                )
            quote = agent_config._toml_string
            block = "\n".join(
                [
                    "[mcp_servers.aistack]",
                    f"url = {quote(connection.url)}",
                    'http_headers = { "Authorization" = '
                    + quote("Bearer " + connection.token)
                    + " }",
                    *(
                        f'tools.{tool}.approval_mode = "approve"'
                        for tool in agent_config.CODEX_APPROVED_TOOLS
                    ),
                ]
            )
            documents[path] = (kept.rstrip("\n") + "\n\n" if kept.strip() else "") + block + "\n"
            tomllib.loads(documents[path])
    return documents


def _preflight(agents: list[str], hook: bool, connection: Connection) -> None:
    documents = _documents(agents, connection)
    for path in documents:
        # Probe write access without changing existing content or credentials.
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=".aistack-check-", dir=path.parent)
        os.close(descriptor)
        Path(temporary).unlink()
    if hook:
        for agent in agents:
            path = (
                Path.home() / ".claude" / "settings.json"
                if agent == "claude-code"
                else agent_config.codex_home() / "hooks.json"
            )
            settings = _read(path)
            hooks = settings.get("hooks", {})
            if not isinstance(hooks, dict) or not isinstance(hooks.get("SessionStart", []), list):
                raise ValidationError(f"Repair hooks.SessionStart in {path} before joining.")


def _program() -> Path:
    if self_update.installed_as_uv_tool():
        return agent_config.installed_program()
    uv = self_update._uv()
    if uv is None:
        raise ValidationError("Install uv first, then run the join command again.")
    installed = subprocess.run(
        [uv, "tool", "install", "--upgrade", "aistack-mcp"], capture_output=True, timeout=120
    )
    if installed.returncode:
        raise ValidationError(
            "AIStack could not be installed. Run `uv tool install aistack-mcp`, fix the reported problem, then run join again."
        )
    directory = subprocess.run(
        [uv, "tool", "dir", "--bin"], capture_output=True, text=True, timeout=15
    )
    program = Path(directory.stdout.strip()) / ("aistack.exe" if os.name == "nt" else "aistack")
    if directory.returncode or not program.is_file():
        raise ValidationError(
            "AIStack's installed command could not be found. Check `uv tool dir --bin`, then run join again."
        )
    return program.resolve()


async def _call(connection: Connection, tool: str, **arguments) -> dict:
    async with server_connection.client(connection) as client:
        result = (await client.call_tool(tool, arguments)).structured_content
        if not isinstance(result, dict):
            raise ValidationError(
                "The server returned no usable setup result. Upgrade the server and try again."
            )
        return result


async def _capabilities(connection: Connection) -> None:
    async with server_connection.client(connection) as client:
        schema = next(
            (tool.inputSchema for tool in await client.list_tools() if tool.name == "join"), {}
        )
        if not {"pairing", "fingerprint", "setup"} <= schema.get("properties", {}).keys():
            raise ValidationError(
                "Upgrade the AIStack server to support computer codes and approval before joining this computer."
            )


async def _binding(connection: Connection, machine: str | None = None) -> str | None:
    if machine is None:
        machine = (await _call(connection, "sync", local={}, identify=True))["machine_id"]
    computer = hardware.hardware_id()
    return None if computer is None else hardware.fingerprint(uuid.UUID(machine), computer)


def _existing(url: str) -> Connection | None:
    connections = []
    for agent in agent_config.AGENTS:
        try:
            found = agent_config.remote_connection(agent)
        except agent_config.NotConnected:
            continue
        if found.url.rstrip("/") == url.rstrip("/"):
            connections.append(found)
    if any(each != connections[0] for each in connections[1:]):
        raise ValidationError(
            "The existing AIStack keys disagree. Repair the agent configurations before joining."
        )
    return connections[0] if connections else None


async def _initial_skills(
    connection: Connection, agents: list[str], home: Path
) -> tuple[int, list[str]]:
    installed = 0
    questions = []
    async with (
        server_connection.client(connection) as client,
        server_connection.http_client() as http,
    ):
        listed = (await client.call_tool("list_skills", {})).structured_content
        for agent in agents:
            harness = "claude_code" if agent == "claude-code" else "agents"
            folder = local_skills.skills_folder(Harness(harness), home)
            for skill in listed["skills"]:
                if skill["team"] is not None:
                    continue
                name = validated_skill_name(skill["name"])
                before = local_skills.observed(folder).get(name)
                result = (
                    await client.call_tool("get_skill", {"name": name, "harness": harness})
                ).structured_content
                if (folder / name).exists():
                    if before is None or canonical_content_hash(before) != result["content_hash"]:
                        questions.append(
                            f"Kept local '{name}' in {folder}. Decide whether to keep, push or restore it at sync."
                        )
                    else:
                        installed += 1
                    continue
                downloaded = await http.get(result["download_url"])
                downloaded.raise_for_status()
                if local_skills.observed(folder).get(name) != before or (folder / name).exists():
                    questions.append(
                        f"Kept '{name}' because its local files changed during setup. Decide at sync."
                    )
                    continue
                local_skills.install(folder, name, downloaded.content, result["content_hash"])
                installed += 1
    return installed, questions


def _configure(agents: list[str], connection: Connection, hook: bool, program: Path, allow_http: bool) -> None:
    # All document parsing succeeds before any file receives the permanent key.
    for path, text in _documents(agents, connection).items():
        _write(path, text)
    for agent in agents:
        agent_config.skills_folder(agent).mkdir(parents=True, exist_ok=True)
        if hook:
            path = agent_config.add_session_start_hook(
                agent, agent_config.server_hook_command(program, allow_http)
            )
            _write(path, path.read_text(encoding="utf-8"))


def _holds(agent: str, connection: Connection) -> bool:
    try:
        return agent_config.remote_connection(agent) == connection
    except agent_config.NotConnected:
        return False


async def _repair(connection: Connection, url: str, allow_http: bool) -> list[str]:
    """Set up again what a finished join set up, from the choices it recorded (ADR-0035)."""
    chosen = _read(Path.home() / ".aistack" / "setup.json")
    if chosen.get("url") != url:
        # Set up some other way: keep to the agents that hold this connection, add no hook.
        chosen = {"agents": [agent for agent in agent_config.AGENTS if _holds(agent, connection)], "hook": False}
    agents = [agent for agent in chosen.get("agents", []) if agent in agent_config.AGENTS]
    hook = chosen.get("hook") is True
    program = await asyncio.to_thread(_program)
    _preflight(agents, hook, connection)
    _configure(agents, connection, hook, program, allow_http)
    return agents


async def join_computer(server: str, code: str, *, allow_http: bool = False, say=print) -> dict:
    home = Path.home()
    url = _endpoint(server)
    warning = server_connection.checked_server(url, allow_http)
    if warning:
        say(warning)
    state_path = home / ".aistack" / "joining.json"
    code_hash = hash_token(computer_codes.normalized(code) or code)
    with sync_lock.locked(home):
        state = _read(state_path)
        if state and state.get("url") != url:
            raise ValidationError(
                "Another AIStack setup is unfinished. Finish it first, or remove its incomplete computer and .aistack/joining.json before changing servers."
            )
        # The same command resumes; a new code is the person starting over after a
        # refusal or a lost key, so the earlier request must not be retried instead.
        if state.get("code_hash") != code_hash:
            state = {}
        # Existing configuration warrants "already connected" only after authentication
        # and the copied-computer check succeed. No used-code lookup can establish it.
        existing = _existing(url)
        if existing and not state:
            try:
                binding = await _binding(existing)
                await _call(existing, "sync", local={}, identify=True, fingerprint=binding)
            except ToolError:
                existing = None
            except httpx.HTTPStatusError as error:
                # A removed or rotated computer's key: pair again from the new code.
                if error.response.status_code != 401:
                    raise
                existing = None
            else:
                agents = await _repair(existing, url, allow_http)
                reports = await server_sync.sync_computer(existing, home, home)
                say("This computer is already connected to AIStack." + (f" Set up {', '.join(agents)} again." if agents else ""))
                say(server_sync.output(reports, False))
                return {"agents": agents, "skills": 0, "already_connected": True}
        async with asyncio.timeout(JOIN_TIMEOUT):
            # Install first: a computer that cannot run the program stops before its code is
            # reserved, and no request waits in Add a computer for a setup that cannot finish.
            program = await asyncio.to_thread(_program)
            if not state:
                bootstrap = Connection(url, code)
                await _capabilities(bootstrap)
                # Refuse malformed existing files before consuming the code, even when
                # the chosen agent is not known until reservation returns its options.
                for path, toml in (
                    (home / ".claude.json", False),
                    (agent_config.codex_home() / "config.toml", True),
                ):
                    _read(path, toml)
                reserved = await _call(
                    bootstrap,
                    "join",
                    pairing="reserve",
                    machine_name=socket.gethostname(),
                    os={"Darwin": "MACOS", "Windows": "WINDOWS"}.get(platform.system(), "LINUX"),
                )
                state = reserved | {"url": url, "code_hash": code_hash}
                _json(state_path, state)
            selected = state["options"]
            agents = _agents(selected["agents"])
            _preflight(agents, selected["hook"], Connection(url, "<pending>"))
            if "token" not in state:
                request = Connection(url, state["request_bearer"])
                binding = await _binding(request, state["machine_id"])
                if binding is None:
                    say(
                        "No OS computer id could be read; copied connections cannot be detected here."
                    )
                deadline = time.monotonic() + JOIN_TIMEOUT
                if selected["approval"]:
                    say(
                        "Waiting for approval in Add a computer. Keep that dialog open; approve only the request you just started."
                    )
                while True:
                    connected = await _call(request, "join", pairing="poll", fingerprint=binding)
                    if connected["status"] == "connected":
                        if "token" not in connected:
                            raise ValidationError(RECOVERY)
                        state.update(connected)
                        _json(state_path, state)
                        break
                    if time.monotonic() >= deadline:
                        raise ValidationError(
                            "Still waiting for approval. Approve the request, then run the same command again to resume."
                        )
                    await asyncio.sleep(POLL_INTERVAL)
            connection = Connection(url, state["token"])
            binding = await _binding(connection, state["machine_id"])
            await _call(connection, "sync", local={}, identify=True, fingerprint=binding)
            _configure(agents, connection, selected["hook"], program, allow_http)
            installed, questions = (0, [])
            if selected["skills"] == "library":
                installed, questions = await _initial_skills(connection, agents, home)
            reports = await server_sync.sync_computer(connection, home, home)
            result = {"agents": agents, "skills": installed}
            try:
                await _call(
                    Connection(url, state["request_bearer"]),
                    "join",
                    pairing="confirm",
                    setup=result,
                )
            except Exception:
                # Configuration and sync already succeeded. A lost acknowledgement or
                # expired request must not retain a second permanent credential store.
                say("Setup finished here, but the dashboard could not confirm completion.")
            # No credential: what a rerun on this computer sets up again.
            _json(home / ".aistack" / "setup.json", {"url": url, "agents": agents, "hook": selected["hook"]})
            state_path.unlink()
            say(f"Connected {', '.join(agents)} to AIStack; installed {installed} skills.")
            for question in questions:
                say(sanitized(question))
            say(server_sync.output(reports, False))
            say(
                "Sync, list, install and private backup are approved in Codex; other tools still ask. Trust its hook once in /hooks if selected."
                if "codex" in agents
                else "Keep your agent’s usual tool approval prompts."
            )
            say("Restart your coding agent once.")
            return result


def run(arguments: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="aistack join")
    parser.add_argument("server")
    parser.add_argument("code")
    parser.add_argument("--allow-http", action="store_true")
    parsed = parser.parse_args(arguments)
    try:
        asyncio.run(join_computer(parsed.server, parsed.code, allow_http=parsed.allow_http))
    except (AIStackError, ToolError) as error:
        parser.exit(1, sanitized(str(error)) + "\n")
    except agent_config.NotConnected:
        parser.exit(1, "Repair the agent configuration and run join again.\n")
    except (Exception, KeyboardInterrupt):
        parser.exit(
            1, "AIStack setup did not finish. Run the same command to resume. " + RECOVERY + "\n"
        )
