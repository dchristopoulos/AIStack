import logging
from functools import wraps
from time import perf_counter
from traceback import format_exc
from typing import Callable, ParamSpec, TypeVar

from fastmcp.exceptions import ToolError

from aistack.commons.exceptions import AIStackError
from aistack.commons.text import sanitized

P = ParamSpec("P")
T = TypeVar("T")


def handle_mcp_errors(func: Callable[P, T]) -> Callable[P, T]:
    """Expose domain rejections as ToolError and mask unexpected failures.

    Log no call arguments. Domain messages carry the context intended for the caller.
    """
    tool_logger = logging.getLogger(func.__module__)

    @wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        started_at = perf_counter()
        try:
            return func(*args, **kwargs)
        except AIStackError as error:
            tool_logger.info(_failure_message(func.__name__, error.message, started_at))
            raise ToolError(error.message) from error
        except Exception as error:
            # logger.exception() would append the raw exception chain after our escaped text.
            tool_logger.error(_failure_message(func.__name__, format_exc(), started_at))
            raise ToolError(f"{func.__name__} failed unexpectedly.") from error

    return wrapper


def _failure_message(tool_name: str, error_message: str, started_at: float) -> str:
    return (f"{tool_name} failed. Error: '{sanitized(error_message)}'. "
            f"Elapsed: '{(perf_counter() - started_at) * 1000:.0f}ms'.")
