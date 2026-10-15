"""Count failed credentials per client address, and turn a guessing run away early.

Nothing else stands between a client and an unlimited number of guesses at the server's
invite code, a team's invite code, a dashboard link, or a machine token. Machine tokens and
the codes the server makes are far too long to guess; the server's own code is chosen by the
operator, and each refusal costs a database lookup and a log line. Past the limit, a request
from that address is answered 429 before it reaches the database or the log.

The state is in memory, which is enough because a server is one process (OPERATING.md): a
restart forgets it, as it forgets dashboard sessions.
"""

import json
import logging
import math
import threading
import time
from collections import OrderedDict, deque
from collections.abc import Callable

from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from aistack.commons.text import loggable

logger = logging.getLogger(__name__)

# Twenty refusals a minute is far more than a person mistyping or an agent retrying with a
# replaced token, and a guessing run reaches it in a fraction of a second.
FAILURE_LIMIT = 20
FAILURE_WINDOW_SECONDS = 60

# A refused `join` is not a wrong credential: the code worked and the name was taken. Each one
# still answers whether a username or team name exists, so a code is good for a few (SEC-08).
REFUSED_JOIN_LIMIT = 5
REFUSED_JOIN_WINDOW_SECONDS = 3600

# The most addresses remembered at once. Past it the oldest is forgotten, so a client cycling
# through addresses costs memory up to this bound and no further.
MAX_TRACKED_KEYS = 10_000


class FailureLimiter:
    """A sliding window of failures per key; a key with `limit` in the window waits."""

    def __init__(self, limit: int, window_seconds: float,
                 clock: Callable[[], float] = time.monotonic):
        self._limit = limit
        self._window = window_seconds
        self._clock = clock
        self._failures: OrderedDict[str, deque[float]] = OrderedDict()
        # Called from the event loop and from worker threads alike.
        self._lock = threading.Lock()

    def retry_after(self, key: str) -> int | None:
        """Seconds until `key` may try again, or None when it may now."""
        with self._lock:
            failures = self._current(key)
            if failures is None or len(failures) < self._limit:
                return None
            return max(1, math.ceil(failures[0] + self._window - self._clock()))

    def record(self, key: str) -> bool:
        """Count one failure for `key`. True when this one reached the limit."""
        with self._lock:
            failures = self._current(key)
            if failures is None:
                failures = self._failures[key] = deque()
                while len(self._failures) > MAX_TRACKED_KEYS:
                    self._failures.popitem(last=False)
            failures.append(self._clock())
            self._failures.move_to_end(key)
            return len(failures) == self._limit

    def _current(self, key: str) -> deque[float] | None:
        failures = self._failures.get(key)
        if failures is None:
            return None
        cutoff = self._clock() - self._window
        while failures and failures[0] <= cutoff:
            failures.popleft()
        if not failures:
            del self._failures[key]
            return None
        return failures


def client_address(request: Request | None) -> str:
    """The address a request came from, as uvicorn resolved it.

    uvicorn reads X-Forwarded-For only from the addresses in FORWARDED_ALLOW_IPS, so behind a
    proxy this is the real client once the operator names the proxy (OPERATING.md).
    """
    if request is None or request.client is None:
        return "unknown"
    return loggable(request.client.host)


def note_failure(limiter: FailureLimiter, address: str, what: str) -> None:
    """Record a refused credential and say so once the address reaches the limit.

    Each refusal is logged by its caller with the address. This adds one line per address per
    window, when the address is turned away, so a flood costs the log a bounded amount.
    """
    if limiter.record(address):
        logger.warning(f"Client throttled: {FAILURE_LIMIT} refused credentials within "
                       f"{FAILURE_WINDOW_SECONDS}s. Client: '{address}'. Last: '{what}'.")


# What a rejected bearer is told, instead of FastMCP's advice to re-register, which AIStack
# has no way to do (SEC-14). It never repeats the bearer.
REJECTED_BEARER = ("This bearer is not an invite code that works or a machine token this "
                   "server knows. A computer that was connected before may have had its "
                   "token replaced or been removed: ask whoever runs the server, then "
                   "reconnect with the new one.")

# Answers nothing a credential could reach, so a throttled address can still be told apart
# from a server that is down.
_UNGUARDED_PATHS = frozenset({"/health"})


class CredentialGuard:
    """The HTTP app, behind the limiter: a throttled address gets 429 before any route runs.

    Every route that checks a credential records its refusals with `note_failure`; this is the
    one place that turns the address away, so no route can forget to. It also gives a rejected
    bearer AIStack's own sentence.
    """

    def __init__(self, app: ASGIApp, limiter: Callable[[], FailureLimiter]):
        self._app = app
        self._limiter = limiter

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] in _UNGUARDED_PATHS:
            await self._app(scope, receive, send)
            return
        wait = self._limiter().retry_after(client_address(Request(scope)))
        if wait is not None:
            await _send_json(send, 429, too_many_refusals(wait),
                             [(b"retry-after", str(wait).encode())])
            return
        await self._app(scope, receive, _rewriting_rejected_bearer(send))


def too_many_refusals(wait: int) -> str:
    return (f"Too many refused credentials came from this address, so it is turned away for "
            f"{wait} more seconds. Check the token or code being sent, then try again.")


def _rewriting_rejected_bearer(send: Send) -> Send:
    """Replace the body and header of FastMCP's 401 for a bearer it did not accept.

    That 401 is the only response that carries `error="invalid_token"`; a missing header gets
    a bare 401 that clients use to discover authentication, and is left alone.
    """
    rewriting = False

    async def wrapped(message: Message) -> None:
        nonlocal rewriting
        if message["type"] == "http.response.start" and message["status"] == 401:
            headers = dict(message.get("headers", []))
            rewriting = b'error="invalid_token"' in headers.get(b"www-authenticate", b"")
            if rewriting:
                await _send_json(send, 401, REJECTED_BEARER, [(
                    b"www-authenticate",
                    f'Bearer error="invalid_token", error_description="{REJECTED_BEARER}"'.encode(),
                )])
                return
        if rewriting:
            # The original body was replaced whole above.
            return
        await send(message)

    return wrapped


async def _send_json(send: Send, status: int, message: str,
                     headers: list[tuple[bytes, bytes]]) -> None:
    body = json.dumps({"error": message}).encode()
    await send({
        "type": "http.response.start",
        "status": status,
        "headers": [(b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()), *headers],
    })
    await send({"type": "http.response.body", "body": body})
