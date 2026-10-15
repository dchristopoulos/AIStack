import logging

import fastmcp
import pytest
from pydantic import SecretStr, ValidationError

from aistack.bootstrap.__main__ import (
    ARGUMENT_ECHO_LOGGER,
    QUIET_LOGGERS,
    WIRE_LOGGERS,
    configure_logging,
)
from aistack.bootstrap.configuration.settings.settings_config import (PLACEHOLDER_INVITE_CODE,
                                                                      Settings,
                                                                      resolved_invite_code,
                                                                      validate_invite_code)


@pytest.fixture(autouse=True)
def restore_logging():
    """configure_logging() reconfigures the root logger globally, so put it back afterwards."""
    root = logging.getLogger()
    level, handlers = root.level, list(root.handlers)
    named = {name: logging.getLogger(name)
             for name in (*WIRE_LOGGERS, *QUIET_LOGGERS, "fastmcp", ARGUMENT_ECHO_LOGGER)}
    saved = {name: (each.level, list(each.handlers), list(each.filters), each.propagate)
             for name, each in named.items()}
    log_enabled = fastmcp.settings.log_enabled
    yield
    root.setLevel(level)
    root.handlers = handlers
    for name, (each_level, each_handlers, each_filters, propagate) in saved.items():
        named[name].setLevel(each_level)
        named[name].handlers = each_handlers
        named[name].filters = each_filters
        named[name].propagate = propagate
    fastmcp.settings.log_enabled = log_enabled


def _settings(**overrides) -> Settings:
    # _env_file=None or these read whatever .env the developer happens to have in the working
    # directory, and a test named "defaults are documented" then asserts against their config.
    return Settings(_env_file=None, aistack_invite_code="a-real-invite-code-of-enough-length", **overrides)


def test_defaults_are_documented_and_sqlite_backed():
    settings = _settings()

    assert settings.database_url.startswith("sqlite:///")
    assert settings.host == "0.0.0.0"
    assert settings.port == 8000
    assert settings.mcp_path == "/mcp"
    assert settings.log_level == "INFO"


def test_a_missing_invite_code_fails_startup():
    with pytest.raises(ValueError) as rejection:
        resolved_invite_code(Settings(_env_file=None))

    assert "AISTACK_INVITE_CODE" in str(rejection.value)


@pytest.mark.parametrize("invite_code", [
    PLACEHOLDER_INVITE_CODE,
    "tiny7chr",
    " padded-code-here-and-long-enough ",
    # Long enough, and guessable: one character, or a word said twice (SEC-02).
    "aaaaaaaaaaaaaaaa",
    "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "passwordpasswordpassword",
    # The README's demo code, printed for anyone to try.
    "try-it-out-locally-1234",
])
def test_a_placeholder_or_unusable_invite_code_fails_startup(invite_code):
    with pytest.raises(ValueError) as rejection:
        validate_invite_code(SecretStr(invite_code))

    # Says which variable to fix, and never prints what was configured.
    assert "AISTACK_INVITE_CODE" in str(rejection.value)
    assert invite_code.strip() not in str(rejection.value)


def test_a_generated_code_passes():
    validate_invite_code(SecretStr("Zm9vYmFyYmF6cXV4cXV1eDEyMzQ1Njc4"))


def test_the_invite_code_can_come_from_a_file(tmp_path):
    code_file = tmp_path / "invite-code.txt"
    # What `openssl rand -base64 24 > invite-code.txt` writes: the code and one newline.
    code_file.write_text("a-real-invite-code-of-enough-length\n")

    code = resolved_invite_code(Settings(_env_file=None, aistack_invite_code_file=code_file))

    assert code.get_secret_value() == "a-real-invite-code-of-enough-length"


def test_a_weak_code_in_the_file_is_refused_without_repeating_it(tmp_path):
    code_file = tmp_path / "invite-code.txt"
    code_file.write_text("aaaaaaaaaaaaaaaa\n")

    with pytest.raises(ValueError) as rejection:
        resolved_invite_code(Settings(_env_file=None, aistack_invite_code_file=code_file))

    assert "AISTACK_INVITE_CODE_FILE" in str(rejection.value)
    assert "aaaaaaaaaaaaaaaa" not in str(rejection.value)


def test_a_missing_code_file_is_named(tmp_path):
    with pytest.raises(ValueError, match="AISTACK_INVITE_CODE_FILE"):
        resolved_invite_code(Settings(_env_file=None,
                                      aistack_invite_code_file=tmp_path / "missing.txt"))


def test_a_code_and_a_code_file_together_are_refused(tmp_path):
    code_file = tmp_path / "invite-code.txt"
    code_file.write_text("a-real-invite-code-of-enough-length")

    with pytest.raises(ValueError, match="Keep one"):
        resolved_invite_code(Settings(_env_file=None, aistack_invite_code_file=code_file,
                                      aistack_invite_code="another-real-invite-code-here"))


def test_a_usable_invite_code_passes_startup_validation():
    validate_invite_code(SecretStr("a-real-invite-code-of-enough-length"))


def test_the_configured_invite_code_is_masked_in_any_repr():
    settings = _settings()

    assert "a-real-invite-code-of-enough-length" not in repr(settings)
    assert "a-real-invite-code-of-enough-length" not in str(settings.invite_code)


@pytest.mark.parametrize("url", ["postgresql://u:abc@h/d", "postgresql://h/d?password=abc"])
def test_database_credentials_are_hidden_in_settings_errors_and_repr(url):
    with pytest.raises(ValidationError) as rejection:
        Settings(_env_file=None, database_url=url, aistack_port=0)
    assert "aistack_port" in str(rejection.value)
    assert "abc" not in str(rejection.value)
    settings = _settings(database_url=url)
    assert "abc" not in repr(settings)
    assert settings.database_url == url


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


