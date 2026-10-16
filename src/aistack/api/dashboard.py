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
from html import escape
from typing import Any

from sqlalchemy.orm import Session
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Route

from aistack.bootstrap.context.application_context import (
    get_failure_limiter,
    get_local_principal,
    get_public_url,
    get_read_session_factory,
    get_session_factory,
    get_ticket_signer,
    is_local_mode,
    library_after_write,
    library_before_read,
    library_description,
)
from aistack.bundled import ICON_LINK, dashboard_page
from aistack.commons.exceptions import InvalidTicket, NotFound, SignedOut, ValidationError
from aistack.mcp.auth.failure_limiter import client_address, note_failure
from aistack.mcp.mcp import mcp
from aistack.mcp.routes.request_body import bounded_body
from aistack.mcp.routes.route_error_handler import handle_route_errors
from aistack.mcp.server_url import APP_PATH, DASHBOARD_LOGIN_PATH, server_base_url
from aistack.services import (
    dashboard_service,
    library_log,
    onboarding_service,
    skill_service,
    team_service,
)
from aistack.services.transfer_ticket import DASHBOARD_SESSION_LIFETIME_SECONDS, DashboardHolder

logger = logging.getLogger(__name__)

API_PATH = "/api"

SESSION_COOKIE = "aistack_session"
# A header a cross-site form cannot set, required on every request that changes something.
REQUEST_HEADER = "x-aistack-request"

_MAX_BODY_BYTES = 16 * 1024
_BODY_READ_TIMEOUT_SECONDS = 10

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

# The routes `aistack dashboard` serves on 127.0.0.1 (ADR-0020): the person's own Library and
# computers. A team needs a server everyone reaches, so its routes are left out, not refused.
LOCAL_ROUTES: list[Route] = []


def _route(path: str, methods: list[str], local: bool = True):
    """Register a route on the server, and with `local`, on the localhost dashboard too."""
    def register(endpoint):
        mcp.custom_route(path, methods=methods)(endpoint)
        if local:
            LOCAL_ROUTES.append(Route(path, endpoint, methods=methods))
        return endpoint
    return register


@_route(DASHBOARD_LOGIN_PATH + "/{ticket}", methods=["GET"])
async def sign_in(request: Request) -> Response:
    """Turn a link from `open_dashboard` into a session, then leave the link behind.

    The redirect takes the ticket out of the address bar. A link that is wrong, has expired,
    or comes from a computer no longer connected gets the same page as no session at all. A
    browser already signed in as someone else is asked first: a link anyone sends could
    otherwise sign it in to their account (ADR-0027).
    """
    try:
        holder = get_ticket_signer().verified_dashboard_link(request.path_params["ticket"])
        joining = await asyncio.to_thread(_in_transaction, _username, holder)
    except (InvalidTicket, SignedOut):
        _refused(request, "Dashboard sign-in refused: the link was not valid or had expired.",
                 "dashboard link")
        return _signed_out_page(request)

    current = await _current_user(request)
    if current is not None and current.user_id != holder.user_id:
        current_name = await asyncio.to_thread(_in_transaction, _username, current)
        return _switch_page(holder, joining, current_name)
    return _start_session(request, holder)


@_route(DASHBOARD_LOGIN_PATH + "/{ticket}", methods=["POST"])
@handle_route_errors
async def switch_account(request: Request) -> Response:
    """The button on the page `sign_in` asks with: sign this browser in as the link's user."""
    _require_request_header(request)
    try:
        holder = get_ticket_signer().verified_dashboard_link(request.path_params["ticket"])
    except InvalidTicket as error:
        _refused(request, "Dashboard switch refused: the link was not valid or had expired.",
                 "dashboard link")
        raise SignedOut(_SIGNED_OUT) from error
    await asyncio.to_thread(_in_transaction, _username, holder)
    return _start_session(request, holder, _json({"ok": True}))


def _refused(request: Request, line: str, what: str) -> None:
    """Log a refused credential with its address and count it toward the throttle."""
    address = client_address(request)
    logger.info(f"{line} Client: '{address}'.")
    note_failure(get_failure_limiter(), address, what)


def _start_session(request: Request, holder: DashboardHolder,
                   response: Response | None = None) -> Response:
    response = response or RedirectResponse(APP_PATH, status_code=303, headers=_PAGE_HEADERS)
    response.set_cookie(
        _session_cookie(request),
        get_ticket_signer().sign_dashboard_session(holder),
        max_age=DASHBOARD_SESSION_LIFETIME_SECONDS,
        httponly=True,
        # Lax, not Strict: the link is usually opened from a chat window on another site, and
        # Strict would withhold the cookie on the redirect that follows. Requests that change
        # anything are protected by the header a cross-site page cannot send.
        samesite="lax",
        secure=_served_over_https(request),
        path="/",
    )
    logger.info(f"Dashboard session started. User: '{holder.user_id}'. "
                f"Machine: '{holder.machine_id}'.")
    return response


