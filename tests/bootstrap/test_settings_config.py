import logging

import pytest
from pydantic import SecretStr, ValidationError

from aistack.bootstrap.__main__ import WIRE_LOGGERS, configure_logging
from aistack.bootstrap.configuration.settings.settings_config import (PLACEHOLDER_INVITE_CODE,
                                                                      Settings,
                                                                      validate_invite_code)


@pytest.fixture(autouse=True)
def restore_logging():
    """configure_logging() reconfigures the root logger globally, so put it back afterwards."""
    root = logging.getLogger()
    level, handlers = root.level, list(root.handlers)
    yield
    root.setLevel(level)
    root.handlers = handlers


def _settings(**overrides) -> Settings:
    return Settings(aistack_invite_code="a-real-invite-code", **overrides)


def test_defaults_are_documented_and_sqlite_backed():
    settings = _settings()

    assert settings.database_url.startswith("sqlite:///")
    assert settings.host == "0.0.0.0"
    assert settings.port == 8000
    assert settings.mcp_path == "/mcp"
    assert settings.log_level == "INFO"


def test_a_missing_invite_code_fails_startup():
    with pytest.raises(ValidationError) as rejection:
        Settings(_env_file=None)

    assert "aistack_invite_code" in str(rejection.value).lower()


@pytest.mark.parametrize("invite_code", [PLACEHOLDER_INVITE_CODE, "tiny7chr", " padded-code-here "])
def test_a_placeholder_or_unusable_invite_code_fails_startup(invite_code):
    with pytest.raises(ValueError) as rejection:
        validate_invite_code(SecretStr(invite_code))

    # Says which variable to fix, and never prints what was configured.
    assert "AISTACK_INVITE_CODE" in str(rejection.value)
    assert invite_code not in str(rejection.value)


def test_a_usable_invite_code_passes_startup_validation():
    validate_invite_code(SecretStr("a-real-invite-code"))


def test_the_configured_invite_code_is_masked_in_any_repr():
    settings = _settings()

    assert "a-real-invite-code" not in repr(settings)
    assert "a-real-invite-code" not in str(settings.invite_code)


def test_the_log_level_is_normalized_and_validated():
    assert _settings(aistack_log_level="debug").log_level == "DEBUG"

    with pytest.raises(ValidationError):
        _settings(aistack_log_level="chatty")


@pytest.mark.parametrize("log_level", ["DEBUG", "INFO", "WARNING"])
def test_the_wire_loggers_never_drop_below_info(log_level):
    """DEBUG on those loggers writes the machine token, in a payload, to the log file."""
    configure_logging(log_level)

    for wire_logger in WIRE_LOGGERS:
        assert logging.getLogger(wire_logger).level >= logging.INFO

    # AIStack's own loggers still follow the operator's choice.
    assert logging.getLogger("aistack").getEffectiveLevel() == logging.getLevelName(log_level)


def test_every_library_that_prints_the_wire_payload_is_floored():
    # A library added to the stack, or renamed upstream, silently reopens the leak. These are
    # the ones observed printing a full tool result at DEBUG.
    assert {"mcp.client", "mcp.server.streamable_http",
            "sse_starlette", "httpcore", "httpx"}.issubset(set(WIRE_LOGGERS))
