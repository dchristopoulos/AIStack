"""`aistack admin`: what the person running the server does to its users, computers and
teams, run inside the container (docs/OPERATING.md). Each command is one transaction through
`operator_service`, on the server's own database setup, so it works alike on SQLite and
PostgreSQL and SQLite's cascades fire."""

import argparse
import sys
import textwrap
from datetime import datetime

from sqlalchemy.exc import OperationalError

from aistack.bootstrap.configuration.settings.settings_config import Settings
from aistack.commons.connect_commands import claude_code_command, codex_config
from aistack.commons.exceptions import AIStackError, ValidationError
from aistack.commons.text import loggable
from aistack.commons.urls import is_plain_http_url
from aistack.db.engine import build_engine, build_session_factory
from aistack.db.schema import guard_schema
from aistack.services import operator_service

OPERATING_SYSTEMS = ("macos", "windows", "linux")


def run(arguments: list[str]) -> None:
    parsed = _parser().parse_args(arguments)
    try:
        settings = Settings()
    except ValueError as error:
        # Pydantic's message names the variable, and leaves out what it was set to.
        sys.exit(f"The server's configuration is invalid.\n{error}")
    # Settled before the transaction: a new token nobody can connect with is worse than none.
    endpoint = _endpoint(settings, parsed.url) if parsed.command in (
        "rotate", "register-machine") else None
    engine = build_engine(settings.database_url)
    try:
        factory = build_session_factory(engine)
        guard_schema(factory, lambda error: AIStackError(str(error)))
        with factory.begin() as session:
            lines = _run(session, parsed, endpoint)
    except AIStackError as refusal:
        sys.exit(refusal.message)
    except OperationalError:
        sys.exit("Could not reach the server's database. Check DATABASE_URL and that the "
                 "database is running.")
    finally:
        engine.dispose()
    print("\n".join(lines))


def _run(session, parsed: argparse.Namespace, endpoint: str | None) -> list[str]:
    command = parsed.command
    if command == "machines":
        return _machine_lines(operator_service.machines(session, parsed.username))
    if command == "rotate":
        return _connect_lines(operator_service.rotate(session, parsed.username, parsed.machine),
                              endpoint, replaces=True)
    if command == "register-machine":
        if parsed.computer_code:
            from aistack.services.computer_codes import commands

            result = commands(operator_service.register_computer_code(
                session, parsed.username, parsed.machine), endpoint)
            return ["Recovery code: connects without approval. Verify who is asking before sharing it.",
                    f"Expires {result['expires_on']}. Run on the new computer:", result["command"],
                    "Use this server's deployed admin command for offboarding and forgetting accounts."]
        if parsed.machine is None or parsed.os is None:
            raise ValidationError("Legacy register-machine needs a computer name and --os. Use --computer-code for recovery with a one-use code.")
        return _connect_lines(operator_service.register_machine(
            session, parsed.username, parsed.machine, parsed.os.upper()), endpoint,
            replaces=False)
    if command == "remove-machine":
        operator_service.remove_machine(session, parsed.username, parsed.machine)
        return [f"Removed {parsed.username}'s computer '{parsed.machine}'. Its token, "
                "dashboard sessions and transfer URLs no longer work."]
    if command == "teams":
        rows = operator_service.teams(session)
        return [f"{row.team}  {row.username}  {row.role.lower()}" for row in rows] or [
            "There are no teams on this server."]
    if command == "rename-user":
        operator_service.rename_user(session, parsed.username, parsed.new)
        return [f"Renamed {parsed.username} to {parsed.new}. Every revision they pushed now "
                "shows the new name; their computers keep working."]
    if command == "name-admin":
        operator_service.name_admin(session, parsed.team, parsed.username)
        return [f"{parsed.username} is an admin of {parsed.team}."]
    if command == "forget":
        pseudonym, teams, machines = operator_service.forget(session, parsed.username,
                                                             _successors(parsed.successor))
        return [f"Forgot {parsed.username}. Teams left: {', '.join(teams) or 'none'}. "
                f"Computers removed: {', '.join(machines) or 'none'}.",
                f"Their own skills, projects and full name are deleted. What they shared into "
                f"a team stays, pushed by {pseudonym}. Rotate the server's invite code if they "
                "knew it."]
    teams, machines = operator_service.offboard(session, parsed.username,
                                                _successors(parsed.successor))
    return [f"Took {parsed.username} off the server. Teams left: "
            f"{', '.join(teams) or 'none'}. Computers removed: {', '.join(machines) or 'none'}.",
            "Their account and what they pushed stay. Rotate the server's invite code if they "
            "knew it."]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aistack admin",
        description="Manage this server's users, computers and teams. Run it where the server "
                    "runs, with the same DATABASE_URL: docker exec aistack aistack admin ...")
    commands = parser.add_subparsers(dest="command", required=True, metavar="command")

    listing = commands.add_parser("machines", help="list computers, and when each last synced")
    listing.add_argument("username", nargs="?", help="only this user's computers")

    for name, text in (("rotate", "give a computer a new token, ending the old one"),
                       ("register-machine", "register a computer for someone who has none "
                                            "left to add it from"),
                       ("remove-machine", "take a computer off the server")):
        machine = commands.add_parser(name, help=text)
        machine.add_argument("username")
        machine.add_argument("machine", nargs="?" if name == "register-machine" else None,
                             help="the computer's name, as 'machines' lists it")
        if name == "register-machine":
            machine.add_argument("--os", choices=OPERATING_SYSTEMS)
            machine.add_argument("--computer-code", action="store_true",
                                 help="issue a one-use recovery code without approval")
        if name in ("rotate", "register-machine"):
            machine.add_argument("--url", help="the address computers reach this server at, "
                                               "when AISTACK_PUBLIC_URL is not set")

    commands.add_parser("teams", help="list shared teams and who is in them")

    rename = commands.add_parser("rename-user", help="give someone a new username")
    rename.add_argument("username")
    rename.add_argument("new", help="the new username")

    admin = commands.add_parser("name-admin",
                                help="make a member the admin of a team whose admins are gone")
    admin.add_argument("team")
    admin.add_argument("username")

    for name, text in (("offboard", "take someone off the server: out of their teams, and "
                                    "every computer of theirs removed"),
                       ("forget", "offboard someone, delete their own skills, and show what "
                                  "they shared under a pseudonym")):
        leaving = commands.add_parser(name, help=text)
        leaving.add_argument("username")
        leaving.add_argument("--successor", action="append", default=[],
                             metavar="TEAM=USERNAME",
                             help="who takes over a team they are the only admin of")
    parser.set_defaults(url=None)
    return parser


