import logging
from collections.abc import Awaitable, Callable
from functools import wraps
from time import perf_counter
from traceback import format_exc

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from aistack.commons.exceptions import (
    AIStackError,
    Conflict,
    InvalidTicket,
    NotFound,
    ValidationError,
)
from aistack.commons.text import sanitized

# The status is for curl's exit code and for anyone reading a proxy log. The agent reads the
# sentence in the body, which is the same one a ToolError would have carried.
_STATUS_CODES: dict[type[AIStackError], int] = {
    ValidationError: 400,
    InvalidTicket: 403,
    NotFound: 404,
    Conflict: 409,
}

RouteHandler = Callable[[Request], Awaitable[Response]]


def handle_route_errors(func: RouteHandler) -> RouteHandler:
    """The transfer routes' counterpart to `handle_mcp_errors`.

    A domain rejection becomes `{"error": <message>}`; anything else is logged with an escaped
    traceback and masked. Neither path logs the request URL, which contains the ticket.
    """
    route_logger = logging.getLogger(func.__module__)

    @wraps(func)
    async def wrapper(request: Request) -> Response:
        started_at = perf_counter()
        try:
            return await func(request)
        except AIStackError as error:
            route_logger.info(_failure_message(func.__name__, error.message, started_at))
            return error_response(error.message, _STATUS_CODES.get(type(error), 400))
        except Exception:
            # logger.exception() would append the raw exception chain after our escaped text.
            route_logger.error(_failure_message(func.__name__, format_exc(), started_at))
            return error_response(f"{func.__name__} failed unexpectedly.", 500)

    return wrapper


def error_response(message: str, status_code: int) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status_code)


def _failure_message(route_name: str, error_message: str, started_at: float) -> str:
    return (f"{route_name} failed. Error: '{sanitized(error_message)}'. "
            f"Elapsed: '{(perf_counter() - started_at) * 1000:.0f}ms'.")
