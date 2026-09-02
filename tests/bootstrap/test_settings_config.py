import logging

import pytest
from pydantic import SecretStr, ValidationError

from aistack.bootstrap.__main__ import WIRE_LOGGERS
from aistack.bootstrap.configuration.settings.settings_config import (PLACEHOLDER_INVITE_CODE,
                                                                      Settings,
                                                                      validate_invite_code)


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


def test_the_wire_loggers_that_would_print_a_token_are_named():
    # A rename upstream would silently reopen the leak, so the names are asserted, not trusted.
    for wire_logger in WIRE_LOGGERS:
        assert logging.getLogger(wire_logger) is not None
    assert {"sse_starlette", "httpx"}.issubset(set(WIRE_LOGGERS))
