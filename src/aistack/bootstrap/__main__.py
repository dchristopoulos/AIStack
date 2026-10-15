import argparse
import asyncio
import logging
import os
import shutil
import socket
import sys
import webbrowser
from pathlib import Path

import uvicorn
from sqlalchemy.exc import OperationalError

from aistack.bootstrap import self_update
from aistack.bootstrap.configuration.settings.settings_config import LocalSettings, Settings
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
from aistack.db.schema import NewerSchema

logger = logging.getLogger(__name__)

LOG_FORMAT = "%(asctime)s %(levelname)-8s [%(name)s.%(funcName)s] %(message)s"

# Loggers that print raw protocol payloads at DEBUG. A tool result containing a machine token
# goes over the wire in plaintext by definition, so at DEBUG these write the token to the log
# file — the one place the secrets rule says it must never appear. They are floored at INFO
# regardless of AISTACK_LOG_LEVEL rather than trusted to the operator's choice of level.
WIRE_LOGGERS = ("mcp.client", "mcp.server.streamable_http", "sse_starlette", "httpcore", "httpx")


def configure_logging(log_level: str) -> None:
    logging.basicConfig(level=log_level, format=LOG_FORMAT, force=True)
    for wire_logger in WIRE_LOGGERS:
        logging.getLogger(wire_logger).setLevel(max(logging.INFO,
                                                    logging.getLevelName(log_level)))


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
    settings = LocalSettings()
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
    ticket = get_ticket_signer().sign_dashboard_link(get_local_principal().user_id)
    link = f"http://127.0.0.1:{port}{DASHBOARD_LOGIN_PATH}/{ticket}"

    # The link is a credential, so it goes to this terminal and the browser, never a log.
    print(f"AIStack dashboard: http://127.0.0.1:{port}/app (Ctrl-C stops it)\n"
          f"Sign-in link, good for five minutes: {link}", flush=True)
    webbrowser.open(link)
    await uvicorn.Server(dashboard_server_config(settings.log_level)).serve(sockets=[listener])


def check_local() -> None:
    """`aistack check`: set up this computer's side of the Library once, and say whether it
    works. Setup runs it before connecting an agent, which would hide a failure."""
    settings = LocalSettings()
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
    settings = LocalSettings()
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


def run() -> None:
    """The `aistack` command: `aistack` is local mode, `aistack serve` the server."""
    parser = argparse.ArgumentParser(
        prog="aistack",
        description="With no command, serve your own Library to the coding agent that started "
                    "this over stdio. 'dashboard' opens it in the browser; 'setup' prints "
                    "setup steps for a coding agent, 'sync-skill' the skill they install, and "
                    "'check' whether this computer reaches its Library; "
                    "'export' writes every skill in the Library to a folder; 'serve' runs the "
                    "AIStack server.")
    parser.add_argument("command", nargs="?", choices=["serve", "dashboard", "setup",
                                                       "sync-skill", "check", "export"])
    parser.add_argument("folder", nargs="?", type=Path,
                        help="Where 'export' writes the skills, ./aistack-library by default; "
                             "the skills folder 'sync-skill' writes its skill into, instead of "
                             "printing it")
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
            write_sync_skill(arguments.folder.expanduser())
        return

    try:
        if command == "serve":
            asyncio.run(main())
        elif command == "dashboard":
            asyncio.run(serve_dashboard())
        elif command == "check":
            check_local()
        elif command == "export":
            export_library((arguments.folder or Path("aistack-library")).expanduser())
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
