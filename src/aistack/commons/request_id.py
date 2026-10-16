"""A short id per HTTP request, on every log line written while it runs (STD-19).

A contextvar, so it follows the request into the worker thread a tool or route runs in.
"""

import logging
import secrets
from contextvars import ContextVar

current: ContextVar[str] = ContextVar("request_id", default="-")


def new() -> object:
    """Start a request; returns what `end` takes."""
    return current.set(secrets.token_hex(4))


def end(token) -> None:
    current.reset(token)


def install() -> None:
    """Give every log record a `request_id`, '-' outside a request."""
    previous = logging.getLogRecordFactory()
    if getattr(previous, "with_request_id", False):
        return

    def factory(*args, **kwargs) -> logging.LogRecord:
        record = previous(*args, **kwargs)
        record.request_id = current.get()
        return record

    factory.with_request_id = True
    logging.setLogRecordFactory(factory)
