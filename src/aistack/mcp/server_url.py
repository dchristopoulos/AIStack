import re

from starlette.requests import Request

from aistack.bootstrap.context.application_context import get_settings
from aistack.commons.exceptions import ValidationError
from aistack.commons.text import loggable

# What a base URL derived from a request may look like: scheme, a hostname or a bracketed IPv6
# literal, an optional port, an optional mount path. Nothing a shell would interpret.
_DERIVED_BASE_URL = re.compile(
    r"https?://(\[[0-9A-Fa-f:.]+\]|[A-Za-z0-9.-]+)(:\d{1,5})?(/[A-Za-z0-9._~/-]*)?"
)


def server_base_url(request: Request) -> str:
    """The address this server is reached at, without a trailing slash.

    AISTACK_PUBLIC_URL wins when set. Otherwise the address is the one the request arrived on,
    which comes from the Host header and is therefore the caller's own choice. It only ever
    goes back to that same caller, but it goes back inside a command a person pastes into a
    shell. Starlette already falls back to the bound address when the header is malformed;
    the pattern here keeps that true if it ever stops, and catches the case where there is
    no address to fall back to.
    """
    configured = get_settings().public_url
    if configured is not None:
        return configured

    derived = str(request.base_url).rstrip("/")
    if not _DERIVED_BASE_URL.fullmatch(derived):
        raise ValidationError(
            "This server cannot tell what address it is reached at: the request arrived for "
            f"'{loggable(derived)}', which is not a plain http(s) URL. Ask whoever runs the "
            "server to set AISTACK_PUBLIC_URL."
        )
    return derived


def mcp_endpoint_url(request: Request) -> str:
    """The URL a harness is configured with to reach this server's MCP endpoint."""
    return f"{server_base_url(request)}{get_settings().mcp_path}"
