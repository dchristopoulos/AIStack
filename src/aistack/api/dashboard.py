"""The dashboard: one page and the JSON routes behind it (ADR-0017).

Every route here is thin in the same way a tool is: it establishes who is asking, runs one
service call in one transaction off the event loop, and returns what that call returned.
Nothing is decided here about who may see or change what; the services decide.
"""

import asyncio
import json
import logging
import uuid
from collections.abc import Callable
from functools import wraps
from typing import Any

from sqlalchemy.orm import Session
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from aistack.bootstrap.context.application_context import (
    get_session_factory,
    get_settings,
    get_ticket_signer,
)
from aistack.bundled import dashboard_page
from aistack.commons.exceptions import InvalidTicket, SignedOut, ValidationError
from aistack.mcp.mcp import mcp
from aistack.mcp.routes.route_error_handler import handle_route_errors
from aistack.mcp.server_url import DASHBOARD_LOGIN_PATH
from aistack.services import dashboard_service, skill_service, team_service
from aistack.services.transfer_ticket import DASHBOARD_SESSION_LIFETIME_SECONDS

logger = logging.getLogger(__name__)

APP_PATH = "/app"
API_PATH = "/api"

SESSION_COOKIE = "aistack_session"
# A header a cross-site form cannot set, required on every request that changes something.
REQUEST_HEADER = "x-aistack-request"

_MAX_BODY_BYTES = 16 * 1024

_SIGNED_OUT = ("You are not signed in to this dashboard. Ask your coding agent to \"open my "
               "aistack dashboard\" for a new link.")

# The page loads nothing from anywhere else and may only talk to this server. Its styles and
# script are inline because it is one file.
_PAGE_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
        "connect-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'none'; "
        "frame-ancestors 'none'"),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}
_API_HEADERS = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}


@mcp.custom_route(DASHBOARD_LOGIN_PATH + "/{ticket}", methods=["GET"])
async def sign_in(request: Request) -> Response:
    """Turn a link from `open_dashboard` into a session, then leave the link behind.

    The redirect takes the ticket out of the address bar. A link that is wrong or has expired
    gets the same page as no session at all.
    """
    try:
        user_id = get_ticket_signer().verified_dashboard_link(request.path_params["ticket"])
    except InvalidTicket:
        logger.info("Dashboard sign-in refused: the link was not valid or had expired.")
        return _signed_out_page()

    response = RedirectResponse(APP_PATH, status_code=303, headers=_PAGE_HEADERS)
    response.set_cookie(
        SESSION_COOKIE,
        get_ticket_signer().sign_dashboard_session(user_id),
        max_age=DASHBOARD_SESSION_LIFETIME_SECONDS,
        httponly=True,
        # Lax, not Strict: the link is usually opened from a chat window on another site, and
        # Strict would withhold the cookie on the redirect that follows. Requests that change
        # anything are protected by the header a cross-site page cannot send.
        samesite="lax",
        secure=_served_over_https(request),
        path="/",
    )
    logger.info(f"Dashboard session started. User: '{user_id}'.")
    return response


@mcp.custom_route(APP_PATH, methods=["GET"])
async def app(request: Request) -> Response:
    """The page itself. It holds no data: everything it shows comes from `/api/state`."""
    try:
        _signed_in(request)
    except SignedOut:
        return _signed_out_page()
    return HTMLResponse(dashboard_page(), headers=_PAGE_HEADERS)


@mcp.custom_route(API_PATH + "/state", methods=["GET"])
@handle_route_errors
async def state(request: Request) -> Response:
    user_id = _signed_in(request)
    return _json(await asyncio.to_thread(_in_transaction, dashboard_service.state, user_id))


@mcp.custom_route(API_PATH + "/logout", methods=["POST"])
@handle_route_errors
async def sign_out(request: Request) -> Response:
    _require_request_header(request)
    response = _json({"ok": True})
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


Action = Callable[[Session, uuid.UUID, dict[str, str], dict[str, Any]], dict[str, Any] | None]


def _action(path: str) -> Callable[[Action], Action]:
    """Register a POST route that runs `function` for the signed-in user in one transaction.

    The function takes the session, the caller's user id, the path parameters, and the JSON
    body. The user id comes from the session cookie and from nowhere else.
    """
    def register(function: Action) -> Action:
        @wraps(function)
        async def route(request: Request) -> Response:
            user_id = _signed_in(request)
            _require_request_header(request)
            body = await _json_body(request)
            result = await asyncio.to_thread(_in_transaction, function, user_id,
                                             dict(request.path_params), body)
            return _json(result or {"ok": True})

        mcp.custom_route(API_PATH + path, methods=["POST"])(handle_route_errors(route))
        return function
    return register


@_action("/skills/{name}/machines/{machine_id}")
def set_skill_on_machine(session, user_id, path, body):
    dashboard_service.set_on_machine(session, user_id, path["name"], path["machine_id"],
                                     _flag(body, "enabled"))


@_action("/skills/{name}/share")
def share_skill(session, user_id, path, body):
    shared = skill_service.share(session, user_id, path["name"], _text(body, "team"),
                                 _text(body, "group", required=False))
    return {
        "team": shared.team, "group": shared.group, "revision": shared.revision,
        "created": shared.created, "unchanged": shared.unchanged,
        "previous_pushed_by": shared.previous_pushed_by,
        "possibly_unrelated": shared.possibly_unrelated,
    }


