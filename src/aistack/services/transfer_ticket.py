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

# How much of the minting machine's token hash a ticket carries (ADR-0027). Enough that a
# rotated token never matches by chance; the whole hash would only be a longer cookie.
TOKEN_PREFIX_LENGTH = 16


def token_prefix(token_hash: str) -> str:
    """What a ticket says about the token of the machine that minted it."""
    return token_hash[:TOKEN_PREFIX_LENGTH]


@dataclass(frozen=True)
class UploadTicket:
    """Permission for one machine to upload one named skill, from one harness."""

    machine_id: uuid.UUID
    user_id: uuid.UUID
    # The minting machine's token, so a rotation voids the URL (ADR-0027).
    token_prefix: str
    skill_name: str
    origin: str | None
    harness: Harness


@dataclass(frozen=True)
class DownloadTicket:
    """Permission for one machine to download one exact revision."""

    machine_id: uuid.UUID
    token_prefix: str
    skill_version_id: uuid.UUID


@dataclass(frozen=True)
class DashboardHolder:
    """Who a dashboard link or session signs in: a user, through the machine whose token
    asked for it. The session lasts only while that machine holds that token (ADR-0027)."""

    user_id: uuid.UUID
    machine_id: uuid.UUID
    token_prefix: str


class _SpentIds:
    """Ticket ids refused from now until the ticket would have expired anyway.

    In memory, like the key: a restart forgets them, and voids every ticket they name.
    """

    def __init__(self):
        self._until: dict[str, float] = {}
        self._lock = threading.Lock()

    def spend(self, ticket_id: str, expires_at: float) -> bool:
        """Remember `ticket_id`; False when it was already spent."""
        now = time.time()
        with self._lock:
            # Forgotten once expired, when the signature check refuses them anyway.
            self._until = {spent: until for spent, until in self._until.items() if until > now}
            if ticket_id in self._until:
                return False
            self._until[ticket_id] = expires_at
            return True

    def __contains__(self, ticket_id: str) -> bool:
        with self._lock:
            return ticket_id in self._until


class TicketSigner:
    """Mints and verifies tickets with one in-memory key."""

    def __init__(self, key: bytes, lifetime_seconds: int = TICKET_LIFETIME_SECONDS):
        self._key = key
        self._lifetime_seconds = lifetime_seconds
        self._used_links = _SpentIds()
        self._ended_sessions = _SpentIds()

    def sign_upload(self, ticket: UploadTicket) -> str:
        return self._signed(_UPLOAD_AUDIENCE, ticket.machine_id, {
            "user_id": str(ticket.user_id),
            "tkh": ticket.token_prefix,
            "skill_name": ticket.skill_name,
            "origin": ticket.origin,
            "harness": ticket.harness.value,
        })

    def sign_download(self, ticket: DownloadTicket) -> str:
        return self._signed(_DOWNLOAD_AUDIENCE, ticket.machine_id, {
            "tkh": ticket.token_prefix,
            "skill_version_id": str(ticket.skill_version_id),
        })

    def verified_upload(self, token: str) -> UploadTicket:
        claims = self._verified(token, _UPLOAD_AUDIENCE, retry_with="push_skill")
        try:
            return UploadTicket(
                machine_id=uuid.UUID(claims["sub"]),
                user_id=uuid.UUID(claims["user_id"]),
                token_prefix=_text(claims["tkh"]),
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
                token_prefix=_text(claims["tkh"]),
                skill_version_id=uuid.UUID(claims["skill_version_id"]),
            )
        except (KeyError, ValueError, TypeError) as error:
            raise _not_valid("get_skill") from error

    def sign_dashboard_link(self, holder: DashboardHolder) -> str:
        """A link that signs a browser in as `holder`, once, within a few minutes
        (ADR-0017)."""
        return self._signed_holder(_DASHBOARD_LINK_AUDIENCE, holder,
                                   DASHBOARD_LINK_LIFETIME_SECONDS)

    def verified_dashboard_link(self, token: str) -> DashboardHolder:
        """The link's holder, the first time it is used. A link copied from a chat log or a
        browser's history afterwards signs nobody in."""
        holder, link_id, expires_at = self._verified_holder(token, _DASHBOARD_LINK_AUDIENCE)
        if not self._used_links.spend(link_id, expires_at):
            raise _invalid_dashboard_link()
        return holder

    def sign_dashboard_session(self, holder: DashboardHolder) -> str:
        """The cookie a signed-in browser presents. A server restart signs everyone out."""
        return self._signed_holder(_DASHBOARD_SESSION_AUDIENCE, holder,
                                   DASHBOARD_SESSION_LIFETIME_SECONDS)

    def verified_dashboard_session(self, token: str) -> DashboardHolder:
        holder, session_id, _ = self._verified_holder(token, _DASHBOARD_SESSION_AUDIENCE)
        if session_id in self._ended_sessions:
            raise _invalid_dashboard_link()
        return holder

    def end_dashboard_session(self, token: str) -> None:
        """Sign a session out for good, wherever its cookie was copied to. A session that is
        not valid has nothing to end."""
        try:
            _, session_id, expires_at = self._verified_holder(token,
                                                              _DASHBOARD_SESSION_AUDIENCE)
        except InvalidTicket:
            return
        self._ended_sessions.spend(session_id, expires_at)

    def _signed_holder(self, audience: str, holder: DashboardHolder,
                       lifetime_seconds: int) -> str:
        # Each link and session has an id, so one can be spent or ended on its own.
        return self._signed(audience, holder.user_id, {
            "jti": str(uuid.uuid4()),
            "mid": str(holder.machine_id),
            "tkh": holder.token_prefix,
        }, lifetime_seconds)

    def _verified_holder(self, token: str,
                         audience: str) -> tuple[DashboardHolder, str, float]:
        """The holder a link or session names, its id, and when it expires."""
        try:
            claims = jwt.decode(token, self._key, algorithms=[_ALGORITHM], audience=audience,
                                options={"require": ["exp", "aud", "sub", "jti", "mid", "tkh"]})
            holder = DashboardHolder(user_id=uuid.UUID(claims["sub"]),
                                     machine_id=uuid.UUID(claims["mid"]),
                                     token_prefix=_text(claims["tkh"]))
            return holder, _text(claims["jti"]), float(claims["exp"])
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


def _text(claim: object) -> str:
    if not isinstance(claim, str):
        raise TypeError("A ticket claim that should be text is not.")
    return claim


def _not_valid(retry_with: str) -> InvalidTicket:
    """One sentence for every way a ticket can be wrong, so the reason is never a hint."""
    return InvalidTicket(
        "This transfer URL is not valid. Use the URL exactly as the tool returned it, or "
        f"call {retry_with} again for a fresh one."
    )


def _invalid_dashboard_link() -> InvalidTicket:
    return InvalidTicket("This dashboard link is not valid, has been used, or has expired. "
                         "Ask your agent to \"open my aistack dashboard\" for a new one.")
