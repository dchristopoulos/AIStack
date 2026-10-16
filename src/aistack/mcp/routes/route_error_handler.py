import logging
from collections.abc import Awaitable, Callable
from functools import wraps
from time import perf_counter
from traceback import format_exc

from starlette.requests import ClientDisconnect, Request
from starlette.responses import JSONResponse, Response

from aistack.commons import metrics
from aistack.commons.exceptions import (
    AIStackError,
    Busy,
    Conflict,
    InvalidTicket,
    NotFound,
    SignedOut,
    TooManyAttempts,
    ValidationError,
)
from aistack.commons.text import bounded_failure

# The status is for curl's exit code and for anyone reading a proxy log. The agent reads the
# sentence in the body, which is the same one a ToolError would have carried.
_STATUS_CODES: dict[type[AIStackError], int] = {
    ValidationError: 400,
    SignedOut: 401,
    InvalidTicket: 403,
    NotFound: 404,
    Conflict: 409,
    Busy: 503,
    TooManyAttempts: 429,
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
            response = await func(request)
        except AIStackError as error:
            metrics.count("route", func.__name__, "refused")
            route_logger.info(_failure_message(func.__name__, error.message, started_at))
            return error_response(error.message, _STATUS_CODES.get(type(error), 400))
        except ClientDisconnect:
            metrics.count("route", func.__name__, "disconnected")
            # The client hung up before its body arrived: a flaky network, not a fault here.
            # Nothing was stored, and nobody is left to read a response.
            route_logger.info(f"{func.__name__}: the client hung up before its request "
                              "finished. Nothing was changed.")
            return Response(status_code=400)
        except Exception:
            metrics.count("route", func.__name__, "error")
            # logger.exception() would append the raw exception chain after our escaped text.
            route_logger.error(_failure_message(func.__name__, format_exc(), started_at))
            # The page shows this sentence, so it names no function; the log has the detail.
            return error_response("Something went wrong on the server. Its log says what.",
                                  500)
        metrics.count("route", func.__name__, "ok")
        return response

    return wrapper


def error_response(message: str, status_code: int) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status_code)


def _failure_message(route_name: str, error_message: str, started_at: float) -> str:
    return (f"{route_name} failed. Error: '{bounded_failure(error_message)}'. "
            f"Elapsed: '{(perf_counter() - started_at) * 1000:.0f}ms'.")