@_action("/skills/{name}/remove")
def remove_my_skill(session, user_id, path, body):
    skill_service.remove_from_my_skills(session, user_id, path["name"])


@_action("/teams")
def create_team(session, user_id, path, body):
    return {"name": team_service.create_team(session, user_id, _text(body, "name"))}


@_action("/teams/join")
def join_team(session, user_id, path, body):
    return {"team": team_service.join_team(session, user_id, _text(body, "code"))}


@_action("/teams/{team}/leave")
def leave_team(session, user_id, path, body):
    team_service.leave_team(session, user_id, path["team"])


@_action("/teams/{team}/invite")
def new_invite_code(session, user_id, path, body):
    # Returned to the admin who asked, once, and never logged.
    return {"code": team_service.new_invite_code(session, user_id, path["team"])}


@_action("/teams/{team}/take")
def take_from_team(session, user_id, path, body):
    skill_service.take_from_team(session, user_id, _text(body, "name"), path["team"])


@_action("/teams/{team}/members/{username}")
def change_member(session, user_id, path, body):
    team_service.set_member(
        session, user_id, path["team"], path["username"],
        role=_text(body, "role", required=False),
        sees_all_groups=_flag(body, "sees_all_groups", required=False),
    )


@_action("/teams/{team}/members/{username}/remove")
def remove_member(session, user_id, path, body):
    team_service.remove_member(session, user_id, path["team"], path["username"])


@_action("/teams/{team}/groups")
def create_group(session, user_id, path, body):
    return {"path": team_service.create_group(
        session, user_id, path["team"], _text(body, "name"),
        parent=_text(body, "parent", required=False),
        private=bool(_flag(body, "private", required=False)),
    )}


# A group's path has slashes in it, so it travels in the body and not in the URL.
@_action("/teams/{team}/group")
def change_group(session, user_id, path, body):
    group = _text(body, "path")
    private = _flag(body, "private", required=False)
    subscribed = _flag(body, "subscribed", required=False)
    if private is not None:
        team_service.set_group(session, user_id, path["team"], group, private)
    if subscribed is not None:
        team_service.set_subscribed(session, user_id, path["team"], group, subscribed)


@_action("/teams/{team}/group/members")
def change_group_member(session, user_id, path, body):
    team_service.set_group_member(session, user_id, path["team"], _text(body, "path"),
                                  _text(body, "username"), _flag(body, "member"))


@_action("/teams/{team}/skills/{name}/move")
def move_team_skill(session, user_id, path, body):
    team_service.move_skill(session, user_id, path["team"], path["name"],
                            _text(body, "group", required=False))


@_action("/teams/{team}/skills/{name}/remove")
def remove_team_skill(session, user_id, path, body):
    team_service.remove_skill(session, user_id, path["team"], path["name"])


def _signed_in(request: Request) -> uuid.UUID:
    """The user this browser is signed in as, from the session cookie and nothing else."""
    cookie = request.cookies.get(SESSION_COOKIE)
    if cookie is None:
        raise SignedOut(_SIGNED_OUT)
    try:
        return get_ticket_signer().verified_dashboard_session(cookie)
    except InvalidTicket as error:
        raise SignedOut(_SIGNED_OUT) from error


def _require_request_header(request: Request) -> None:
    if REQUEST_HEADER not in request.headers:
        raise ValidationError(
            "This request did not come from the dashboard page, so it was not carried out.")


async def _json_body(request: Request) -> dict[str, Any]:
    raw = await request.body()
    if len(raw) > _MAX_BODY_BYTES:
        raise ValidationError(f"The request is larger than {_MAX_BODY_BYTES} bytes.")
    try:
        body = json.loads(raw or b"{}")
    except (ValueError, UnicodeDecodeError) as error:
        raise ValidationError("The request body is not JSON.") from error
    if not isinstance(body, dict):
        raise ValidationError("The request body must be a JSON object.")
    return body


def _text(body: dict[str, Any], key: str, required: bool = True) -> str | None:
    value = body.get(key)
    if value is None and not required:
        return None
    if not isinstance(value, str):
        raise ValidationError(f"'{key}' must be text.")
    return value


def _flag(body: dict[str, Any], key: str, required: bool = True) -> bool | None:
    value = body.get(key)
    if value is None and not required:
        return None
    if not isinstance(value, bool):
        raise ValidationError(f"'{key}' must be true or false.")
    return value


def _in_transaction(function: Callable[..., Any], user_id: uuid.UUID, *arguments: Any) -> Any:
    """One request, one transaction, exactly as a tool call."""
    with get_session_factory().begin() as session:
        dashboard_service.require_a_machine(session, user_id)
        return function(session, user_id, *arguments)


def _json(payload: dict[str, Any]) -> JSONResponse:
    return JSONResponse(payload, headers=_API_HEADERS)


def _signed_out_page() -> Response:
    return HTMLResponse(
        "<!doctype html><meta charset=utf-8><title>AIStack</title>"
        "<body style=\"font:16px system-ui;margin:15vh auto;max-width:32rem;padding:0 1rem\">"
        "<h1 style=\"font-size:1.25rem\">You are not signed in</h1>"
        "<p>Ask your coding agent to <strong>open my aistack dashboard</strong>. It will give "
        "you a link that signs you in.</p>",
        status_code=401,
        headers=_PAGE_HEADERS,
    )


def _served_over_https(request: Request) -> bool:
    public_url = get_settings().public_url
    if public_url is not None:
        return public_url.startswith("https://")
    return request.url.scheme == "https"
