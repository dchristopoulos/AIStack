"""The dashboard: one page and the JSON routes behind it (ADR-0017).

Every route here is thin in the same way a tool is: it establishes who is asking, runs one
service call in one transaction off the event loop, and returns what that call returned.
Nothing is decided here about who may see or change what; the services decide.
"""

import asyncio
import json
import logging
import re
import subprocess
import uuid
from collections.abc import Callable
from functools import wraps
from html import escape
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Route

from aistack.bootstrap import start_agent
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
    refuse_when_moved,
)
from aistack.bundled import PLAIN_PAGE_SCRIPT, dashboard_page, plain_page, script_source
from aistack.commons.exceptions import (
    AIStackError,
    InvalidTicket,
    NotFound,
    SignedOut,
    ValidationError,
)
from aistack.commons.release import release
from aistack.mcp.auth.failure_limiter import client_address, note_failure
from aistack.mcp.mcp import mcp
from aistack.mcp.routes.request_body import bounded_body
from aistack.mcp.routes.route_error_handler import handle_route_errors
from aistack.mcp.server_url import APP_PATH, DASHBOARD_LOGIN_PATH, mcp_endpoint_url, server_base_url
from aistack.services import (
    computer_codes,
    dashboard_service,
    library_log,
    onboarding_service,
    project_file_service,
    projects,
    repository_work,
    rule_service,
    skill_service,
    team_service,
)
from aistack.services.rule_validation import credential_lines, validated_rule_text
from aistack.services.skill_archive import build_archive
from aistack.services.transfer_ticket import DASHBOARD_SESSION_LIFETIME_SECONDS, DashboardHolder

logger = logging.getLogger(__name__)

API_PATH = "/api"

SESSION_COOKIE = "aistack_session"
# A header a cross-site form cannot set, required on every request that changes something.
REQUEST_HEADER = "x-aistack-request"

_MAX_BODY_BYTES = 16 * 1024
# A rule's text is up to 64 KiB of UTF-8, and JSON may spell one byte in six (`\u0001`), so
# the service, not this, says what was too long.
_RULE_BODY_BYTES = 6 * 64 * 1024 + _MAX_BODY_BYTES
_BODY_READ_TIMEOUT_SECONDS = 10

_SIGNED_OUT = ("You are not signed in to this dashboard. Ask your coding agent to \"open my "
               "aistack dashboard\" for a new link.")

def _page_headers(*scripts: str) -> dict[str, str]:
    """A page loads nothing from anywhere else and may only talk to this server. Its styles
    and scripts are inline because it is one file; the scripts run only as these exact texts,
    by their hashes, so markup someone slipped into a skill's description runs nothing
    (STD-13). The styles stay inline-allowed for the page's style attributes."""
    sources = " ".join(script_source(script) for script in scripts) or "'none'"
    return {
        "Content-Security-Policy": (
            f"default-src 'none'; style-src 'unsafe-inline'; script-src {sources}; "
            "connect-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'none'; "
            "frame-ancestors 'none'"),
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
        "Cache-Control": "no-store",
    }


