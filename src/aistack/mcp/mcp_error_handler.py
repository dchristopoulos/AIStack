import logging
from functools import wraps
from inspect import Signature, signature
from time import perf_counter
from typing import Any, Callable, TypeVar

from fastmcp.exceptions import ToolError

from aistack.commons.exceptions import AIStackError

T = TypeVar("T")

# The arguments worth naming in a failure line, with the field labels the success lines use,
# so one log filter returns both. Secrets are never listed here — a tool that takes one would
# otherwise have it written to the log by a decorator nobody remembered to check.
SUBJECT_ARGUMENTS = (("username", "Username"),
                     ("machine_name", "Machine"),
                     ("name", "Name"),
                     ("os", "OS"))


def handle_mcp_errors() -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Convert domain exceptions to ToolError, in the one place that does it.

    A tool never returns an error payload: at the protocol level that reads as success, and an
    agent has to be told to look inside the result to notice. Raising is the only signal an
    MCP client treats as failure.

    Anything that is not an `AIStackError` is a server fault. Its message is replaced rather
    than forwarded, because the caller of a failed database call has no use for the SQL and no
    business seeing it — `mask_error_details=True` on the server is the second layer of that.
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        # The tool's own logger and function name, so a filter on "onboarding.join" returns
        # its failures alongside its successes.
        tool_logger = logging.getLogger(func.__module__)
        tool_signature = signature(func)

        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            started_at = perf_counter()
            try:
                return func(*args, **kwargs)
            except AIStackError as error:
                # A rejection is an expected, caller-visible outcome, not a server fault, so it
                # is logged at info and its message is handed to the caller verbatim.
                tool_logger.info(_failure_message(func.__name__, tool_signature, args, kwargs,
                                                  error.message, started_at))
                raise ToolError(error.message) from error
            except Exception as error:  # noqa: BLE001  # pylint: disable=broad-exception-caught
                tool_logger.exception(_failure_message(func.__name__, tool_signature, args,
                                                       kwargs, str(error), started_at))
                raise ToolError(f"{func.__name__} failed unexpectedly.") from error

        return wrapper

    return decorator


def _failure_message(tool_name: str,
                     tool_signature: Signature,
                     args: tuple[Any, ...],
                     kwargs: dict[str, Any],
                     error_message: str,
                     started_at: float) -> str:
    """Render a failure in the same field grammar as the tool's own completion line.

    A failure that says only "join failed" cannot be matched to the call that produced it, so
    the arguments that determined the outcome are named even when the exception did not.
    """
    try:
        arguments = tool_signature.bind_partial(*args, **kwargs).arguments
    except TypeError:  # A call that does not even match the signature has nothing to name.
        arguments = {}

    subject = "".join(f"{label}: '{arguments[name]}'. "
                      for name, label in SUBJECT_ARGUMENTS if name in arguments)
    return (f"{tool_name} failed. {subject}"
            f"Error: '{error_message}'. "
            f"Elapsed: '{(perf_counter() - started_at) * 1000:.0f}ms'.")
