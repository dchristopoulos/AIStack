import logging

import pytest

from aistack.bootstrap.configuration.settings.settings_config import Settings
from aistack.bootstrap.context import application_context
from aistack.mcp.mcp import http_server_config, mcp


@pytest.fixture(name="context")
def context_fixture(sqlite_url):
    application_context.build_application_context(Settings(
        _env_file=None,
        database_url=sqlite_url,
        aistack_invite_code="a-real-invite-code-of-enough-length",
    ))
    yield
    application_context.dispose_application_context()


def test_the_access_log_is_off_because_a_transfer_url_is_a_credential(context):
    """An access log line is the request path, and the path holds the ticket (ADR-0010).

    Asserted on the configuration itself. A captured-log assertion cannot see this: pytest
    attaches its own handler to non-propagating loggers, so under test uvicorn's access
    logger looks configured whether or not production would write a line.
    """
    config = http_server_config(path="/mcp", log_level="INFO")

    assert config.access_log is False
    assert logging.getLogger("uvicorn.access").propagate is False


def test_the_server_refuses_to_be_built_without_a_token_verifier(context, monkeypatch):
    monkeypatch.setattr(mcp, "auth", None)

    with pytest.raises(RuntimeError, match="No token verifier is attached"):
        http_server_config(path="/mcp", log_level="INFO")


def test_the_bind_address_is_passed_through(context):
    config = http_server_config(path="/mcp", log_level="DEBUG", host="127.0.0.1", port=9123)

    assert (config.host, config.port) == ("127.0.0.1", 9123)
    assert config.log_level == "debug"
