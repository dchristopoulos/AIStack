import logging

import pytest
from fastmcp.exceptions import ToolError

from aistack.commons.exceptions import AIStackError, Conflict, ValidationError
from aistack.mcp.mcp_error_handler import handle_mcp_errors


@handle_mcp_errors
def sample_tool(username: str, os: str, secret: str = "aist_should-never-be-logged"):
    if username == "taken":
        raise Conflict(f"Username '{username}' is already taken.")
    if os == "SOLARIS":
        raise ValidationError(f"os must be one of MACOS, WINDOWS, LINUX. Received: '{os}'.")
    if username == "explode":
        raise RuntimeError("connection to 'db-host:5432' as user 'admin' failed")
    return {"username": username}


@pytest.mark.parametrize(("username", "os", "expected"), [
    ("taken", "LINUX", "Username 'taken' is already taken."),
    ("free", "SOLARIS", "os must be one of MACOS, WINDOWS, LINUX. Received: 'SOLARIS'."),
])
def test_a_domain_exception_reaches_the_caller_verbatim_as_a_tool_error(username, os, expected):
    with pytest.raises(ToolError) as rejection:
        sample_tool(username, os)

    # Raised, not returned: an error payload reads as success at the protocol level.
    assert str(rejection.value) == expected


def test_an_unexpected_exception_is_masked():
    with pytest.raises(ToolError) as failure:
        sample_tool("explode", "LINUX")

    assert str(failure.value) == "sample_tool failed unexpectedly."
    assert "db-host" not in str(failure.value)
    assert "RuntimeError" not in str(failure.value)


def test_a_rejection_logs_its_message_without_call_arguments(caplog):
    with caplog.at_level(logging.INFO):
        with pytest.raises(ToolError):
            sample_tool("private-username", "SOLARIS", secret="explicit-secret-sentinel")

    logged = caplog.text
    assert "sample_tool failed." in logged
    assert "os must be one of MACOS, WINDOWS, LINUX" in logged
    assert "private-username" not in logged
    assert "Elapsed: '" in logged
    assert "explicit-secret-sentinel" not in logged


def test_a_domain_exception_is_never_logged_as_a_server_fault(caplog):
    with caplog.at_level(logging.INFO):
        with pytest.raises(ToolError):
            sample_tool("taken", "LINUX")

    assert [record.levelname for record in caplog.records] == ["INFO"]
    assert "Traceback" not in caplog.text


def test_the_masked_failure_still_logs_the_real_cause_for_the_operator(caplog):
    with caplog.at_level(logging.ERROR):
        with pytest.raises(ToolError):
            sample_tool("explode", "LINUX")

    # Masked for the caller, fully visible in the server log — otherwise a bug is unreportable.
    assert "db-host:5432" in caplog.text
    assert "Traceback" in caplog.text


def test_every_domain_exception_type_is_handled_by_the_base_class():
    assert issubclass(Conflict, AIStackError)
    assert issubclass(ValidationError, AIStackError)


def test_the_complete_exception_chain_cannot_forge_log_lines(caplog):
    @handle_mcp_errors
    def chained_failure():
        try:
            raise ValueError("cause\nFORGED-CAUSE\x1b[2J")
        except ValueError as error:
            raise RuntimeError("outer\r\nFORGED-OUTER") from error

    with caplog.at_level(logging.ERROR):
        with pytest.raises(ToolError):
            chained_failure()

    assert len(caplog.records) == 1
    rendered = logging.Formatter().format(caplog.records[0])
    assert "\n" not in rendered and "\r" not in rendered and "\x1b" not in rendered
    assert "\\nFORGED-CAUSE" in rendered
    assert "\\r\\nFORGED-OUTER" in rendered
    assert "Traceback" in rendered and "direct cause" in rendered
