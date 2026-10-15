import argparse
import asyncio
import logging
import os
import shutil
import socket
import sys
import time
import webbrowser
from pathlib import Path

import fastmcp
import uvicorn
from sqlalchemy.exc import OperationalError

from aistack.bootstrap import github_setup, self_update
from aistack.bootstrap.configuration.settings.settings_config import (
    LocalSettings,
    Settings,
    described,
    record_place,
)
from aistack.bootstrap.context.application_context import (
    build_application_context,
    build_local_context,
)
from aistack.bundled import (
    SYNC_SKILL_NAME,
    local_setup_instructions,
    local_sync_skill_document,
)
from aistack.commons.exceptions import AIStackError
from aistack.commons.text import loggable
from aistack.db.engine import build_engine
from aistack.mcp.argument_errors import argument_problems
from aistack.db.schema import NewerSchema

logger = logging.getLogger(__name__)

LOG_FORMAT = "%(asctime)s %(levelname)-8s [%(name)s.%(funcName)s] %(message)s"

# Loggers that print raw protocol payloads at DEBUG. A tool result containing a machine token
# goes over the wire in plaintext by definition, so at DEBUG these write the token to the log
# file: the one place the secrets rule says it must never appear. They are floored at INFO
# regardless of AISTACK_LOG_LEVEL rather than trusted to the operator's choice of level.
# FastMCP joins them once its records reach the root logger: at DEBUG it writes every tool
# call's arguments, a team's invite code among them.
WIRE_LOGGERS = ("mcp.client", "mcp.server.streamable_http", "sse_starlette", "httpcore", "httpx",
                "fastmcp")

# FastMCP's own line for a rejected bearer. AIStack logs the rejection, with the address, so
# at INFO this second line would only double what a flood costs the log.
QUIET_LOGGERS = ("fastmcp.server.auth.middleware",)

# Where FastMCP 3.4.7 logs a call's arguments when they fail validation.
ARGUMENT_ECHO_LOGGER = "fastmcp.server.server"


