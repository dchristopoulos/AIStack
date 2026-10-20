import logging

from starlette.requests import Request

from aistack.bootstrap.context.application_context import get_settings
from aistack.commons.exceptions import ValidationError
from aistack.commons.text import loggable
from aistack.commons.urls import is_plain_http_url

# Where a link from `open_dashboard` signs a browser in. Here, with the other addresses the
# server hands out, so the tool that builds the link and the route that answers it agree.
DASHBOARD_LOGIN_PATH = "/app/login"
# The dashboard page itself, which an invite page links to.
APP_PATH = "/app"
# Where a team's invite link lands (ADR-0019).
INVITE_PATH = "/invite"

logger = logging.getLogger(__name__)
# Said once per process: every request through such a proxy would repeat it.
_warned_of_untrusted_proxy = False


def server_base_url(request: Request) -> str:
    """The address this server is reached at, without a trailing slash.

    AISTACK_PUBLIC_URL wins when set. Otherwise the address is the one the request arrived on,
    which comes from the Host header and is therefore the caller's own choice. It only ever
    goes back to that same caller, but it goes back inside a command a person pastes into a
    shell. Starlette already falls back to the bound address when the header is malformed;
    the check here keeps that true if it ever stops, and catches the case where there is
    no address to fall back to.
    """
    configured = get_settings().public_url
    if configured is not None:
        return configured

    derived = str(request.base_url).rstrip("/")
    if not is_plain_http_url(derived):
        raise ValidationError(
            "This server cannot tell what address it is reached at: the address the request "
            "arrived on is not a plain http(s) URL. Ask whoever runs the server to set "
            "AISTACK_PUBLIC_URL to the address people reach it at."
        )
    if derived.startswith("http://"):
        _warn_of_untrusted_proxy(request)
    return derived


def _warn_of_untrusted_proxy(request: Request) -> None:
    """A proxy said the request came over https, and uvicorn did not apply it because the
    proxy is not at an address it trusts (AUTO-17). The address handed out is then http://,
    and the first request a pasted command makes goes out in the clear."""
    global _warned_of_untrusted_proxy
    forwarded = (request.headers.get("x-forwarded-proto", "")
                 + request.headers.get("forwarded", "")).lower()
    if _warned_of_untrusted_proxy or "https" not in forwarded:
        return
    _warned_of_untrusted_proxy = True
    logger.warning(
        "Requests arrive through a proxy that says https, but AISTACK_PUBLIC_URL is not set, "
        "so this server hands out http:// addresses. Set AISTACK_PUBLIC_URL="
        f"https://{loggable(request.url.netloc)}."
    )


def mcp_endpoint_url(request: Request) -> str:
    """The URL a harness is configured with to reach this server's MCP endpoint."""
    return f"{server_base_url(request)}{get_settings().mcp_path}"