_PAGE_HEADERS = _page_headers(*re.findall(r"<script>(.*?)</script>", dashboard_page(), re.S))
_PLAIN_HEADERS = _page_headers(PLAIN_PAGE_SCRIPT)
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

    The redirect takes the ticket out of the address bar. A link works once: opened again in
    a browser that it already signed in, it leads to the page; anywhere else, a link that was
    used, has expired, or comes from a computer no longer connected says so. A browser
    already signed in as someone else is asked first: a link anyone sends could otherwise
    sign it in to their account (ADR-0027).
    """
    try:
        holder = get_ticket_signer().verified_dashboard_link(request.path_params["ticket"])
        joining = await asyncio.to_thread(_in_transaction, _username, holder)
    except (InvalidTicket, SignedOut):
        # A browser opens the link it was handed and the person clicks it too (UX-02).
        if await _current_user(request) is not None:
            return RedirectResponse(APP_PATH, status_code=303, headers=_PAGE_HEADERS)
        _refused(request, "Dashboard sign-in refused: the link was not valid or had expired.",
                 "dashboard link")
        return _link_spent_page()

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
    script = ("document.getElementById('switch').onclick=async()=>{"
              f"await fetch({json.dumps(switch)},"
              f"{{method:'POST',headers:{{'{REQUEST_HEADER}':'1'}}}});"
              f"location.href={json.dumps(APP_PATH)}}}")
    return HTMLResponse(plain_page(
        "Switch account?, AIStack",
        "<h1>Switch account?</h1>"
        f"<p>This browser is signed in as <strong>{escape(current)}</strong>. The link you "
        f"opened signs it in as <strong>{escape(joining)}</strong>.</p>"
        "<p>If someone else sent you this link, stay with your own account.</p>"
        f"<p><button id=switch>Sign in as {escape(joining)}</button> "
        f"<a href=\"{APP_PATH}\">Stay signed in as {escape(current)}</a></p>"
        f"<script>{script}</script>"),
        headers=_page_headers(script, PLAIN_PAGE_SCRIPT),
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
        shown, folders = await asyncio.to_thread(_in_transaction, _state_here, holder,
                                                 read_only=True)
        # Read after the transaction: on SQLite a read must not hold anything while it works.
        await asyncio.to_thread(_read_working_copies, shown["project_files"], folders,
                                holder.machine_id)
    else:
        shown = await asyncio.to_thread(_in_transaction, _as_user(dashboard_service.state),
                                        holder, read_only=True)
    # The page hides what only a server can do, such as creating a team, when this is false.
    # `this_computer` is the one whose link opened this session: the page says "This one".
    return _json(shown | {"server": not is_local_mode(), "library": library_description(),
                          "release": release(), "this_computer": str(holder.machine_id)})


@_route(API_PATH + "/skills/{name}/history", methods=["GET"], local=False)
@handle_route_errors
async def skill_history(request: Request) -> Response:
    holder = _signed_in(request)
    return _json(await asyncio.to_thread(
        _in_transaction, _as_user(dashboard_service.history), holder,
        request.path_params["name"], read_only=True))


@_route(API_PATH + "/teams/{team}/skills/{name}/changes", methods=["GET"], local=False)
@handle_route_errors
async def team_update_changes(request: Request) -> Response:
    holder = _signed_in(request)
    return _json(await asyncio.to_thread(
        _in_transaction, _as_user(dashboard_service.update_changes), holder,
        request.path_params["team"], request.path_params["name"], read_only=True))


# A project's key has slashes in it, so it travels in the query, as `?project=<key>`.
@_route(API_PATH + "/rules/{name}/text", methods=["GET"])
@handle_route_errors
async def rule_text(request: Request) -> Response:
    holder = _signed_in(request)
    return _json(await asyncio.to_thread(
        _in_transaction, _as_user(rule_service.text_of), holder, request.path_params["name"],
        request.query_params.get("project"), read_only=True))


@_route(API_PATH + "/library.tar.gz", methods=["GET"])
@handle_route_errors
async def download_library(request: Request) -> Response:
    """The person's whole Library as one archive, a folder per skill, as `aistack export`
    writes it: their data, theirs to take elsewhere (STD-15)."""
    holder = _signed_in(request)
    if is_local_mode():
        await asyncio.to_thread(library_before_read)
    skills = await asyncio.to_thread(_in_transaction, _as_user(skill_service.export_library),
                                     holder, read_only=True)
    # Packed after the transaction: on SQLite a read must not hold anything while it works.
    # ponytail: built in memory, a few MB for a real Library; stream it if Libraries grow.
    archive = await asyncio.to_thread(build_archive, (
        (f"{skill.name}/{path}", content, executable)
        for skill in skills for path, content, executable in skill.files),
        max((skill.modified_at for skill in skills), default=0))
    return Response(archive, media_type="application/gzip", headers=_API_HEADERS | {
        "Content-Disposition": 'attachment; filename="aistack-library.tar.gz"'})


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


def _action(path: str, local: bool = True, credential: str | None = None,
            with_holder: bool = False,
            body_limit: int = _MAX_BODY_BYTES) -> Callable[[Action], Action]:
    """Register a POST route that runs `function` for the signed-in user in one transaction.

    The function takes the session, the caller's user id, the path parameters, and the JSON
    body. The user id comes from the session cookie and from nowhere else. `local` false keeps
    a team action off the localhost dashboard. `credential` names what the body carries when
    it is one, such as an invite code: a NotFound then counts toward the throttle.
    `with_holder` also passes the verified issuing computer and the validated endpoint.
    `body_limit` is the most the body may be, in bytes.
    """
    def register(function: Action) -> Action:
        @wraps(function)
        async def route(request: Request) -> Response:
            holder = _signed_in(request)
            _require_request_header(request)
            if is_local_mode():
                await asyncio.to_thread(refuse_when_moved)
            body = await _json_body(request, body_limit)
            try:
                parameters = dict(request.path_params)
                if with_holder:
                    parameters["server"] = mcp_endpoint_url(request)
                target = function if with_holder else _as_user(function)
                result = await asyncio.to_thread(_in_transaction, target, holder,
                                                 parameters, body)
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


@_action("/computer-codes", local=False, with_holder=True)
def create_computer_code(session, holder, path, body):
    return computer_codes.commands(
        computer_codes.create(
            session,
            holder.user_id,
            holder.machine_id,
            holder.token_prefix,
            body,
        ),
        path["server"],
    )


@_action("/computer-codes/{id}", local=False)
def change_computer_code(session, user_id, path, body):
    return computer_codes.change(session, user_id, path["id"], body)


@_action("/computer-codes/{id}/cancel", local=False)
def cancel_computer_code(session, user_id, path, body):
    return computer_codes.decide(session, user_id, path["id"], "cancel")


@_action("/computer-codes/{id}/approve", local=False)
def approve_computer_code(session, user_id, path, body):
    return computer_codes.decide(session, user_id, path["id"], "approve")


@_action("/computer-codes/{id}/deny", local=False)
def deny_computer_code(session, user_id, path, body):
    return computer_codes.decide(session, user_id, path["id"], "deny")


@_action("/skills/{name}/machines/{machine_id}")
def set_skill_on_machine(session, user_id, path, body):
    project = _text(body, "project", required=False)
    if project is not None and is_local_mode():
        # Its log event is replayed by this release and recorded by a later one (ADR-0026).
        raise ValidationError("A project's folders are managed on an AIStack server for now. "
                              "Local mode will manage them in a later release.")
    placed = dashboard_service.set_on_machine(session, user_id, path["name"],
                                              path["machine_id"], _flag(body, "enabled"),
                                              _text(body, "harness", required=False),
                                              project)
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


# Server only for now: local mode records it once a release replays its event (ADR-0026).
@_action("/skills/{name}/bring-back", local=False)
def bring_back(session, user_id, path, body):
    return {"name": skill_service.bring_back(session, user_id, path["name"])}


# Server only for now, as bring-back is.
@_action("/skills/{name}/restore", local=False)
def restore_revision(session, user_id, path, body):
    restored = skill_service.restore_revision(session, user_id, path["name"],
                                              body.get("revision"))
    return {"revision": restored.revision, "unchanged": restored.unchanged}


@_action("/skills/{name}/remove")
def remove_my_skill(session, user_id, path, body):
    removed = skill_service.remove_from_my_skills(session, user_id, path["name"])
    if is_local_mode():
        library_log.record(session, library_log.new_event(
            session, get_local_principal().machine_id, library_log.SKILL_REMOVED, name=removed))


# A project's key has slashes in it, so it travels in the body. Server only for
# now: in local mode each is a log event a later release records (ADR-0026).
@_action("/machines/{machine_id}/projects", local=False)
def add_project(session, user_id, path, body):
    dashboard_service.add_project(session, user_id, path["machine_id"], _text(body, "project"),
                                  _text(body, "harness", required=False))


@_action("/machines/{machine_id}/projects/remove", local=False)
def remove_project(session, user_id, path, body):
    return {"removed": dashboard_service.remove_project(
        session, user_id, path["machine_id"], _text(body, "project"),
        _text(body, "harness", required=False))}


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


# Rules (ADR-0036). Local mode records each change as a log event, in the release that adds
# them (ADR-0039). A project's key has slashes in it, so `project` travels in the body.
@_action("/rules", body_limit=_RULE_BODY_BYTES)
def create_rule(session, user_id, path, body):
    project, text, agents = (_text(body, "project", required=False), _text(body, "text"),
                             _texts(body, "agents"))
    saved = rule_service.create(session, user_id, _text(body, "name"), text, project, agents,
                                bool(_flag(body, "confirmed", required=False)))
    if saved.saved:
        _logged(session, library_log.RULE_CREATED, name=saved.name, project=project, text=text,
                agents=agents)
    return _saved(saved)


@_action("/rules/{name}/edit", body_limit=_RULE_BODY_BYTES)
def edit_rule(session, user_id, path, body):
    project, text = _text(body, "project", required=False), _text(body, "text")
    saved = rule_service.edit(session, user_id, path["name"], text, project,
                              bool(_flag(body, "confirmed", required=False)))
    if saved.saved and not saved.unchanged:
        _logged(session, library_log.RULE_EDITED, name=saved.name, project=project, text=text)
    return _saved(saved)


@_action("/rules/{name}/rename")
def rename_rule(session, user_id, path, body):
    project = _text(body, "project", required=False)
    renamed = rule_service.rename(session, user_id, path["name"], _text(body, "new_name"),
                                  project)
    if renamed != path["name"]:
        _logged(session, library_log.RULE_RENAMED, name=path["name"], project=project,
                new_name=renamed)
    return {"name": renamed}


@_action("/rules/{name}/agents")
def set_rule_agents(session, user_id, path, body):
    project = _text(body, "project", required=False)
    agents = rule_service.set_agents(session, user_id, path["name"], _texts(body, "agents"),
                                     project)
    _logged(session, library_log.RULE_AGENTS_SET, name=path["name"], project=project,
            agents=agents)
    return {"agents": agents}


@_action("/rules/{name}/remove")
def remove_rule(session, user_id, path, body):
    project = _text(body, "project", required=False)
    removed = rule_service.archive(session, user_id, path["name"], project)
    _logged(session, library_log.RULE_REMOVED, name=removed, project=project)
    return {"name": removed}


# A project's own files (ADR-0036): which the page shows, turning one off for this person, and
# an edit for one computer to write and share. Local mode logs a tick and a turn-off, and
# writes and shares an edit on this computer through its own routes below (ADR-0039).
@_action("/projects/files/tick")
def tick_project_file(session, user_id, path, body):
    project, file, ticked = _text(body, "project"), _text(body, "path"), _flag(body, "ticked")
    project_file_service.set_ticked(session, user_id, project, file, ticked)
    _logged(session, library_log.PROJECT_FILE_TICKED, project=project, path=file,
            ticked=ticked)


@_action("/projects/files/turn-off")
def turn_off_project_file(session, user_id, path, body):
    project, file = _text(body, "project"), _text(body, "path")
    turned_off = _flag(body, "turned_off")
    project_file_service.set_turned_off(session, user_id, project, file, turned_off)
    _logged(session, library_log.PROJECT_FILE_TURNED_OFF, project=project, path=file,
            turned_off=turned_off)


@_action("/projects/files/edit", local=False, body_limit=_RULE_BODY_BYTES)
def edit_project_file(session, user_id, path, body):
    return _saved(project_file_service.save_edit(
        session, user_id, _text(body, "project"), _text(body, "path"), _text(body, "text"),
        _text(body, "base_hash"), _text(body, "machine"),
        bool(_flag(body, "confirmed", required=False))))


@_action("/projects/files/commit", local=False)
def commit_project_file(session, user_id, path, body):
    return {"note": project_file_service.commit(session, user_id, _text(body, "project"),
                                                _text(body, "path"), _text(body, "note"))}


def _logged(session: Session, kind: str, **data: Any) -> None:
    """In local mode, record a change as an event in its transaction, so every computer
    sharing the Library makes it too (ADR-0025)."""
    if is_local_mode():
        library_log.record(session, library_log.new_event(
            session, get_local_principal().machine_id, kind, **data))


def _saved(saved: rule_service.Saved) -> dict[str, Any]:
    return {"name": saved.name, "saved": saved.saved, "credential_lines": saved.credential_lines,
            "revision": saved.revision, "unchanged": saved.unchanged}


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
    # Returned to the admin who asked, once, and never logged. The id is not secret: the page
    # names the invite by it in the list of invites.
    code, invite_id = team_service.new_invite(session, user_id, path["team"])
    return {"code": code, "id": str(invite_id)}


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


@_action("/teams/{team}/group/rename", local=False)
def rename_group(session, user_id, path, body):
    return {"path": team_service.rename_group(session, user_id, path["team"],
                                              _text(body, "path"), _text(body, "name"))}


@_action("/teams/{team}/group/delete", local=False)
def delete_group(session, user_id, path, body):
    team_service.delete_group(session, user_id, path["team"], _text(body, "path"))


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


@handle_route_errors
async def start_agent_here(request: Request) -> Response:
    """Opens a terminal on this computer running `aistack start` (ADR-0038). Registered on
    the localhost dashboard only: a server never starts a program on anybody's computer."""
    _signed_in(request)
    _require_request_header(request)
    body = await _json_body(request)
    await asyncio.to_thread(start_agent.start_from_page, _text(body, "agent"),
                            _text(body, "project"), _texts(body, "skills"))
    return _json({"ok": True})