def configure_logging(log_level: str) -> None:
    logging.basicConfig(level=log_level, format=LOG_FORMAT, force=True)
    _route_fastmcp_through_root()
    for wire_logger in WIRE_LOGGERS:
        logging.getLogger(wire_logger).setLevel(max(logging.INFO,
                                                    logging.getLevelName(log_level)))
    for quiet_logger in QUIET_LOGGERS:
        logging.getLogger(quiet_logger).setLevel(logging.WARNING)


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
    self_update.start_in_background(settings.home)

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
    from aistack.mcp.mcp import dashboard_server_config
    from aistack.mcp.server_url import DASHBOARD_LOGIN_PATH

    # Port 0: the system picks a free one, so a second dashboard or another program on a
    # fixed port never stops this one starting. The link names whichever it picked.
    listener = socket.create_server(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    ticket = get_ticket_signer().sign_dashboard_link(get_local_principal().dashboard_holder())
    link = f"http://127.0.0.1:{port}{DASHBOARD_LOGIN_PATH}/{ticket}"

    # The link is a credential, so it goes to this terminal and the browser, never a log.
    print(f"AIStack dashboard: http://127.0.0.1:{port}/app (Ctrl-C stops it)\n"
          f"Sign-in link, good for five minutes: {link}", flush=True)
    webbrowser.open(link)
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
    target = skills_folder / SYNC_SKILL_NAME / "SKILL.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(local_sync_skill_document(), encoding="utf-8", newline="\n")
    print(f"Wrote {target}.")


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
        skills = skill_service.export_library(session, caller.machine_id, caller.user_id)
    # Written after the transaction, through the same checks an install makes.
    for skill in skills:
        local_skills.install(destination, skill.name, skill.archive, skill.content_hash)
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
    except AIStackError as refusal:
        sys.exit(f"The Library cannot be read, so nothing was moved. {refusal}")
    # A GitHub Library is moved as the repository has it, not as this copy last saw it.
    application_context.library_before_read(force=True)
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


def run() -> None:
    """The `aistack` command: `aistack` is local mode, `aistack serve` the server."""
    parser = argparse.ArgumentParser(
        prog="aistack",
        description="With no command, serve your own Library to the coding agent that started "
                    "this over stdio. 'dashboard' opens it in the browser; 'setup' prints "
                    "setup steps for a coding agent, 'sync-skill' the skill they install, and "
                    "'check' whether this computer reaches its Library; 'github' signs in to "
                    "GitHub and finds or creates the private repository a Library lives in; "
                    "'export' writes every skill in the Library to a folder; 'move github', "
                    "'move postgresql' or 'move here' moves it with its history; 'serve' "
                    "runs the AIStack server.")
    parser.add_argument("command", nargs="?", choices=["serve", "dashboard", "setup",
                                                       "sync-skill", "check", "export",
                                                       "github", "move"])
    parser.add_argument("folder", nargs="?",
                        help="Where 'export' writes the skills, ./aistack-library by default; "
                             "the skills folder 'sync-skill' writes its skill into, instead of "
                             "printing it; where 'move' takes the Library: github, postgresql "
                             f"(the address in {MOVE_TO_URL}) or here")
    parser.add_argument("repository", nargs="?",
                        help="For 'move github': the private repository, as owner/name. "
                             "Without it, your own aistack-library, made if needed")
    arguments = parser.parse_args()
    command = arguments.command

    # Printed for an agent to follow or save: local mode has no server to fetch them from.
    if command == "setup":
        print(local_setup_instructions(), end="")
        return
    if command == "sync-skill":
        if arguments.folder is None:
            print(local_sync_skill_document(), end="")
        else:
            write_sync_skill(Path(arguments.folder).expanduser())
        return

    if command == "github":
        sys.exit(github_setup.connect(LocalSettings().home))

    try:
        if command == "serve":
            asyncio.run(main())
        elif command == "dashboard":
            asyncio.run(serve_dashboard())
        elif command == "check":
            check_local()
        elif command == "export":
            export_library(Path(arguments.folder or "aistack-library").expanduser())
        elif command == "move":
            if arguments.folder not in MOVE_DESTINATIONS:
                parser.error("move takes where to: github, postgresql or here")
            try:
                move_library(arguments.folder, arguments.repository)
            except AIStackError as refusal:
                sys.exit(refusal.message)
        else:
            serve_local()
    except ValueError as error:
        # Configuration is wrong, not the code. A traceback would bury the one line that says
        # which variable to set, so this exits loudly and readably instead. ValueError covers
        # both a field pydantic rejected and the invite-code check that deliberately is not one.
        logging.basicConfig(level="INFO", format=LOG_FORMAT, force=True)
        logger.error(f"AIStack cannot start: its configuration is invalid.\n{error}")
        sys.exit(1)
    except NewerSchema as error:
        logging.basicConfig(level="INFO", format=LOG_FORMAT, force=True)
        logger.error(f"AIStack cannot start. {error}")
        sys.exit(1)
    except OperationalError as error:
        # The usual first-run mistake in local mode: an address that is wrong or a password
        # that changed. The driver's last line names which, and holds no password.
        logging.basicConfig(level="INFO", format=LOG_FORMAT, force=True)
        reason = str(error.orig).strip().splitlines()[-1]
        logger.error(f"AIStack cannot start: it could not reach the Library's database. {reason}")
        sys.exit(1)
    except AIStackError as error:
        # Local mode's start asks the database who this is, and the answer can be a refusal
        # that names what to change, such as a database that is a server's.
        logging.basicConfig(level="INFO", format=LOG_FORMAT, force=True)
        logger.error(f"AIStack cannot start. {error}")
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("Received interrupt signal, shutting down...")


if __name__ == "__main__":
    run()
