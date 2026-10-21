"""`aistack project add <folder>`: start managing a project on this computer, and send the
list of its Markdown files to the page (ADR-0026, ADR-0036, ADR-0038).

It says what it will send, by path and size, and waits for Enter: the dashboard's link runs
this command, and a link must never act on its own. No file's text is sent here; each sync
uploads the text of the files ticked on the page.
"""

import argparse
import asyncio
import sys
from pathlib import Path

from fastmcp.exceptions import ToolError

from aistack.bootstrap import agent_config
from aistack.commons.exceptions import AIStackError


def run(argv: list[str], home: Path | None = None, confirm=input) -> None:
    from aistack.bootstrap.sync_lock import locked
    from aistack.services import agent_files, repository_work, server_connection, server_sync

    parser = argparse.ArgumentParser(
        prog="aistack project",
        description="'add <folder>' manages the git repository that folder is in on this "
                    "computer, and lists its agent files and other Markdown files on the "
                    "dashboard, where you tick which ones it shows.")
    parser.add_argument("action", choices=["add"])
    parser.add_argument("folder")
    arguments = parser.parse_args(argv)
    home = home or Path.home()
    folder = Path(arguments.folder).expanduser()
    found = server_sync.current_project(folder, home) if folder.is_dir() else None
    if found is None:
        sys.exit(f"AIStack: {folder} is not inside a git repository, or is your home folder, so "
                 "it is not a project.")
    top = found[0]
    try:
        listed = repository_work.markdown_files(top)
    except (OSError, AIStackError):
        sys.exit(f"AIStack could not list the files git tracks in {top}.")
    agents = agent_files.all_readers([file["path"] for file in listed])
    print(f"AIStack will manage {top} on this computer and send the dashboard this list of its "
          "files, by path and size. No file's text is sent now.")
    for file in listed:
        readers = ", ".join(agent_files.AGENT_FILES[agent].display_name
                            for agent in agents.get(file["path"], ()))
        print(f"  {file['path']}  ({file['size']} bytes)" + (f"  read by {readers}" if readers
                                                            else ""))
    if not listed:
        print("  (no Markdown files)")
    try:
        confirm("Press Enter to send it, or Ctrl-C to stop. ")
    except (EOFError, KeyboardInterrupt):
        sys.exit("Nothing was sent.")
    try:
        connection = agent_config.remote_connection()
        warning = server_connection.checked_server(connection.url, False)
        if warning:
            print(warning)
        with locked(home):
            reports = asyncio.run(server_sync.sync_computer(connection, home, top,
                                                            add_files=listed))
    except (agent_config.NotConnected, AIStackError, ToolError) as error:
        sys.exit(f"AIStack: {error}")
    except Exception:
        # Network and SDK exceptions can carry bearers and signed transfer URLs.
        sys.exit("AIStack could not reach your server. Check the connection and try again.")
    print(f"Added {top}. Tick the files the dashboard shows on the project's page.")
    rendered = server_sync.output(reports)
    if rendered:
        print(rendered)
    if any(report["failures"] for report in reports):
        sys.exit(1)
