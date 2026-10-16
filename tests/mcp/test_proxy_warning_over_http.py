"""AUTO-17: behind a TLS proxy uvicorn does not trust, the server hands out http:// addresses.
It cannot know its https address on its own, so it says once which setting fixes it."""

import logging
import socket

import httpx
import pytest

pytestmark = pytest.mark.anyio

# A loopback address that is not 127.0.0.1, standing in for Docker's bridge gateway: uvicorn
# trusts forwarded headers from 127.0.0.1 only.
PROXY_ADDRESS = "127.0.0.2"


def _can_bind(address: str) -> bool:
    try:
        with socket.socket() as probe:
            probe.bind((address, 0))
        return True
    except OSError:
        return False


@pytest.mark.skipif(not _can_bind(PROXY_ADDRESS), reason=f"{PROXY_ADDRESS} is not loopback here")
async def test_a_proxy_that_says_https_without_a_public_url_is_named_once(server_url, caplog,
                                                                       monkeypatch):
    monkeypatch.setattr("aistack.mcp.server_url._warned_of_untrusted_proxy", False)
    setup = server_url.removesuffix("/mcp") + "/setup"
    transport = httpx.AsyncHTTPTransport(local_address=PROXY_ADDRESS)
    headers = {"X-Forwarded-Proto": "https", "Host": "aistack.example.com"}

    with caplog.at_level(logging.INFO):
        async with httpx.AsyncClient(transport=transport) as http:
            first = await http.get(setup, headers=headers)
            second = await http.get(setup, headers=headers)

    assert first.status_code == second.status_code == 200
    # Still http: the server cannot tell the proxy's word from a caller's.
    assert "http://aistack.example.com/" in first.text
    warnings = [record.getMessage() for record in caplog.records
                if record.levelno == logging.WARNING and "AISTACK_PUBLIC_URL" in
                record.getMessage()]
    assert len(warnings) == 1
    assert "https://aistack.example.com" in warnings[0]
    assert "/setup" not in warnings[0]