def test_the_public_url_is_unset_by_default():
    assert _settings().public_url is None


@pytest.mark.parametrize(("configured", "stored"), [
    ("https://aistack.example.com", "https://aistack.example.com"),
    ("https://aistack.example.com/", "https://aistack.example.com"),
    ("  http://10.0.0.5:8000  ", "http://10.0.0.5:8000"),
    ("", None),
])
def test_the_public_url_is_stored_without_a_trailing_slash(configured, stored):
    assert _settings(aistack_public_url=configured).public_url == stored


@pytest.mark.parametrize("configured", ["aistack.example.com", "ftp://aistack.example.com"])
def test_a_public_url_without_an_http_scheme_is_rejected(configured):
    with pytest.raises(ValidationError, match="AISTACK_PUBLIC_URL"):
        _settings(aistack_public_url=configured)


@pytest.mark.parametrize("configured", [
    "https://aistack.example.com; rm -rf ~",
    "https://aistack.example.com$(id)",
    "https://user:password@aistack.example.com",
    "https://aistack.example.com/?next=x",
    "https://aistack example.com",
    'https://aistack.example.com" --header "x',
])
def test_a_public_url_that_is_not_a_plain_address_is_rejected(configured):
    """It is pasted into a shell command, exactly like an address taken from a request."""
    with pytest.raises(ValidationError, match="AISTACK_PUBLIC_URL"):
        _settings(aistack_public_url=configured)


@pytest.mark.parametrize("configured", [
    "https://aistack.example.com",
    "http://10.0.0.5:8000",
    "http://[::1]:8000",
    "https://example.com/aistack",
    "http://aistack.tailnet-name.ts.net:8000",
])
def test_an_ordinary_public_url_is_accepted(configured):
    assert _settings(aistack_public_url=configured).public_url == configured


def test_a_library_lives_in_one_place():
    from aistack.bootstrap.configuration.settings.settings_config import LocalSettings

    both = LocalSettings(aistack_library_repo="maria/skills",
                         aistack_database_url="postgresql://x@y/z")
    with pytest.raises(ValueError, match="not both"):
        both.library_url()


@pytest.fixture(name="local")
def local_fixture(tmp_path, monkeypatch):
    """LocalSettings as a command builds them, from a clean environment."""
    from aistack.bootstrap.configuration.settings.settings_config import LocalSettings

    for variable in ("AISTACK_LIBRARY_REPO", "AISTACK_DATABASE_URL"):
        monkeypatch.delenv(variable, raising=False)

    def local(**place):
        return LocalSettings(aistack_home=tmp_path, **place)

    return local


def test_the_agents_place_is_recorded_and_found_without_settings(local, tmp_path):
    local(aistack_library_repo="maria/aistack-library").resolved(record=True)

    found = local().resolved(record=False)
    assert found.library_repo == "maria/aistack-library"
    assert "password" not in (tmp_path / "library.toml").read_text()


def test_a_database_address_is_never_written_down(local, tmp_path):
    local(aistack_database_url="postgresql+psycopg://maria:s3cret@db.neon.tech/skills"
          ).resolved(record=True)

    assert "s3cret" not in (tmp_path / "library.toml").read_text()
    with pytest.raises(ValueError, match="lives in the PostgreSQL database skills at "
                                         "db.neon.tech. Set AISTACK_DATABASE_URL"):
        local().resolved(record=False)
    # Given the address again, the command runs.
    assert local(aistack_database_url="postgresql://maria:s3cret@db.neon.tech/skills"
                 ).resolved(record=False).database_url


def test_a_command_given_another_place_names_both_and_opens_neither(local):
    local(aistack_library_repo="maria/aistack-library").resolved(record=True)

    with pytest.raises(ValueError) as refused:
        local(aistack_library_repo="maria/other").resolved(record=False)
    assert "maria/aistack-library" in str(refused.value)
    assert "maria/other" in str(refused.value)


def test_the_agent_moving_its_library_moves_the_record(local):
    local(aistack_library_repo="maria/aistack-library").resolved(record=True)
    local(aistack_library_repo="maria/moved").resolved(record=True)

    assert local().resolved(record=False).library_repo == "maria/moved"


def test_a_computer_with_no_place_set_keeps_its_library_here(local, tmp_path):
    assert local().resolved(record=True).library_url().endswith("/aistack.db")
    assert local().resolved(record=False).library_repo is None
    assert 'kind = "this_computer"' in (tmp_path / "library.toml").read_text()


@pytest.mark.parametrize("content", ["kind = ", 'kind = "ftp"', "kind = 3", b"\xff\xfe"])
def test_a_garbled_record_is_named_not_guessed(local, tmp_path, content):
    file = tmp_path / "library.toml"
    if isinstance(content, bytes):
        file.write_bytes(content)
    else:
        file.write_text(content)
    with pytest.raises(ValueError, match="library.toml"):
        local().resolved(record=False)


def test_the_agents_start_rewrites_a_garbled_record(local, tmp_path):
    (tmp_path / "library.toml").write_text("kind = ")
    local(aistack_library_repo="maria/aistack-library").resolved(record=True)

    assert local().resolved(record=False).library_repo == "maria/aistack-library"


def test_a_sqlite_file_named_by_the_agent_is_found_again(local, tmp_path):
    library = tmp_path / "elsewhere.db"
    local(aistack_database_url=f"sqlite:///{library}").resolved(record=True)

    assert local().resolved(record=False).library_url() == f"sqlite:///{library}"