async def _current_user(request: Request) -> DashboardHolder | None:
    """Who this browser is signed in as now, if anyone, with a computer still connected."""
    try:
        holder = _signed_in(request)
        await asyncio.to_thread(_in_transaction, _username, holder)
        return holder
    except SignedOut:
        return None


def _switch_page(holder: DashboardHolder, joining: str, current: str) -> Response:
    """Ask before replacing a session. The link was spent on the way here, so the button
    carries a fresh one, good for the same few minutes and only once."""
    switch = f"{DASHBOARD_LOGIN_PATH}/{get_ticket_signer().sign_dashboard_link(holder)}"
    return HTMLResponse(
        "<!doctype html><meta charset=utf-8>"
        "<meta name=viewport content=\"width=device-width,initial-scale=1\"><title>AIStack</title>"
        "<body style=\"font:16px/1.5 system-ui;margin:15vh auto;max-width:32rem;padding:0 1rem\">"
        "<h1 style=\"font-size:1.25rem\">Switch account?</h1>"
        f"<p>This browser is signed in as <strong>{escape(current)}</strong>. The link you "
        f"opened signs it in as <strong>{escape(joining)}</strong>.</p>"
        "<p>If someone else sent you this link, stay with your own account.</p>"
        f"<p><button id=switch>Sign in as {escape(joining)}</button> "
        f"<a href=\"{APP_PATH}\">Stay signed in as {escape(current)}</a></p>"
        "<script>document.getElementById('switch').onclick=async()=>{"
        f"await fetch({json.dumps(switch)},{{method:'POST',headers:{{'{REQUEST_HEADER}':'1'}}}});"
        f"location.href={json.dumps(APP_PATH)}}}</script>",
        headers=_PAGE_HEADERS,
    )


@_route("/", methods=["GET"])
async def root(request: Request) -> Response:
    """The server's own address is what a person opens first: it leads to the page."""
    return RedirectResponse(APP_PATH, status_code=307)


@_route(APP_PATH, methods=["GET"])
async def app(request: Request) -> Response:
    """The page itself. It holds no data: everything it shows comes from `/api/state`."""
    try:
        _signed_in(request)
    except SignedOut:
        return _signed_out_page(request)
    return HTMLResponse(dashboard_page(), headers=_PAGE_HEADERS)


@_route(API_PATH + "/state", methods=["GET"])
@handle_route_errors
async def state(request: Request) -> Response:
    holder = _signed_in(request)
    if is_local_mode():
        await asyncio.to_thread(library_before_read)
    shown = await asyncio.to_thread(_in_transaction, _as_user(dashboard_service.state), holder,
                                    read_only=True)
    # The page hides what only a server can do, such as creating a team, when this is false.
    return _json(shown | {"server": not is_local_mode(), "library": library_description()})


@_route(API_PATH + "/logout", methods=["POST"])
@handle_route_errors
async def sign_out(request: Request) -> Response:
    _require_request_header(request)
    cookie = request.cookies.get(_session_cookie(request))
    if cookie is not None:
        # Ended on the server too, so a copy of the cookie stops working with it.
        get_ticket_signer().end_dashboard_session(cookie)
    response = _json({"ok": True})
    response.delete_cookie(_session_cookie(request), path="/")
    return response


Action = Callable[[Session, uuid.UUID, dict[str, str], dict[str, Any]], dict[str, Any] | None]


def _action(path: str, local: bool = True,
            credential: str | None = None) -> Callable[[Action], Action]:
    """Register a POST route that runs `function` for the signed-in user in one transaction.

    The function takes the session, the caller's user id, the path parameters, and the JSON
    body. The user id comes from the session cookie and from nowhere else. `local` false keeps
    a team action off the localhost dashboard. `credential` names what the body carries when
    it is one, such as an invite code: a NotFound then counts toward the throttle.
    """
    def register(function: Action) -> Action:
        @wraps(function)
        async def route(request: Request) -> Response:
            holder = _signed_in(request)
            _require_request_header(request)
            body = await _json_body(request)
            try:
                result = await asyncio.to_thread(_in_transaction, _as_user(function), holder,
                                                 dict(request.path_params), body)
            except NotFound:
                if credential is not None:
                    _refused(request, f"Dashboard {function.__name__} refused: the "
                                      f"{credential} did not work.", credential)
                raise
            result = result or {"ok": True}
            if is_local_mode():
                # False when a GitHub Library could not be reached: the change waits here.
                result = result | {"shared": await asyncio.to_thread(library_after_write)}
            return _json(result)

        _route(API_PATH + path, methods=["POST"], local=local)(handle_route_errors(route))
        return function
    return register


