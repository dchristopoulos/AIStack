import pytest
from starlette.requests import Request

from aistack.bootstrap.configuration.settings.settings_config import Settings
from aistack.bootstrap.context import application_context
from aistack.commons.exceptions import ValidationError
from aistack.mcp.server_url import mcp_endpoint_url, server_base_url


@pytest.fixture(name="context")
def context_fixture(sqlite_url):
    def build(**overrides):
        application_context.build_application_context(Settings(
            _env_file=None,
            database_url=sqlite_url,
            aistack_invite_code="a-real-invite-code-of-enough-length",
            **overrides,
        ))

    yield build
    application_context.dispose_application_context()


def _request(host: str, scheme: str = "http") -> Request:
    return Request({
        "type": "http",
        "method": "POST",
        "scheme": scheme,
        "path": "/mcp",
        "root_path": "",
        "query_string": b"",
        "headers": [(b"host", host.encode("latin-1"))],
        "server": ("127.0.0.1", 8000),
    })


@pytest.mark.parametrize(("host", "scheme", "expected"), [
    ("aistack.example.com", "https", "https://aistack.example.com"),
    ("localhost:8000", "http", "http://localhost:8000"),
    ("10.0.0.5:8000", "http", "http://10.0.0.5:8000"),
    ("[::1]:8000", "http", "http://[::1]:8000"),
])
def test_the_base_url_is_taken_from_the_request_when_none_is_configured(context, host, scheme,
                                                                       expected):
    context()

    assert server_base_url(_request(host, scheme)) == expected


def test_a_configured_public_url_wins_over_the_request(context):
    context(aistack_public_url="https://aistack.example.com/")

    assert server_base_url(_request("10.0.0.5:8000")) == "https://aistack.example.com"
    assert mcp_endpoint_url(_request("10.0.0.5:8000")) == "https://aistack.example.com/mcp"


HOSTILE_HOSTS = [
    "example.com; rm -rf ~",
    "example.com$(id)",
    "example.com`id`",
    'example.com" --header "x',
    "example.com\nX-Injected: 1",
    "user@example.com",
]


@pytest.mark.parametrize("host", HOSTILE_HOSTS)
def test_a_malformed_host_header_never_reaches_the_address(context, host):
    """The derived address ends up in a command a person pastes into a shell."""
    context()

    assert server_base_url(_request(host)) == "http://127.0.0.1:8000"


@pytest.mark.parametrize("host", HOSTILE_HOSTS)
def test_with_no_address_to_fall_back_to_the_request_is_refused(context, host):
    context()
    request = _request(host)
    request.scope["server"] = None

    with pytest.raises(ValidationError) as rejection:
        server_base_url(request)

    assert "AISTACK_PUBLIC_URL" in str(rejection.value)
    assert host not in str(rejection.value)


@pytest.mark.parametrize(("host", "root_path"), [
    ("example.com", "/$(id)"),
    ("example.com:999999", ""),
])
def test_a_refused_address_is_not_repeated_in_the_error(context, host, root_path):
    context()
    request = _request(host)
    request.scope["server"] = None
    request.scope["root_path"] = root_path

    with pytest.raises(ValidationError) as rejection:
        server_base_url(request)

    assert "AISTACK_PUBLIC_URL" in str(rejection.value)
    assert "example.com" not in str(rejection.value)
    assert "$(id)" not in str(rejection.value)


def test_the_mcp_endpoint_follows_the_configured_path(context):
    context(aistack_mcp_path="/vault")

    assert mcp_endpoint_url(_request("localhost:8000")) == "http://localhost:8000/vault"
