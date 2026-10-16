"""`aistack admin`, the operator's commands (AUTO-15, PH-18), on SQLite and PostgreSQL."""

import re
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError

from aistack.bootstrap import admin_cli
from aistack.db.engine import build_session_factory
from aistack.db.models.machine import Machine
from aistack.db.models.machine_harness import MachineHarness
from aistack.db.models.harness import Harness
from aistack.db.models.user import User
from aistack.services import onboarding_service, skill_service, team_service, visibility
from tests.archives import skill_archive
from aistack.services.token_service import hash_token

OPERATING = Path(__file__).parents[2] / "docs" / "OPERATING.md"
URL = "https://aistack.example.com"


@pytest.fixture(name="server")
def server_fixture(portable_engine, monkeypatch, tmp_path):
    """The database a server runs on, with maria and dimitris in team acme."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATABASE_URL", portable_engine.url.render_as_string(hide_password=False))
    monkeypatch.delenv("AISTACK_PUBLIC_URL", raising=False)
    factory = build_session_factory(portable_engine)
    with factory.begin() as session:
        maria = onboarding_service.join(session, "maria", "laptop", "MACOS")
        dimitris = onboarding_service.join(session, "dimitris", "desktop", "LINUX")
        session.add(MachineHarness(machine_id=maria.machine.machine_id,
                                   harness=Harness.CLAUDE_CODE))
        team_service.create_team(session, dimitris.user.user_id, "acme")
        code = team_service.new_invite_code(session, dimitris.user.user_id, "acme")
        team_service.admit(session, team_service.invited_to(session, code), maria.user.user_id)
    return factory


def _admin(capsys, *arguments) -> str:
    admin_cli.run(list(arguments))
    return capsys.readouterr().out


def _refused(capsys, *arguments) -> str:
    with pytest.raises(SystemExit) as exit:
        admin_cli.run(list(arguments))
    assert capsys.readouterr().out == ""
    return str(exit.value.code)


def _machines(factory) -> dict[str, str]:
    with factory.begin() as session:
        return {machine.name: machine.token_hash for machine in session.scalars(select(Machine))}


def _token(output: str) -> str:
    return re.search(r"Bearer (aist_[A-Za-z0-9_-]+)", output).group(1)


def test_machines_lists_each_computer_and_when_each_harness_synced(server, capsys):
    output = _admin(capsys, "machines")

    assert output.splitlines()[0].startswith("dimitris  desktop  linux  added ")
    assert output.splitlines()[0].endswith("never synced")
    assert re.match(r"maria  laptop  macos  added .* claude_code synced never$",
                    output.splitlines()[1])
    assert _admin(capsys, "machines", "maria").count("\n") == 1


def test_rotate_replaces_the_token_and_prints_how_to_reconnect(server, capsys):
    before = _machines(server)["laptop"]

    output = _admin(capsys, "rotate", "maria", "laptop", "--url", URL)

    token = _token(output)
    assert _machines(server)["laptop"] == hash_token(token) != before
    assert "claude mcp remove aistack --scope user" in output
    assert (f"claude mcp add --transport http --scope user aistack {URL}/mcp "
            f'--header "Authorization: Bearer {token}"') in output
    assert f'url = "{URL}/mcp"' in output and "[mcp_servers.aistack]" in output


def test_a_new_token_waits_for_an_address_to_connect_with(server, capsys, monkeypatch):
    before = _machines(server)

    assert "--url" in _refused(capsys, "rotate", "maria", "laptop")
    assert "plain http" in _refused(capsys, "rotate", "maria", "laptop", "--url", "ftp://x")

    assert _machines(server) == before
    monkeypatch.setenv("AISTACK_PUBLIC_URL", URL)
    assert f"{URL}/mcp" in _admin(capsys, "rotate", "maria", "laptop")


def test_register_machine_lets_someone_with_no_computer_back_in(server, capsys):
    output = _admin(capsys, "register-machine", "maria", "new-laptop", "--os", "windows",
                    "--url", URL)

    assert _machines(server)["new-laptop"] == hash_token(_token(output))
    assert "claude mcp remove" not in output


def test_remove_machine_takes_even_the_last_computer_off(server, capsys):
    output = _admin(capsys, "remove-machine", "maria", "laptop")

    assert "Removed maria's computer 'laptop'" in output
    assert "laptop" not in _machines(server)


def test_teams_lists_shared_teams_and_leaves_personal_ones_out(server, capsys):
    assert _admin(capsys, "teams").splitlines() == ["acme  dimitris  admin",
                                                    "acme  maria  member"]


def test_name_admin_makes_a_member_the_admin(server, capsys):
    _admin(capsys, "name-admin", "acme", "maria")

    assert "acme  maria  admin" in _admin(capsys, "teams")


def test_offboard_hands_over_the_teams_and_removes_every_computer(server, capsys):
    refusal = _refused(capsys, "offboard", "dimitris")
    assert "only admin of team 'acme'" in refusal
    assert "desktop" in _machines(server)

    output = _admin(capsys, "offboard", "dimitris", "--successor", "acme=maria")

    assert "Teams left: acme. Computers removed: desktop." in output
    assert "desktop" not in _machines(server)
    assert _admin(capsys, "teams").splitlines() == ["acme  maria  admin"]


@pytest.mark.parametrize("arguments", [
    ("machines", "mario"),
    ("rotate", "mario", "laptop", "--url", URL),
    ("register-machine", "mario", "pc", "--os", "linux", "--url", URL),
    ("remove-machine", "mario", "laptop"),
    ("name-admin", "acme", "mario"),
    ("offboard", "mario"),
])
def test_an_unknown_username_exits_with_a_sentence(server, capsys, arguments):
    before = _machines(server)

    assert "mario" in _refused(capsys, *arguments)
    assert _machines(server) == before


def test_an_unknown_computer_exits_with_a_sentence(server, capsys):
    assert _refused(capsys, "remove-machine", "maria", "desktop") == (
        "'maria' has no computer named 'desktop'.")


def test_the_command_runs_as_aistack_admin(server, tmp_path):
    result = subprocess.run([sys.executable, "-m", "aistack.bootstrap", "admin", "teams"],
                            capture_output=True, text=True, timeout=60)

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["acme  dimitris  admin", "acme  maria  member"]


def test_operating_has_no_python_to_copy():
    assert "```python" not in OPERATING.read_text()


def test_a_new_token_reaches_the_terminal_and_never_the_log(server, capsys, caplog):
    caplog.set_level("DEBUG")

    token = _token(_admin(capsys, "rotate", "maria", "laptop", "--url", URL))

    assert "Machine token rotated by the operator" in caplog.text
    assert token not in caplog.text


def test_no_tool_or_route_reaches_the_operators_service():
    source = Path(__file__).parents[2] / "src" / "aistack"
    reaching = [path.relative_to(source).as_posix()
                for folder in ("mcp", "api") for path in (source / folder).rglob("*.py")
                if "operator_service" in path.read_text()]
    assert reaching == []


def test_a_malformed_successor_is_escaped_and_changes_nothing(server, capsys):
    before = _machines(server)

    refusal = _refused(capsys, "offboard", "dimitris", "--successor", "acme\n\x1b[31m")

    assert "acme\\n\\x1b[31m" in refusal
    assert "\n" not in refusal and "\x1b" not in refusal
    assert _machines(server) == before


def test_a_reconnect_address_checks_the_mcp_path_before_minting_a_token(
        server, capsys, monkeypatch):
    before = _machines(server)
    monkeypatch.setenv("AISTACK_MCP_PATH", "/mcp;echo unsafe")

    assert "plain http" in _refused(capsys, "rotate", "maria", "laptop", "--url", URL)

    assert _machines(server) == before


def test_admin_commands_refuse_a_schema_this_release_cannot_use(server, capsys):
    before = _machines(server)
    with server.begin() as session:
        session.execute(text("UPDATE alembic_version SET version_num = '9999'"))
        session.execute(text("UPDATE schema_compatibility SET "
                             "oldest_compatible_revision = '9999', "
                             "written_by_release = '9.9.0'"))

    assert "Run that release or a newer one" in _refused(
        capsys, "remove-machine", "maria", "laptop")

    assert _machines(server) == before


def test_a_database_failure_leaves_driver_details_out_of_the_error(
        server, capsys, monkeypatch):
    def unavailable(*arguments):
        raise OperationalError(None, None, Exception("password=private-database-secret"))

    monkeypatch.setattr(admin_cli.operator_service, "machines", unavailable)

    refusal = _refused(capsys, "machines")

    assert "Check DATABASE_URL" in refusal
    assert "private-database-secret" not in refusal


def test_rename_user_renames_their_personal_team_and_their_revisions_follow(server, capsys):
    with server.begin() as session:
        maria = session.scalar(select(User).where(User.username == "maria"))
        skill_service.push(session, session.scalar(select(Machine.machine_id).where(
            Machine.user_id == maria.user_id)), maria.user_id, "wizard", None,
            skill_archive("wizard"))

    assert "Renamed maria to maria.k" in _admin(capsys, "rename-user", "maria", "maria.k")

    with server.begin() as session:
        renamed = session.scalar(select(User).where(User.username == "maria.k"))
        assert visibility.personal_team(session, renamed.user_id).name == "maria.k"
        assert [skill.pushed_by for skill in skill_service.list_skills(
            session, renamed.user_id)] == ["maria.k"]
    assert "laptop" in _machines(server)


@pytest.mark.parametrize("taken", ["dimitris", "acme"])
def test_rename_user_refuses_a_name_a_user_or_a_team_has(server, capsys, taken):
    assert "already called" in _refused(capsys, "rename-user", "maria", taken)

    with server.begin() as session:
        assert session.scalar(select(User).where(User.username == "maria")) is not None