LOCAL_ROUTES.append(Route(API_PATH + "/start-agent", start_agent_here, methods=["POST"]))


@handle_route_errors
async def look_inside(request: Request) -> Response:
    """What `aistack project add` would list for a folder on this computer: its agent files
    and other Markdown by path and size, and the skills its repository holds (ADR-0038).
    Registered on the localhost dashboard only: a server never reads anybody's disk."""
    _signed_in(request)
    _require_request_header(request)
    body = await _json_body(request)
    return _json(await asyncio.to_thread(repository_work.look_inside, _text(body, "folder"),
                                         Path.home()))


LOCAL_ROUTES.append(Route(API_PATH + "/projects/look-inside", look_inside, methods=["POST"]))


# A project's own files on the localhost dashboard (ADR-0039). Adding one is a change to the
# Library and is logged; an edit and its pull request change this computer's working copy and
# its remote, not the Library. The folder is read before the transaction, and written after.
@handle_route_errors
async def add_project_here(request: Request) -> Response:
    """Keep the files of the project a folder on this computer is in, ticked as the page
    ticked them, as `aistack project add` does on a server."""
    holder = _signed_in(request)
    _require_request_header(request)
    await asyncio.to_thread(refuse_when_moved)
    body = await _json_body(request)
    found = await asyncio.to_thread(repository_work.look_inside, _text(body, "folder"),
                                    Path.home())
    ticked = set(_texts(body, "ticked"))
    key = found["key"] or projects.local_project_key(holder.machine_id, found["top"])
    files = [{"path": file["path"], "size": file["size"]} for file in found["files"]]

    def add(session, holder):
        event = library_log.new_event(
            session, holder.machine_id, library_log.PROJECT_FILES_LISTED, project=key,
            project_name=found["name"], path=found["top"], files=files,
            ticked=[file["path"] for file in files if file["path"] in ticked])
        # The call replay makes, so this computer and every other one keep the same files.
        library_log.apply(session, event)
        library_log.record(session, event)

    await asyncio.to_thread(_in_transaction, add, holder)
    shared = await asyncio.to_thread(library_after_write)
    return _json({"project": key, "name": found["name"], "shared": shared})


