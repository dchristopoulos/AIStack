"""The invite link (ADR-0019): which team it is for, and the one sentence to paste.

Like a transfer route, the credential is in the URL: the team's invite code. The page shows
the team's name to whoever holds the link, which is the point of the link and nothing more.
A wrong or replaced code gets the same page as any other wrong one.
"""

import asyncio
import logging
from html import escape
from urllib.parse import quote

from starlette.requests import Request
from starlette.responses import HTMLResponse, Response

from aistack.bootstrap.context.application_context import (
    get_failure_limiter,
    get_read_session_factory,
)
from aistack.bundled import plain_page
from aistack.commons.exceptions import NotFound
from aistack.mcp.auth.failure_limiter import client_address, note_failure
from aistack.mcp.mcp import mcp
from aistack.mcp.routes.route_error_handler import handle_route_errors
from aistack.mcp.server_url import APP_PATH, INVITE_PATH, server_base_url
from aistack.services import team_service

logger = logging.getLogger(__name__)

# The code is in the address bar: nothing on the page may load from elsewhere or send it on.
# The one image is the inline icon.
_HEADERS = {
    "Content-Security-Policy": ("default-src 'none'; style-src 'unsafe-inline'; img-src data:; "
                                "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}

@mcp.custom_route(INVITE_PATH + "/{code}", methods=["GET"])
@handle_route_errors
async def invite(request: Request) -> Response:
    code = request.path_params["code"]
    try:
        team = await asyncio.to_thread(_team_name, code)
    except NotFound:
        # Never logs or echoes the code: a near-miss of a real one is still a secret.
        address = client_address(request)
        logger.info(f"Invite page refused: not an invite code that works. Client: '{address}'.")
        note_failure(get_failure_limiter(), address, "invite link")
        return _page("Invite not found", 404,
                     "<h1>This invite link does not work</h1>"
                     "<p>An invite link lets one person in and lasts seven days. This one has "
                     "been used, cancelled, or has run out.</p>"
                     "<p>If you used it yourself, you are already in the team: ask your coding "
                     "agent to <strong>open my aistack dashboard</strong>. Otherwise ask "
                     "whoever sent it for a new link.</p>")

    server = server_base_url(request)
    sentence = (f"Set up AIStack: fetch {server}/setup and follow it.\n"
                f"Invite code: {code}. My username is <a short handle like maria>, and my "
                "name is <your name>.")
    join = f"Join the AIStack team {team} with invite code {code}."
    # In the fragment, which the browser never sends: the dashboard reads it and drops it.
    dashboard = f"{server}{APP_PATH}#/join/{quote(code, safe='')}"
    return _page(
        f"Join {team}", 200,
        f"<h1>You are invited to <code>{escape(team)}</code></h1>"
        "<p>Paste this into Claude Code or Codex, with a short username and your name filled "
        "in. It creates your account, connects this computer, and puts you in the team.</p>"
        f"<pre>{escape(sentence)}</pre>"
        "<p>Already have an account? Say this to your coding agent instead:</p>"
        f"<pre>{escape(join)}</pre>"
        f"<p>Or <a href=\"{escape(dashboard)}\">join in your dashboard</a>, if this browser "
        "is signed in to it.</p>")


def _team_name(code: str) -> str:
    with get_read_session_factory().begin() as session:
        return team_service.invited_team(session, code)


def _page(title: str, status: int, body: str) -> Response:
    return HTMLResponse(plain_page(f"{escape(title)}, AIStack", body), status_code=status,
                        headers=_HEADERS)
