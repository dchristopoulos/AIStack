"""The HTTP routes that carry skill archives and rule text (ADR-0010, ADR-0036).

They sit outside FastMCP's bearer check on purpose: the ticket in the URL is the credential,
minted by an authorized tool call and good for one skill or rule, one direction, and five
minutes.
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
from aistack.commons.exceptions import ValidationError
from aistack.db.models.rule import RULE_TEXT_MAX_BYTES
from aistack.services import project_service, rule_sync, skill_service
from aistack.services.skill_archive import MAX_ARCHIVE_BYTES, read_archive
from aistack.services.skill_validation import validated_skill
from aistack.services.rule_validation import validated_rule_text
from aistack.services.transfer_ticket import (
    DownloadTicket,
    RuleDownloadTicket,
    RuleUploadTicket,
    UploadTicket,
)

logger = logging.getLogger(__name__)

UPLOAD_PATH = "/transfer/upload"
DOWNLOAD_PATH = "/transfer/download"
RULE_UPLOAD_PATH = "/transfer/rule-upload"
RULE_DOWNLOAD_PATH = "/transfer/rule-download"

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
    # Validated before the transaction: parsing is slow, and SQLite's write lock is held from
    # the first statement.
    uploaded = validated_skill(ticket.skill_name, read_archive(archive))
    with get_session_factory().begin() as session:
        # Checked again here: the folder may have stopped being managed since the URL.
        folder = None if ticket.project_id is None else project_service.folder_by_id(
            session, ticket.machine_id, ticket.project_id, ticket.harness)
        return skill_service.store(
            session,
            machine_id=ticket.machine_id,
            user_id=ticket.user_id,
            uploaded=uploaded,
            origin=ticket.origin,
            harness=ticket.harness,
            token_prefix=ticket.token_prefix,
            project_folder=folder,
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


@mcp.custom_route(RULE_UPLOAD_PATH + "/{ticket}", methods=["PUT"])
@handle_route_errors
async def upload_rule(request: Request) -> Response:
    """A file's text from a computer, as the rule the ticket names. The text is never
    logged."""
    ticket = get_ticket_signer().verified_rule_upload(request.path_params["ticket"])
    body = await bounded_body(
        request, RULE_TEXT_MAX_BYTES,
        f"The file is larger than the {RULE_TEXT_MAX_BYTES} byte limit for one rule (64 KiB). "
        "Shorten it, or split it into two rules.", UPLOAD_READ_TIMEOUT_SECONDS)
    try:
        text = validated_rule_text(body.decode("utf-8"))
    except UnicodeDecodeError:
        raise ValidationError("The file is not UTF-8 text, so it was not stored. Save it as "
                              "UTF-8 and sync again.") from None
    saved = await asyncio.to_thread(_store_rule, ticket, text)
    logger.info(f"Rule uploaded. Rule: '{saved.name}'. Saved: '{saved.saved}'. "
                f"Revision: '{saved.revision}'. Agent: '{ticket.agent.value}'. "
                f"Machine: '{ticket.machine_id}'.")
    return JSONResponse(asdict(saved))


def _store_rule(ticket: RuleUploadTicket, text: str):
    with get_session_factory().begin() as session:
        return rule_sync.store(session, ticket, text)


@mcp.custom_route(RULE_DOWNLOAD_PATH + "/{ticket}", methods=["GET"])
@handle_route_errors
async def download_rule(request: Request) -> Response:
    ticket = get_ticket_signer().verified_rule_download(request.path_params["ticket"])
    name, text = await asyncio.to_thread(_load_rule, ticket)
    logger.info(f"Rule downloaded. Rule: '{name}'. Agent: '{ticket.agent.value}'. "
                f"Machine: '{ticket.machine_id}'.")
    return Response(text.encode("utf-8"), media_type="text/markdown; charset=utf-8")


def _load_rule(ticket: RuleDownloadTicket) -> tuple[str, str]:
    with get_session_factory().begin() as session:
        return rule_sync.text_of(session, ticket)
