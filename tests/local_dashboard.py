"""`aistack dashboard` served in-process, for the HTTP and browser tests of local mode."""

import asyncio
import contextlib
import socket
from pathlib import Path

import uvicorn

from aistack.bootstrap.configuration.settings.settings_config import LocalSettings
from aistack.bootstrap.context import application_context
from aistack.mcp.mcp import dashboard_server_config
from aistack.mcp.server_url import DASHBOARD_LOGIN_PATH
from aistack.services import skill_service
from tests.archives import skill_archive


@contextlib.asynccontextmanager
async def local_dashboard(home: Path, library_url: str):
    """A local Library holding one skill, its dashboard, and a sign-in link: (base, link)."""
    application_context.build_local_context(LocalSettings(
        aistack_home=home / ".aistack",
        aistack_database_url=library_url,
        aistack_username="maria",
    ))
    try:
        caller = application_context.get_local_principal()
        with application_context.get_session_factory().begin() as session:
            skill_service.push(session, caller.machine_id, caller.user_id, "wizard", None,
                               skill_archive("wizard"))

        with socket.create_server(("127.0.0.1", 0)) as listener:
            base = f"http://127.0.0.1:{listener.getsockname()[1]}"
            server = uvicorn.Server(dashboard_server_config(log_level="INFO"))
            serving = asyncio.create_task(server.serve(sockets=[listener]))
            try:
                async with asyncio.timeout(5):
                    while not server.started:
                        if serving.done():
                            await serving
                            raise RuntimeError("The dashboard stopped before startup.")
                        await asyncio.sleep(0.01)
                ticket = application_context.get_ticket_signer().sign_dashboard_link(
                    caller.user_id)
                yield base, f"{base}{DASHBOARD_LOGIN_PATH}/{ticket}"
            finally:
                server.should_exit = True
                with contextlib.suppress(asyncio.CancelledError):
                    await serving
    finally:
        application_context.dispose_application_context()
