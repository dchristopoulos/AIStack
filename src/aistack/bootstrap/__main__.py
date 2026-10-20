import argparse
import asyncio
import logging
import os
import shutil
import signal
import sys
import time
from pathlib import Path

import fastmcp
import uvicorn
from fastmcp.exceptions import ToolError
from sqlalchemy.exc import OperationalError

from aistack.bootstrap import admin_cli, agent_config, github_setup, self_update
from aistack.bootstrap.configuration.settings.settings_config import (
    LIBRARY_FILE,
    DatabaseSettings,
    LocalSettings,
    Settings,
    described,
    record_place,
)
from aistack.bootstrap.context.application_context import (
    build_application_context,
    build_local_context,
    dispose_application_context,
    needs_newer_release,
)
from aistack.bundled import local_setup_instructions, local_sync_skill_document
from aistack.commons import request_id
from aistack.commons.exceptions import AIStackError
from aistack.commons.release import release
from aistack.commons.text import loggable
from aistack.db import backup
from aistack.db.engine import build_engine
from aistack.db.schema import ForeignDatabase, NewerSchema
from aistack.mcp.argument_errors import argument_problems

logger = logging.getLogger(__name__)

# The request id ties together the lines one HTTP request wrote; '-' outside one.
LOG_FORMAT = "%(asctime)s %(levelname)-8s %(request_id)s [%(name)s.%(funcName)s] %(message)s"
# RFC 3339 with the offset, so a line read on another computer or beside another log is not
# off by a time zone (STD-11).
LOG_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S%z"

# Loggers that print raw protocol payloads at DEBUG. A tool result containing a machine token
# goes over the wire in plaintext by definition, so at DEBUG these write the token to the log
# file: the one place the secrets rule says it must never appear. They are floored at INFO
# regardless of AISTACK_LOG_LEVEL rather than trusted to the operator's choice of level.
# FastMCP joins them once its records reach the root logger: at DEBUG it writes every tool
# call's arguments, a team's invite code among them.
WIRE_LOGGERS = ("mcp.client", "mcp.server.streamable_http", "sse_starlette", "httpcore", "httpx",
                "fastmcp")

# Floored at WARNING. FastMCP's own line for a rejected bearer: AIStack logs the rejection,
# with the address, so at INFO this second line would only double what a flood costs the log.
# And the MCP SDK's two lines around every request, "Processing request of type ..." and
# "Terminating session: None", which buried AIStack's one line per call (IMP-18).
QUIET_LOGGERS = ("fastmcp.server.auth.middleware", "mcp.server.lowlevel.server",
                 "mcp.server.streamable_http")

# Where FastMCP 3.4.7 logs a call's arguments when they fail validation.
ARGUMENT_ECHO_LOGGER = "fastmcp.server.server"


def configure_logging(log_level: str) -> None:
    request_id.install()
    logging.basicConfig(level=log_level, format=LOG_FORMAT, datefmt=LOG_DATE_FORMAT, force=True)
    _route_fastmcp_through_root()
    chosen = logging.getLevelName(log_level)
    for wire_logger in WIRE_LOGGERS:
        logging.getLogger(wire_logger).setLevel(max(logging.INFO, chosen))
    # Only ever raised: a floor below the operator's level would let these through it.
    for quiet_logger in QUIET_LOGGERS:
        logging.getLogger(quiet_logger).setLevel(max(logging.WARNING, chosen))


def _route_fastmcp_through_root() -> None:
    """Send FastMCP's records through the root handler, its argument echo removed (SEC-03).

    FastMCP gives its logger two Rich handlers and stops propagation, so its lines skip
    LOG_FORMAT, AISTACK_LOG_LEVEL, and every filter here. Turning its own setup off keeps a
    later `run(log_level=...)` from putting them back.
    """
    fastmcp.settings.log_enabled = False
    fastmcp_logger = logging.getLogger("fastmcp")
    for handler in fastmcp_logger.handlers[:]:
        fastmcp_logger.removeHandler(handler)
    fastmcp_logger.propagate = True
    # On the logger that writes the line, so it runs before any handler sees the record.
    echoing = logging.getLogger(ARGUMENT_ECHO_LOGGER)
    if not any(isinstance(existing, WithoutArgumentValues) for existing in echoing.filters):
        echoing.addFilter(WithoutArgumentValues())