@_action("/skills/{name}/machines/{machine_id}")
def set_skill_on_machine(session, user_id, path, body):
    placed = dashboard_service.set_on_machine(session, user_id, path["name"],
                                              path["machine_id"], _flag(body, "enabled"),
                                              _text(body, "harness", required=False))
    # Local mode logs every change, so other computers sharing the Library get it (ADR-0025).
    if is_local_mode():
        library_log.record(session, library_log.new_event(
            session, get_local_principal().machine_id, library_log.SKILL_PLACED,
            name=placed.name, harness=placed.harness, enabled=placed.enabled,
            target_machine_id=str(placed.machine_id)))


@_action("/skills/{name}/share", local=False)
def share_skill(session, user_id, path, body):
    shared = skill_service.share(session, user_id, path["name"], _text(body, "team"),
                                 _text(body, "group", required=False))
    return {
        "team": shared.team, "group": shared.group, "revision": shared.revision,
        "created": shared.created, "unchanged": shared.unchanged,
        "previous_pushed_by": shared.previous_pushed_by,
        "possibly_unrelated": shared.possibly_unrelated,
        "overwrote_revision": shared.overwrote_revision,
        "updates_from": shared.updates_from,
    }


@_action("/skills/{name}/remove")
def remove_my_skill(session, user_id, path, body):
    removed = skill_service.remove_from_my_skills(session, user_id, path["name"])
    if is_local_mode():
        library_log.record(session, library_log.new_event(
            session, get_local_principal().machine_id, library_log.SKILL_REMOVED, name=removed))


# Server only for now: in local mode a removal or a rename is a change to the Library's log,
# which every computer must be able to replay before any records one (ADR-0024, ADR-0025).
@_action("/machines/{machine_id}/remove", local=False)
def remove_machine(session, user_id, path, body):
    return {"removed": onboarding_service.remove_machine(session, user_id,
                                                         path["machine_id"])}


@_action("/machines/{machine_id}/rename", local=False)
def rename_machine(session, user_id, path, body):
    return {"name": onboarding_service.rename_machine(session, user_id, path["machine_id"],
                                                      _text(body, "name"))}


# A name for teammates to read; local mode has no teammates.
@_action("/account", local=False)
def change_account(session, user_id, path, body):
    return {"full_name": onboarding_service.set_full_name(session, user_id,
                                                          _text(body, "full_name"))}


@_action("/teams", local=False)
def create_team(session, user_id, path, body):
    return {"name": team_service.create_team(session, user_id, _text(body, "name"))}


@_action("/teams/join", local=False, credential="team invite code")
def join_team(session, user_id, path, body):
    return {"team": team_service.join_team(session, user_id, _text(body, "code"))}


@_action("/teams/{team}/leave", local=False)
def leave_team(session, user_id, path, body):
    team_service.leave_team(session, user_id, path["team"])


# Deleting removes the team's copies of its skills for everyone in it (ADR-0028).
@_action("/teams/{team}/delete", local=False)
def delete_team(session, user_id, path, body):
    team_service.delete_team(session, user_id, path["team"])


@_action("/teams/{team}/invite", local=False)
def new_invite_code(session, user_id, path, body):
    # Returned to the admin who asked, once, and never logged.
    return {"code": team_service.new_invite_code(session, user_id, path["team"])}


@_action("/teams/{team}/invites/{invite_id}/cancel", local=False)
def cancel_invite(session, user_id, path, body):
    team_service.cancel_invite(session, user_id, path["team"], path["invite_id"])


@_action("/teams/{team}/take", local=False)
def take_from_team(session, user_id, path, body):
    skill_service.take_from_team(session, user_id, _text(body, "name"), path["team"],
                                 replace=_flag(body, "replace", required=False) or False)


@_action("/teams/{team}/members/{username}", local=False)
def change_member(session, user_id, path, body):
    team_service.set_member(
        session, user_id, path["team"], path["username"],
        role=_text(body, "role", required=False),
        sees_all_groups=_flag(body, "sees_all_groups", required=False),
        can_invite=_flag(body, "can_invite", required=False),
    )


@_action("/teams/{team}/members/{username}/remove", local=False)
def remove_member(session, user_id, path, body):
    team_service.remove_member(session, user_id, path["team"], path["username"])


@_action("/teams/{team}/groups", local=False)
def create_group(session, user_id, path, body):
    return {"path": team_service.create_group(
        session, user_id, path["team"], _text(body, "name"),
        parent=_text(body, "parent", required=False),
        private=bool(_flag(body, "private", required=False)),
    )}