@handle_route_errors
async def edit_file_here(request: Request) -> Response:
    """Write an edit of a repository file into this computer's working copy, only while the
    file still has the text the edit started from."""
    holder = _signed_in(request)
    _require_request_header(request)
    body = await _json_body(request, _RULE_BODY_BYTES)
    text = validated_rule_text(_text(body, "text"))
    lines = credential_lines(text)
    if lines and not _flag(body, "confirmed", required=False):
        return _json({"name": _text(body, "path"), "saved": False, "credential_lines": lines,
                      "revision": None, "unchanged": False})
    top, path = await _working_copy(holder, body)
    written = await asyncio.to_thread(repository_work.write_here, top, path, text,
                                      _text(body, "base_hash"))
    return _json({"name": path, "saved": True, "credential_lines": lines, "revision": None,
                  "unchanged": not written})


@handle_route_errors
async def share_file_here(request: Request) -> Response:
    """Share a repository file as this computer's working copy has it: a branch holding only
    that file, pushed, and a pull request opened with gh when it is signed in."""
    holder = _signed_in(request)
    _require_request_header(request)
    body = await _json_body(request)
    note = project_file_service.validated_note(_text(body, "note"))
    top, path = await _working_copy(holder, body)
    return _json(await asyncio.to_thread(repository_work.share_here, top, path, note)
                 | {"note": note})