class WithoutArgumentValues(logging.Filter):
    """Keep the tool name and which fields failed from FastMCP's 'Invalid arguments' line.

    The values are what the caller sent, and for `join_team` that is a team's invite code
    under whatever name or shape the agent put it.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str) and record.msg.startswith("Invalid arguments for tool"):
            tool, detail = (record.args + (None, None))[:2] if isinstance(record.args, tuple) \
                else (None, None)
            record.msg = "Invalid arguments for tool '%s'. Fields: '%s'."
            record.args = (loggable(tool), loggable(argument_problems(detail)))
        return True


async def main() -> None:
    settings = Settings()
    configure_logging(settings.log_level)
    if Path(".env").is_file():
        # Settings read it, DATABASE_URL included, so a server started inside some project
        # says whose configuration it took.
        logger.info(f"Read configuration from {Path('.env').resolve()}.")

    build_application_context(settings)

    # Imported after the context is built, so a missing invite code fails before a port opens.
    from aistack.mcp.mcp import run_http_stream_server

    await run_http_stream_server(host=settings.host, port=settings.port,
                                 path=settings.mcp_path, log_level=settings.log_level)


def serve_local() -> None:
    """Local mode (ADR-0020): one person's Library, served over stdio to the agent that
    started this process. stdout is the protocol, so logging goes to stderr only."""
    settings = LocalSettings()
    configure_logging(settings.log_level)
    build_local_context(settings)
    # The agent starts this process in the open project, and Windows runs a program named by
    # its bare name from the current folder first: a project's git.exe or uv.exe would run.
    # Nothing here reads a path relative to the project.
    os.chdir(settings.home)
    logger.info(f"AIStack {release()} is serving the Library over stdio.")
    if settings.auto_update:
        # At once, not after the daily wait, when the Library needs a newer release (ADR-0024).
        self_update.start_in_background(settings.home, force=needs_newer_release())

    from aistack.mcp.local import local_mcp

    local_mcp.run(transport="stdio", show_banner=False, log_level=settings.log_level)


async def serve_dashboard() -> None:
    """`aistack dashboard`: the same page as a server's, for this computer's Library, on
    127.0.0.1, opened in the browser with a sign-in link that works once, for five minutes."""
    settings = LocalSettings().resolved(record=False)
    configure_logging(settings.log_level)
    build_local_context(settings)

    from aistack.bootstrap.context.application_context import (
        get_local_principal,
        get_ticket_signer,
    )
    from aistack.mcp.local_dashboard import listen, open_in_browser
    from aistack.mcp.mcp import dashboard_server_config
    from aistack.mcp.server_url import DASHBOARD_LOGIN_PATH

    # This Library's own port when it is free, so the browser keeps its choices; another
    # otherwise. The link names whichever it got.
    listener = listen()
    port = listener.getsockname()[1]
    ticket = get_ticket_signer().sign_dashboard_link(get_local_principal().dashboard_holder())
    link = f"http://127.0.0.1:{port}{DASHBOARD_LOGIN_PATH}/{ticket}"

    # The link is a credential, so it goes to this terminal and the browser, never a log.
    opened = open_in_browser(link)
    print(f"AIStack dashboard: http://127.0.0.1:{port}/app (Ctrl-C stops it)\n"
          + ("Opened it in your browser. " if opened else "")
          + f"Sign-in link, which works once within five minutes: {link}", flush=True)
    await uvicorn.Server(dashboard_server_config(settings.log_level)).serve(sockets=[listener])


def check_local() -> None:
    """`aistack check`: set up this computer's side of the Library once, and say whether it
    works. Setup runs it before connecting an agent, which would hide a failure. Setup runs
    it with the place the agent gets, so it records that place for the other commands."""
    settings = LocalSettings().resolved(record=True)
    configure_logging(settings.log_level)
    build_local_context(settings)

    from aistack.bootstrap.context.application_context import (
        get_local_principal,
        get_session_factory,
        library_description,
    )
    from aistack.services import library_log

    try:
        get_local_principal()
    except AIStackError as refusal:
        if needs_newer_release() and settings.auto_update:
            installed = self_update.check_and_upgrade(settings.home, force=True)
            if installed:
                sys.exit(f"AIStack {installed} is installed: the Library needed a newer "
                         "release. Run this again, and restart your coding agent.")
        sys.exit(f"AIStack is not ready. {refusal}")
    library = library_description()
    if library["kind"] == "github":
        with get_session_factory().begin() as session:
            if library_log.unpublished(session):
                sys.exit(f"AIStack is not ready. It could not push to {library['repository']}. "
                         "Check that `gh auth status` shows you signed in as someone who can "
                         "write to it.")
    where = {
        "this_computer": "on this computer only",
        "github": f"in the GitHub repository {library.get('repository')}",
        "postgresql": f"in a {library.get('provider')} database at {library.get('host')}",
    }[library["kind"]]
    print(f"AIStack is ready. Your Library lives {where}.")


def write_sync_skill(skills_folder: Path) -> None:
    """`aistack sync-skill <skills folder>`: setup's step, the same on every system. Windows
    PowerShell 5.1 writes UTF-16 through `>`, which no agent reads as a skill."""
    print(f"Wrote {agent_config.write_sync_skill(skills_folder)}.")


def use_agent_place(agent: str) -> None:
    """`--agent`: start with the Library settings the agent starts AIStack with. They are
    read from its config and never shown, because a database address holds a password."""
    place = agent_config.configured_place(agent)
    if not place and not agent_config.has_entry(agent):
        sys.exit(f"{agent} has no AIStack connection on this computer. Run setup first.")
    for name in agent_config.PLACE_VARIABLES:
        os.environ.pop(name, None)
    os.environ.update(place)


def recorded_place(agent: str) -> dict[str, str]:
    """With no place in the environment: where `check` or `move` last recorded the Library, so
    a connection made after a move follows it. A database's address is never written down, so
    for one the agent's existing connection supplies it; with nothing recorded, that
    connection is brought up to date as it is."""
    settings = LocalSettings()
    if not (settings.home / LIBRARY_FILE).exists():
        return agent_config.configured_place(agent)
    try:
        settings = settings.resolved(record=False)
    except ValueError as refusal:
        configured = agent_config.configured_place(agent)
        if "AISTACK_DATABASE_URL" in configured:
            return configured
        sys.exit(str(refusal))
    if settings.library_repo:
        return {"AISTACK_LIBRARY_REPO": settings.library_repo}
    if settings.database_url:
        return {"AISTACK_DATABASE_URL": settings.database_url}
    return {}


def connect_agent(agent: str, hook: bool) -> None:
    """`aistack connect claude-code|codex`: check the Library, install the sync skill, and
    connect the agent, by this program's full path. Running it again changes nothing.

    The Library's place comes from the environment, as `check` reads it, or else from where
    the Library was last recorded (`recorded_place`)."""
    if not self_update.installed_as_uv_tool():
        sys.exit("Install AIStack first with `uv tool install aistack-mcp`, then run this "
                 "from the installed command, so your agent can start it offline.")
    place = agent_config.place_from_environment()
    if not place.keys() & {"AISTACK_LIBRARY_REPO", "AISTACK_DATABASE_URL"}:
        place = recorded_place(agent) | place
        os.environ.update(place)
    check_local()
    program = agent_config.installed_program()
    print(f"Wrote {agent_config.write_sync_skill(agent_config.skills_folder(agent))}.")
    if agent == "claude-code":
        agent_config.connect_claude_code(program, place)
    else:
        agent_config.connect_codex(program, place)
    print(f"Connected {agent} to AIStack at {program}.")
    if hook:
        added = agent_config.add_session_start_hook(
            agent, agent_config.hook_command(program, agent))
        print(f"Added the sync reminder at session start to {added}.")


def status_hook(agent: str | None) -> None:
    """`aistack status --hook`: the session-start reminder to sync, printed only when a sync of
    this computer's folders would have something to do (AUTO-24). It never fails a session:
    anything it cannot settle prints the reminder."""
    try:
        quiet = _nothing_to_sync(agent)
    except (Exception, SystemExit):
        quiet = False
    if not quiet:
        print(agent_config.HOOK_REMINDER)


def _nothing_to_sync(agent: str | None) -> bool:
    if agent:
        use_agent_place(agent)
    settings = LocalSettings().resolved(record=False)
    if settings.place() is None and not (settings.home / "aistack.db").exists():
        return False
    configure_logging("ERROR")
    build_local_context(settings)
    return not sync_would_act()


def sync_would_act() -> bool:
    """Whether a sync of every skills folder this computer has would report something to do,
    against the Library the running context opened."""
    from aistack.bootstrap.context.application_context import (
        get_local_principal,
        get_session_factory,
        library_before_read,
        library_problem,
    )
    from aistack.db.models.harness import Harness
    from aistack.services import local_skills, sync_service

    library_before_read(force=True)
    if library_problem() is not None:
        return True
    caller = get_local_principal()
    for harness in local_skills.folders_in_use(Path.home()):
        local = local_skills.observed(local_skills.skills_folder(Harness(harness), Path.home()))
        # The sync a session would run, rolled back: it records that the folder synced.
        with get_session_factory()() as session:
            try:
                report = sync_service.sync(session, caller.machine_id, caller.user_id, local,
                                           harness)
            finally:
                session.rollback()
        if (report.install or report.update or report.ask or report.backup
                or report.team_updates or report.first_sync):
            return True
    return False


def export_library(destination: Path) -> None:
    """`aistack export <folder>`: every skill in this Library as a skill folder (ADR-0020).

    To move them into another Library, a team's server above all, copy the folders into a
    skills folder on a computer connected to it and sync: sync backs up what is new.
    """
    if destination.exists() and any(destination.iterdir()):
        sys.exit(f"{destination} already has files in it. Export into a new or empty folder, "
                 "so nothing there is replaced.")
    settings = LocalSettings().resolved(record=False)
    if settings.place() is None and not (settings.home / "aistack.db").exists():
        # Opening it would make an empty Library here and export nothing from it.
        sys.exit("There is no Library on this computer to export. If your coding agent's "
                 "Library lives on GitHub or in a database, start the agent once, or set "
                 "AISTACK_LIBRARY_REPO or AISTACK_DATABASE_URL as its settings do.")
    configure_logging(settings.log_level)
    build_local_context(settings)

    from aistack.bootstrap.context.application_context import (
        get_local_principal,
        get_session_factory,
    )
    from aistack.services import local_skills, skill_service

    caller = get_local_principal()
    with get_session_factory().begin() as session:
        skills = skill_service.export_library(session, caller.user_id)
    # Packed and written after the transaction, through the same checks an install makes.
    for skill in skills:
        local_skills.install(destination, skill.name, skill.archive(), skill.content_hash)
    shutil.rmtree(destination / local_skills.STAGING_FOLDER, ignore_errors=True)
    print(f"Exported {len(skills)} skills to {destination}.")


# Where `aistack move` can take a Library, by the word a person types.
MOVE_DESTINATIONS = {"github": "github", "postgresql": "postgresql", "here": "this_computer"}
# The new database's address, for `aistack move postgresql`. AISTACK_DATABASE_URL already
# names the Library being moved when that one is a database.
MOVE_TO_URL = "AISTACK_MOVE_TO_URL"


def move_library(destination: str, repository: str | None) -> None:
    """`aistack move github|postgresql|here`: the Library this computer's agent uses, with its
    whole history, placements and removals, replayed into the new place (ADR-0025). The old
    place is left as it was."""
    from aistack.services import library_move
    from aistack.services.library_repo import LibraryRepo, RepoUnavailable

    kind = MOVE_DESTINATIONS[destination]
    settings = LocalSettings().resolved(record=False)
    source = settings.place() or {"kind": "this_computer"}
    if source["kind"] == kind:
        sys.exit(f"Your Library already lives {described(source)}.")
    if source["kind"] == "this_computer" and not (settings.home / "aistack.db").exists():
        sys.exit("There is no Library on this computer to move. Set AIStack up with "
                 "`aistack setup`, choosing where the Library lives.")
    target_url = os.environ.get(MOVE_TO_URL) if kind == "postgresql" else None
    if kind == "postgresql" and not target_url:
        sys.exit(f"Set {MOVE_TO_URL} to the new database's postgresql:// address, then run "
                 "this again.")

    configure_logging(settings.log_level)
    build_local_context(settings)
    from aistack.bootstrap.context import application_context

    try:
        application_context.get_local_principal()
        # A GitHub Library is moved as the repository has it, not as this copy last saw it.
        application_context.library_before_read(force=True)
    except AIStackError as refusal:
        sys.exit(f"The Library cannot be read, so nothing was moved. {refusal}")
    with application_context.get_session_factory().begin() as session:
        log = library_move.events(session)
        contents = library_move.contents(session)
    application_context.dispose_application_context()
    library_move.check_replays(log, contents, settings.home)

    if kind == "github":
        if repository is None:
            status, repository = github_setup.repository_for(settings.home)
            if repository is None:
                sys.exit(status)
        # What a GitHub Library used before is kept, never replaced: renamed aside.
        stamp = time.strftime("%Y%m%d-%H%M%S")
        for name in ("library", "github-copy.db", "github-copy.db-wal", "github-copy.db-shm"):
            old = settings.home / name
            if old.exists():
                old.rename(settings.home / f"{name}.before-move-{stamp}")
        try:
            added = library_move.into_repository(
                LibraryRepo(settings.home / "library", repository), log)
        except RepoUnavailable as error:
            sys.exit(f"Could not publish the Library to {repository}, so it still lives "
                     f"{described(source)}. {error} Run this again once it can be reached.")
        place = {"kind": "github", "repository": repository}
        variable = f"AISTACK_LIBRARY_REPO={repository}"
        print(f"Published {added} changes to {repository}.")
    else:
        url = target_url or f"sqlite:///{(settings.home / 'aistack.db').as_posix()}"
        engine = build_engine(url)
        try:
            library_move.into_database(engine, log)
        finally:
            engine.dispose()
        place = (LocalSettings(aistack_home=settings.home, aistack_database_url=url).place()
                 if target_url else {"kind": "this_computer"})
        variable = (f"AISTACK_DATABASE_URL set to the address in {MOVE_TO_URL}"
                    if target_url else "no AISTACK_ variable")
        print(f"Copied {len(log)} changes into the new place.")
    record_place(settings.home, place)
    print(f"Your Library now lives {described(place)}, with its history. The old place is "
          f"left as it was. Connect your coding agent to the new place, with {variable}, "
          "and restart it once.")


def back_up_database(target: Path) -> None:
    """`aistack backup <file>`: a copy of the server's database that restores, safe to take
    while the server runs. On PostgreSQL it says how to use pg_dump instead."""
    engine = build_engine(DatabaseSettings().database_url)
    try:
        print(f"Backed up the database to {backup.back_up(engine, target)}.")
    finally:
        engine.dispose()


def restore_database(source: Path) -> None:
    """`aistack restore <file>`: replace the server's database with a backup, with the server
    stopped. The database it replaces is kept beside it."""
    engine = build_engine(DatabaseSettings().database_url)
    try:
        kept = backup.restore(engine, source)
    finally:
        engine.dispose()
    print(f"Restored the database from {source}."
          + (f" The one it replaced is kept at {kept}." if kept else "")
          + " Start the release that made the backup, or a newer one.")


def _exit_on_terminate(signal_number, _frame) -> None:
    raise SystemExit(128 + signal_number)


def run() -> None:
    """The `aistack` command: `aistack` is local mode, `aistack serve` the server."""
    # uvicorn hands a SIGTERM (`docker stop`) back to the handler it found once it has shut
    # down. The default one ends the process on the spot, past the `finally` below that
    # closes the database; this one exits through it.
    signal.signal(signal.SIGTERM, _exit_on_terminate)
    # Before anything logs with LOG_FORMAT, which names the request id.
    request_id.install()
    if sys.argv[1:2] == ["admin"]:
        admin_cli.run(sys.argv[2:])
        return
    if sys.argv[1:2] == ["join"]:
        from aistack.bootstrap import server_join

        configure_logging("WARNING")
        server_join.run(sys.argv[2:])
        return
    parser = argparse.ArgumentParser(
        prog="aistack",
        description="With no command, serve your own Library to the coding agent that started "
                    "this over stdio. 'dashboard' opens it in the browser; 'setup' prints "
                    "setup steps for a coding agent, 'sync-skill' the skill they install, and "
                    "'check' whether this computer reaches its Library; 'github' signs in to "
                    "GitHub and finds or creates the private repository a Library lives in; "
                    "'export' writes every skill in the Library to a folder; 'status --hook' "
                    "reminds the agent to sync when there is something to; 'move github', "
                    "'move postgresql' or 'move here' moves it with its history; 'connect' "
                    "connects Claude Code or Codex to it; 'serve' runs the AIStack server, "
                    "'backup' and 'restore' copy its database, and 'admin' manages its "
                    "users, computers and teams; 'join <server> <code>' adds this computer "
                    "with a computer code, and 'sync' reconciles its skills.")
    parser.add_argument("command", nargs="?", choices=["serve", "dashboard", "setup",
                                                       "sync-skill", "check", "export",
                                                       "github", "move", "connect", "backup",
                                                       "restore", "admin", "status", "sync", "join"])
    parser.add_argument("folder", nargs="?",
                        help="Where 'export' writes the skills, ./aistack-library by default; "
                             "the skills folder 'sync-skill' writes its skill into, instead of "
                             "printing it; where 'move' takes the Library: github, postgresql "
                             f"(the address in {MOVE_TO_URL}) or here; the agent 'connect' "
                             "connects, claude-code or codex; the file 'backup' writes or "
                             "'restore' reads")
    parser.add_argument("repository", nargs="?",
                        help="For 'move github': the private repository, as owner/name. "
                             "Without it, your own aistack-library, made if needed")
    parser.add_argument("--agent", choices=agent_config.AGENTS,
                        help="For 'check' and 'export': use the Library this agent is "
                             "connected to, without showing its settings")
    parser.add_argument("--hook", action="store_true",
                        help="For 'connect': also remind the agent to sync at session start. "
                             "'status --hook' is that reminder: printed only when sync has "
                             "something to do")
    parser.add_argument("--allow-http", action="store_true", help="Allow public plain HTTP, which exposes this computer’s key")
    arguments = parser.parse_args()
    command = arguments.command
    folder = Path(arguments.folder).expanduser() if arguments.folder else None

    # Printed for an agent to follow or save: local mode has no server to fetch them from.
    if command == "setup":
        print(local_setup_instructions(), end="")
        return
    if command == "sync-skill":
        if folder is None:
            print(local_sync_skill_document(), end="")
        else:
            write_sync_skill(folder)
        return
    if command == "connect" and arguments.folder not in agent_config.AGENTS:
        parser.error("connect takes the agent to connect: claude-code or codex")

    if command == "sync":
        from aistack.bootstrap.sync_lock import locked
        from aistack.services import server_connection, server_sync

        try:
            connection = agent_config.remote_connection(arguments.agent)
            warning = server_connection.checked_server(connection.url, arguments.allow_http)
            # The person accepted plain HTTP at join; repeating it fills every new chat.
            if warning and not arguments.hook:
                print(warning)
            with locked(Path.home()):
                reports = asyncio.run(server_sync.sync_computer(connection, Path.home(), Path.cwd()))
            rendered = server_sync.output(reports, arguments.hook)
            if rendered:
                print(rendered)
            if any(report["failures"] for report in reports):
                sys.exit(1)
        except (agent_config.NotConnected, AIStackError, ToolError) as error:
            sys.exit(f"AIStack: {error}")
        except Exception:
            # Network/SDK exceptions can contain bearers and signed transfer URLs.
            sys.exit("AIStack sync could not finish. Check the server connection and try again; installed skills remain usable.")
        return

    if command == "status":
        if not arguments.hook:
            parser.error("status runs as the session-start hook: aistack status --hook")
        status_hook(arguments.agent)
        return
    if command == "github":
        sys.exit(github_setup.connect(LocalSettings().home))
    if command in ("backup", "restore") and arguments.folder is None:
        parser.error(f"{command} takes the backup file: aistack {command} <file>")

    try:
        if arguments.agent:
            use_agent_place(arguments.agent)
        if command == "serve":
            asyncio.run(main())
        elif command == "dashboard":
            asyncio.run(serve_dashboard())
        elif command == "check":
            check_local()
        elif command == "export":
            export_library(folder or Path("aistack-library"))
        elif command == "move":
            if arguments.folder not in MOVE_DESTINATIONS:
                parser.error("move takes where to: github, postgresql or here")
            try:
                move_library(arguments.folder, arguments.repository)
            except AIStackError as refusal:
                sys.exit(refusal.message)
        elif command == "connect":
            connect_agent(arguments.folder, arguments.hook)
        elif command == "backup":
            back_up_database(Path(arguments.folder).expanduser())
        elif command == "restore":
            restore_database(Path(arguments.folder).expanduser())
        else:
            serve_local()
    except ValueError as error:
        # Configuration is wrong, not the code. A traceback would bury the one line that says
        # which variable to set, so this exits loudly and readably instead. ValueError covers
        # both a field pydantic rejected and the invite-code check that deliberately is not one.
        logging.basicConfig(level="INFO", format=LOG_FORMAT, datefmt=LOG_DATE_FORMAT, force=True)
        logger.error(f"AIStack cannot start: its configuration is invalid.\n{error}")
        sys.exit(1)
    except (NewerSchema, ForeignDatabase) as error:
        logging.basicConfig(level="INFO", format=LOG_FORMAT, datefmt=LOG_DATE_FORMAT, force=True)
        logger.error(f"AIStack cannot start. {error}")
        sys.exit(1)
    except OperationalError as error:
        # The usual first-run mistake in local mode: an address that is wrong or a password
        # that changed. The driver's last line names which, and holds no password.
        logging.basicConfig(level="INFO", format=LOG_FORMAT, datefmt=LOG_DATE_FORMAT, force=True)
        reason = str(error.orig).strip().splitlines()[-1]
        database = "the server's database" if command == "serve" else "the Library's database"
        logger.error(f"AIStack cannot start: it could not reach {database}. {reason}")
        sys.exit(1)
    except AIStackError as error:
        # Local mode's start asks the database who this is, and the answer can be a refusal
        # that names what to change, such as a database that is a server's.
        logging.basicConfig(level="INFO", format=LOG_FORMAT, datefmt=LOG_DATE_FORMAT, force=True)
        logger.error(f"AIStack cannot start. {error}")
        sys.exit(1)
    except (agent_config.NotConnected, backup.BackupRefused) as refusal:
        sys.exit(str(refusal))
    except KeyboardInterrupt:
        logger.info("Received interrupt signal, shutting down...")
    finally:
        # A stopped server leaves its data in one file, not half of it in `-wal`.
        dispose_application_context()


if __name__ == "__main__":
    run()
