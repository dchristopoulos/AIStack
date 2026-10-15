"""The two HTTP routes that carry skill archives (ADR-0010).

They sit outside FastMCP's bearer check on purpose: the ticket in the URL is the credential,
minted by an authorized tool call and good for one skill, one direction, and five minutes.
"""

import asyncio
import logging
from dataclasses import asdict
from time import perf_counter

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from aistack.bootstrap.context.application_context import get_session_factory, get_ticket_signer
from aistack.mcp.mcp import mcp
from aistack.mcp.routes.request_body import bounded_body
from aistack.mcp.routes.route_error_handler import handle_route_errors
from aistack.services import skill_service
from aistack.services.skill_archive import MAX_ARCHIVE_BYTES
from aistack.services.transfer_ticket import DownloadTicket, UploadTicket

logger = logging.getLogger(__name__)

UPLOAD_PATH = "/transfer/upload"
DOWNLOAD_PATH = "/transfer/download"

UPLOAD_READ_TIMEOUT_SECONDS = 30


@mcp.custom_route(UPLOAD_PATH + "/{ticket}", methods=["PUT"])
@handle_route_errors
async def upload_skill(request: Request) -> Response:
    started_at = perf_counter()
    # Verified before a byte of the body is read: an unauthorized caller costs one HMAC.
    ticket = get_ticket_signer().verified_upload(request.path_params["ticket"])
    archive = await _bounded_body(request)

    # FastMCP requires async here; keep the parse and the blocking driver off the event loop.
    pushed = await asyncio.to_thread(_store_upload, ticket, archive)

    logger.info(
        f"Skill pushed. Skill: '{pushed.name}'. Revision: '{pushed.revision}'. "
        f"Created: '{pushed.created}'. Unchanged: '{pushed.unchanged}'. "
        f"Files: '{pushed.file_count}'. Bytes: '{len(archive)}'. User: '{ticket.user_id}'. "
        f"Elapsed: '{(perf_counter() - started_at) * 1000:.0f}ms'."
    )
    # What the push did, as the agent reads it; placement_changed is for local mode's log.
    result = asdict(pushed)
    del result["placement_changed"]
    return JSONResponse(result)


def _store_upload(ticket: UploadTicket, archive: bytes) -> skill_service.PushedSkill:
    """One upload, one transaction: the revision lands whole or not at all."""
    with get_session_factory().begin() as session:
        return skill_service.push(
            session,
            machine_id=ticket.machine_id,
            user_id=ticket.user_id,
            name=ticket.skill_name,
            origin=ticket.origin,
            archive=archive,
            harness=ticket.harness,
            token_prefix=ticket.token_prefix,
        )


@mcp.custom_route(DOWNLOAD_PATH + "/{ticket}", methods=["GET"])
@handle_route_errors
async def download_skill(request: Request) -> Response:
    started_at = perf_counter()
    ticket = get_ticket_signer().verified_download(request.path_params["ticket"])

    name, archive = await asyncio.to_thread(_load_download, ticket)

    logger.info(
        f"Skill downloaded. Skill: '{name}'. Bytes: '{len(archive)}'. "
        f"Machine: '{ticket.machine_id}'. "
        f"Elapsed: '{(perf_counter() - started_at) * 1000:.0f}ms'."
    )
    return Response(
        archive,
        media_type="application/gzip",
        headers={"Content-Disposition": f'attachment; filename="{name}.tgz"'},
    )


def _load_download(ticket: DownloadTicket) -> tuple[str, bytes]:
    with get_session_factory().begin() as session:
        return skill_service.archive_of(session, ticket.machine_id, ticket.skill_version_id,
                                        token_prefix=ticket.token_prefix)


async def _bounded_body(request: Request) -> bytes:
    """An upload, refused after one megabyte however much the client meant to send. One
    megabyte takes well under a second on any link worth pushing over."""
    return await bounded_body(
        request, MAX_ARCHIVE_BYTES,
        f"The upload is larger than the {MAX_ARCHIVE_BYTES} byte limit for one skill. If a "
        ".git or node_modules folder is inside the skill, leave it out.",
        UPLOAD_READ_TIMEOUT_SECONDS)
