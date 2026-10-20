"""Remote credentials and transport policy shared by sync and computer setup (ADR-0035)."""

import ipaddress
import socket
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import httpx
from fastmcp import Client
from fastmcp.client import BearerAuth, StreamableHttpTransport

from aistack.commons.exceptions import ValidationError

_PRIVATE = tuple(ipaddress.ip_network(value) for value in (
    "127.0.0.0/8", "::1/128", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
    "fc00::/7", "100.64.0.0/10",
))


@dataclass(frozen=True)
class Connection:
    url: str
    token: str = field(repr=False)


def checked_server(url: str, allow_http: bool = False) -> str | None:
    """Return an HTTP warning, or refuse before sending any credential."""
    try:
        parts = urlsplit(url)
        if (parts.scheme not in ("http", "https") or not parts.hostname
                or parts.username or parts.password or parts.query or parts.fragment):
            raise ValueError
        port = parts.port
    except (ValueError, TypeError):
        raise ValidationError("Use a plain http(s) server address without credentials, query or fragment.") from None
    if parts.scheme == "https":
        return None
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(parts.hostname, port or 80, type=socket.SOCK_STREAM)}
        private = bool(addresses) and all(any(ipaddress.ip_address(address) in network for network in _PRIVATE)
                                          for address in addresses)
    except (OSError, ValueError):
        private = False
    if private:
        return "AIStack: this connection is not encrypted."
    if not allow_http:
        raise ValidationError("Use HTTPS for a public server, or pass --allow-http to accept sending the computer's key over plain HTTP.")
    return "AIStack: this connection is not encrypted; anyone on the network path can read this computer's key."


def http_client(**kwargs) -> httpx.AsyncClient:
    # Refuse all redirects: no credential can cross an origin through SDK redirect defaults.
    return httpx.AsyncClient(**(kwargs | {"follow_redirects": False, "timeout": 15.0}))


def client(connection: Connection) -> Client:
    return Client(
        StreamableHttpTransport(
            connection.url,
            auth=BearerAuth(connection.token),
            httpx_client_factory=http_client,
        ),
        timeout=20,
        init_timeout=20,
    )
