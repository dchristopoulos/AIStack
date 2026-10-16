"""The two routes a brand-new machine reads before it has any credential.

A user who has never heard of AIStack cannot call a tool on a server they are not connected
to, so the way in is plain HTTP: instructions their agent can follow, and the one skill that
has to exist on disk before the vault can be asked for anything.
"""

from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response

from aistack.bundled import SYNC_SKILL_NAME, setup_instructions, sync_skill_document
from aistack.mcp.mcp import mcp
from aistack.mcp.routes.route_error_handler import handle_route_errors
from aistack.mcp.server_url import mcp_endpoint_url, server_base_url

SETUP_PATH = "/setup"

_MARKDOWN = "text/markdown; charset=utf-8"
# Without AISTACK_PUBLIC_URL the addresses in the text come from the request's Host, so a
# shared cache that ignored it could hand one client's address to everyone (SEC-11).
_UNCACHED = {"Cache-Control": "no-store", "Vary": "Host"}


@mcp.custom_route(SETUP_PATH, methods=["GET"])
@handle_route_errors
async def setup(request: Request) -> Response:
    """Setup instructions for an agent, with this server's own address already filled in.

    Public on purpose, and it holds nothing worth protecting: no invite code, no token, only
    the URL the reader used to get here.
    """
    instructions = (setup_instructions()
                    .replace("{server_url}", server_base_url(request))
                    .replace("{mcp_url}", mcp_endpoint_url(request)))
    return PlainTextResponse(instructions, media_type=_MARKDOWN, headers=_UNCACHED)


@mcp.custom_route(f"{SETUP_PATH}/{SYNC_SKILL_NAME}/SKILL.md", methods=["GET"])
@handle_route_errors
async def sync_skill(request: Request) -> Response:
    return PlainTextResponse(sync_skill_document(), media_type=_MARKDOWN, headers=_UNCACHED)