# A group's path has slashes in it, so it travels in the body and not in the URL.
@_action("/teams/{team}/group", local=False)
def change_group(session, user_id, path, body):
    group = _text(body, "path")
    private = _flag(body, "private", required=False)
    subscribed = _flag(body, "subscribed", required=False)
    if private is not None:
        team_service.set_group(session, user_id, path["team"], group, private)
    if subscribed is not None:
        team_service.set_subscribed(session, user_id, path["team"], group, subscribed)


@_action("/teams/{team}/group/members", local=False)
def change_group_member(session, user_id, path, body):
    team_service.set_group_member(session, user_id, path["team"], _text(body, "path"),
                                  _text(body, "username"), _flag(body, "member"))


@_action("/teams/{team}/skills/{name}/move", local=False)
def move_team_skill(session, user_id, path, body):
    team_service.move_skill(session, user_id, path["team"], path["name"],
                            _text(body, "group", required=False))


@_action("/teams/{team}/skills/{name}/remove", local=False)
def remove_team_skill(session, user_id, path, body):
    team_service.remove_skill(session, user_id, path["team"], path["name"])


def _session_cookie(request: Request) -> str:
    """A browser keeps one set of cookies for 127.0.0.1 across every port, so a localhost
    dashboard names its cookie by its port and two dashboards do not sign each other out.

    Over https the name takes the `__Host-` prefix, which a browser accepts only from this
    exact host, so a sibling subdomain cannot plant a session of its own.
    """
    if is_local_mode():
        return f"{SESSION_COOKIE}_{request.url.port}"
    return f"__Host-{SESSION_COOKIE}" if _served_over_https(request) else SESSION_COOKIE


def _signed_in(request: Request) -> DashboardHolder:
    """Who this browser is signed in as, from the session cookie and nothing else. Whether
    the computer behind it is still connected is checked in each request's transaction."""
    cookie = request.cookies.get(_session_cookie(request))
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
    raw = await bounded_body(request, _MAX_BODY_BYTES,
                             f"The request is larger than {_MAX_BODY_BYTES} bytes.",
                             _BODY_READ_TIMEOUT_SECONDS)
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


def _in_transaction(function: Callable[..., Any], holder: DashboardHolder, *arguments: Any,
                    read_only: bool = False) -> Any:
    """One request, one transaction, exactly as a tool call, for a session whose computer is
    still connected."""
    factory = get_read_session_factory() if read_only else get_session_factory()
    with factory.begin() as session:
        dashboard_service.require_its_machine(session, holder)
        return function(session, holder, *arguments)


def _as_user(function: Callable[..., Any]) -> Callable[..., Any]:
    """A service call that takes the caller's user id, as `state` and every action do."""
    return lambda session, holder, *arguments: function(session, holder.user_id, *arguments)


def _username(session: Session, holder: DashboardHolder) -> str:
    return dashboard_service.username(session, holder.user_id)


def _json(payload: dict[str, Any]) -> JSONResponse:
    return JSONResponse(payload, headers=_API_HEADERS)


def _signed_out_page(request: Request) -> Response:
    return HTMLResponse(
        "<!doctype html><meta charset=utf-8>"
        "<meta name=viewport content=\"width=device-width,initial-scale=1\"><title>AIStack</title>"
        + ICON_LINK +
        "<body style=\"font:16px/1.5 system-ui;margin:15vh auto;max-width:32rem;padding:0 1rem\">"
        "<h1 style=\"font-size:1.25rem\">You are not signed in</h1>"
        "<p>Ask your coding agent to <strong>open my aistack dashboard</strong>. It will "
        "give you a link that signs you in. A link works for five minutes.</p>"
        + _not_connected_yet(request),
        status_code=401,
        headers=_PAGE_HEADERS,
    )


def _not_connected_yet(request: Request) -> str:
    """For someone whose agent is not connected yet: the sentence that connects it.

    Built from the server's own address only, so nothing secret is on a page anyone can open.
    """
    if is_local_mode():
        return ""
    try:
        server = server_base_url(request)
    except ValidationError:
        return ""
    sentence = (f"Set up AIStack: fetch {server}/setup and follow it.\n"
                "Invite code: <the invite code>. Call me <your name>.")
    return ("<p>Not connected yet? Paste this into Claude Code or Codex, with the invite code "
            "you were given and the name you want to go by:</p>"
            "<pre style=\"white-space:pre-wrap;padding:12px;border:1px solid #8884;"
            f"border-radius:8px\">{escape(sentence)}</pre>")


def _served_over_https(request: Request) -> bool:
    public_url = get_public_url()
    if public_url is not None:
        return public_url.startswith("https://")
    return request.url.scheme == "https"