async def _working_copy(holder: DashboardHolder, body: dict[str, Any]) -> tuple[Path, str]:
    """Where a listed file of one of the person's projects is on this computer, checked on
    disk: the folder this computer listed the project from, still that project's repository."""
    key, path = _text(body, "project"), _text(body, "path")

    def listed(session, holder):
        row = project_file_service.my_file(session, holder.user_id, key, path)
        folder = library_log.listed_from(session, holder.machine_id, key)
        if folder is None:
            raise NotFound("This project was not added on this computer, so its files are not "
                           "here. Add it by its folder on this computer first.")
        return folder, row.path

    folder, path = await asyncio.to_thread(_in_transaction, listed, holder, read_only=True)
    top = await asyncio.to_thread(repository_work.working_copy, folder, key, holder.machine_id,
                                  Path.home())
    return top, path


def _state_here(session: Session, holder: DashboardHolder) -> tuple[dict, dict[str, str]]:
    """The page's state, and the folder this computer listed each project from."""
    shown = dashboard_service.state(session, holder.user_id)
    keys = {file["project"] for file in shown["project_files"] if file["ticked"]}
    return shown, {key: folder for key in keys
                   if (folder := library_log.listed_from(session, holder.machine_id, key))}


def _read_working_copies(files: list[dict], folders: dict[str, str], machine_id) -> None:
    for key, folder in folders.items():
        here = [file for file in files if file["project"] == key and file["ticked"]]
        try:
            top = repository_work.working_copy(folder, key, machine_id, Path.home())
            repository_work.read_here(here, top, machine_id)
        except (OSError, subprocess.SubprocessError, AIStackError):
            # Moved or gone: the page shows the files unread until it is added again.
            continue


