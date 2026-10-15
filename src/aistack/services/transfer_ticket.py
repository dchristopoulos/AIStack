"""Tickets: the signed, short-lived credential inside a transfer URL (ADR-0010).

A ticket is a JWT signed with HS256. Nothing about the format is custom; PyJWT checks the
signature in constant time and enforces the expiry, and this module only decides what a
ticket says and turns a failed check into a sentence the agent can act on.
"""

import threading
import time
import uuid
from dataclasses import dataclass

import jwt

from aistack.commons.exceptions import InvalidTicket
from aistack.db.models.harness import Harness

TICKET_LIFETIME_SECONDS = 300
SIGNING_KEY_BYTES = 32

# A dashboard link signs a browser in; the session it starts is what the browser keeps.
DASHBOARD_LINK_LIFETIME_SECONDS = 300
DASHBOARD_SESSION_LIFETIME_SECONDS = 8 * 60 * 60

_ALGORITHM = "HS256"
# The audience is the purpose. A download ticket presented to the upload route fails here,
# before any claim is read.
_UPLOAD_AUDIENCE = "aistack:upload"
_DOWNLOAD_AUDIENCE = "aistack:download"
# A link cannot be replayed as a session cookie, nor a cookie as a link.
_DASHBOARD_LINK_AUDIENCE = "aistack:dashboard-link"
_DASHBOARD_SESSION_AUDIENCE = "aistack:dashboard-session"


@dataclass(frozen=True)
class UploadTicket:
    """Permission for one machine to upload one named skill, from one harness."""

    machine_id: uuid.UUID
    user_id: uuid.UUID
    skill_name: str
    origin: str | None
    harness: Harness


@dataclass(frozen=True)
class DownloadTicket:
    """Permission for one machine to download one exact revision."""

    machine_id: uuid.UUID
    skill_version_id: uuid.UUID


class TicketSigner:
    """Mints and verifies tickets with one in-memory key."""

    def __init__(self, key: bytes, lifetime_seconds: int = TICKET_LIFETIME_SECONDS):
        self._key = key
        self._lifetime_seconds = lifetime_seconds
        self._used_links: dict[str, float] = {}
        self._used_links_lock = threading.Lock()

    def sign_upload(self, ticket: UploadTicket) -> str:
        return self._signed(_UPLOAD_AUDIENCE, ticket.machine_id, {
            "user_id": str(ticket.user_id),
            "skill_name": ticket.skill_name,
            "origin": ticket.origin,
            "harness": ticket.harness.value,
        })

    def sign_download(self, ticket: DownloadTicket) -> str:
        return self._signed(_DOWNLOAD_AUDIENCE, ticket.machine_id, {
            "skill_version_id": str(ticket.skill_version_id),
        })

    def verified_upload(self, token: str) -> UploadTicket:
        claims = self._verified(token, _UPLOAD_AUDIENCE, retry_with="push_skill")
        try:
            return UploadTicket(
                machine_id=uuid.UUID(claims["sub"]),
                user_id=uuid.UUID(claims["user_id"]),
                skill_name=claims["skill_name"],
                origin=claims["origin"],
                harness=Harness(claims["harness"]),
            )
        except (KeyError, ValueError, TypeError) as error:
            raise _not_valid("push_skill") from error

    def verified_download(self, token: str) -> DownloadTicket:
        claims = self._verified(token, _DOWNLOAD_AUDIENCE, retry_with="get_skill")
        try:
            return DownloadTicket(
                machine_id=uuid.UUID(claims["sub"]),
                skill_version_id=uuid.UUID(claims["skill_version_id"]),
            )
        except (KeyError, ValueError, TypeError) as error:
            raise _not_valid("get_skill") from error

    def sign_dashboard_link(self, user_id: uuid.UUID) -> str:
        """A link that signs a browser in as `user_id`, once, within a few minutes
        (ADR-0017)."""
        return self._signed(_DASHBOARD_LINK_AUDIENCE, user_id, {"jti": str(uuid.uuid4())},
                            DASHBOARD_LINK_LIFETIME_SECONDS)

    def verified_dashboard_link(self, token: str) -> uuid.UUID:
        """The link's user, the first time it is used. A link copied from a chat log or a
        browser's history afterwards signs nobody in."""
        user_id = self._verified_user(token, _DASHBOARD_LINK_AUDIENCE)
        link_id = jwt.decode(token, options={"verify_signature": False}).get("jti")
        if not isinstance(link_id, str):
            raise _invalid_dashboard_link()
        now = time.time()
        with self._used_links_lock:
            # Forgotten once expired, when the signature check refuses them anyway.
            self._used_links = {used: expires for used, expires in self._used_links.items()
                                if expires > now}
            if link_id in self._used_links:
                raise _invalid_dashboard_link()
            self._used_links[link_id] = now + DASHBOARD_LINK_LIFETIME_SECONDS
        return user_id

    def sign_dashboard_session(self, user_id: uuid.UUID) -> str:
        """The cookie a signed-in browser presents. A server restart signs everyone out."""
        return self._signed(_DASHBOARD_SESSION_AUDIENCE, user_id, {},
                            DASHBOARD_SESSION_LIFETIME_SECONDS)

    def verified_dashboard_session(self, token: str) -> uuid.UUID:
        return self._verified_user(token, _DASHBOARD_SESSION_AUDIENCE)

    def _verified_user(self, token: str, audience: str) -> uuid.UUID:
        try:
            claims = jwt.decode(token, self._key, algorithms=[_ALGORITHM], audience=audience,
                                options={"require": ["exp", "aud", "sub"]})
            return uuid.UUID(claims["sub"])
        except (jwt.InvalidTokenError, KeyError, ValueError, TypeError) as error:
            raise _invalid_dashboard_link() from error

    def _signed(self, audience: str, subject: uuid.UUID, claims: dict,
                lifetime_seconds: int | None = None) -> str:
        return jwt.encode(
            {
                "aud": audience,
                "sub": str(subject),
                "exp": int(time.time()) + (lifetime_seconds or self._lifetime_seconds),
                **claims,
            },
            self._key,
            algorithm=_ALGORITHM,
        )

    def _verified(self, token: str, audience: str, retry_with: str) -> dict:
        """Return the claims of a ticket this server signed, for this purpose, in time.

        The algorithm list is pinned, so a token declaring `alg: none` or an asymmetric
        algorithm is refused rather than verified on its own terms. No message here repeats
        the token: it is a credential, and this is the rejection path.
        """
        try:
            return jwt.decode(
                token,
                self._key,
                algorithms=[_ALGORITHM],
                audience=audience,
                options={"require": ["exp", "aud", "sub"]},
            )
        except jwt.ExpiredSignatureError as error:
            raise InvalidTicket(
                f"This transfer URL has expired; they last {self._lifetime_seconds // 60} "
                f"minutes. Call {retry_with} again for a fresh one."
            ) from error
        except jwt.InvalidTokenError as error:
            raise _not_valid(retry_with) from error


def _not_valid(retry_with: str) -> InvalidTicket:
    """One sentence for every way a ticket can be wrong, so the reason is never a hint."""
    return InvalidTicket(
        "This transfer URL is not valid. Use the URL exactly as the tool returned it, or "
        f"call {retry_with} again for a fresh one."
    )


def _invalid_dashboard_link() -> InvalidTicket:
    return InvalidTicket("This dashboard link is not valid, has been used, or has expired. "
                         "Ask your agent to \"open my aistack dashboard\" for a new one.")