def _endpoint(settings: Settings, url: str | None) -> str:
    base = settings.public_url if url is None else url.strip().rstrip("/")
    if base is None:
        sys.exit("Say where computers reach this server, with --url https://aistack.example.com, "
                 "or set AISTACK_PUBLIC_URL. Nothing was changed.")
    endpoint = f"{base}{settings.mcp_path}"
    if not is_plain_http_url(base) or not is_plain_http_url(endpoint):
        sys.exit("--url must be a plain http:// or https:// address such as "
                 "https://aistack.example.com, and AISTACK_MCP_PATH must be a plain path. "
                 "Nothing was changed.")
    return endpoint


def _successors(pairs: list[str]) -> dict[str, str]:
    successors = {}
    for pair in pairs:
        team, _, username = pair.partition("=")
        if not team or not username:
            sys.exit(f"--successor takes TEAM=USERNAME, such as acme=dimitris. "
                     f"Got '{loggable(pair)}'.")
        successors[team] = username
    return successors


def _machine_lines(rows: list[operator_service.MachineRow]) -> list[str]:
    if not rows:
        return ["There are no computers on this server."]
    return [f"{row.username}  {row.name}  {row.os.lower()}  added {_day(row.created_on)}  "
            + ("; ".join(f"{harness} synced {_day(when) if when else 'never'}"
                         for harness, when in row.last_synced.items()) or "never synced")
            for row in rows]


def _connect_lines(new: operator_service.NewToken, endpoint: str, replaces: bool) -> list[str]:
    """The token, and what to paste on that computer, printed once and never logged."""
    first = (f"New token for {new.username}'s computer '{new.machine}'. The old one has stopped "
             "working." if replaces else
             f"Registered '{new.machine}' for {new.username}.")
    return [
        first,
        "Send what follows to them over something private: it is shown only here.",
        "",
        "For Claude Code, in a terminal on that computer:",
        "",
        *([textwrap.indent("claude mcp remove aistack --scope user", "    ")] if replaces else []),
        textwrap.indent(claude_code_command(endpoint, new.token), "    "),
        "",
        "For Codex, in ~/.codex/config.toml there"
        + (", in place of the [mcp_servers.aistack] block it has:" if replaces else ":"),
        "",
        textwrap.indent(codex_config(endpoint, new.token), "    ").rstrip(),
        "",
        "Then restart the agent and say \"sync aistack\".",
    ]


def _day(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%d %H:%M UTC")