LOCAL_ROUTES.extend([
    Route(API_PATH + "/projects/add", add_project_here, methods=["POST"]),
    Route(API_PATH + "/projects/files/edit", edit_file_here, methods=["POST"]),
    Route(API_PATH + "/projects/files/commit", share_file_here, methods=["POST"]),
])


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


async def _json_body(request: Request, limit: int = _MAX_BODY_BYTES) -> dict[str, Any]:
    raw = await bounded_body(request, limit, f"The request is larger than {limit} bytes.",
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


def _texts(body: dict[str, Any], key: str) -> list[str]:
    """A list of text, empty when the body leaves it out."""
    value = body.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValidationError(f"'{key}' must be a list of text.")
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
    """The first page someone who has never seen AIStack meets: what it is, then the two ways
    in. Static text and the server's own address only, because anyone can open it."""
    return HTMLResponse(plain_page(
        "Sign in, AIStack",
        "<h1>Sign in to AIStack</h1>"
        "<p class=lede>AIStack keeps one private Library of the skills your coding agents use, "
        "on each of your computers and shared with your teams.</p>"
        "<section><h2>I have AIStack on this computer</h2>"
        "<p>Ask your coding agent to open your dashboard. It answers with a link that signs "
        "this browser in; a link works once, within five minutes.</p>"
        "<pre>open my aistack dashboard</pre></section>"
        + _not_connected_yet(request)),
        status_code=401,
        headers=_PLAIN_HEADERS,
    )


def _link_spent_page() -> Response:
    """A sign-in link opened a second time, or too late, in a browser it did not sign in.
    The person is connected already, so the setup sentence is not offered."""
    return HTMLResponse(plain_page(
        "Sign-in link used, AIStack",
        "<h1>This sign-in link has been used</h1>"
        "<p class=lede>A link works once, within five minutes, and this one has already been "
        "used or has expired.</p>"
        "<section><h2>Get a new link</h2>"
        "<p>Ask your coding agent for one:</p>"
        "<pre>open my aistack dashboard</pre></section>"),
        status_code=401,
        headers=_PLAIN_HEADERS,
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
                "Invite code: <the invite code>. My username is <a short handle like maria>, "
                "and my name is <your name>.")
    return ("<section><h2>I'm new here</h2>"
            "<p>Paste this into Claude Code or Codex, with the invite code you were given, a "
            "short username and your name filled in. It creates your account and connects "
            "this computer.</p>"
            f"<pre>{escape(sentence)}</pre></section>")


def _served_over_https(request: Request) -> bool:
    public_url = get_public_url()
    if public_url is not None:
        return public_url.startswith("https://")
    return request.url.scheme == "https"
