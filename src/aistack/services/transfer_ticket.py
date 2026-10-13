"""Tickets: the signed, short-lived credential inside a transfer URL (ADR-0010).

A ticket is a JWT signed with HS256. Nothing about the format is custom; PyJWT checks the
signature in constant time and enforces the expiry, and this module only decides what a
ticket says and turns a failed check into a sentence the agent can act on.
"""

import time
import uuid
from dataclasses import dataclass

import jwt

from aistack.commons.exceptions import InvalidTicket

TICKET_LIFETIME_SECONDS = 300
SIGNING_KEY_BYTES = 32

_ALGORITHM = "HS256"
# The audience is the purpose. A download ticket presented to the upload route fails here,
# before any claim is read.
_UPLOAD_AUDIENCE = "aistack:upload"
_DOWNLOAD_AUDIENCE = "aistack:download"


@dataclass(frozen=True)
class UploadTicket:
    """Permission for one machine to upload one named skill."""

    machine_id: uuid.UUID
    user_id: uuid.UUID
    skill_name: str
    origin: str | None


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

    def sign_upload(self, ticket: UploadTicket) -> str:
        return self._signed(_UPLOAD_AUDIENCE, ticket.machine_id, {
            "user_id": str(ticket.user_id),
            "skill_name": ticket.skill_name,
            "origin": ticket.origin,
        })

    def sign_download(self, ticket: DownloadTicket) -> str:
        return self._signed(_DOWNLOAD_AUDIENCE, ticket.machine_id, {
            "skill_version_id": str(ticket.skill_version_id),
        })

    def verified_upload(self, token: str) -> UploadTicket:
        claims = self._verified(token, _UPLOAD_AUDIENCE, retry_with="push_skill")
        return UploadTicket(
            machine_id=uuid.UUID(claims["sub"]),
            user_id=uuid.UUID(claims["user_id"]),
            skill_name=claims["skill_name"],
            origin=claims["origin"],
        )

    def verified_download(self, token: str) -> DownloadTicket:
        claims = self._verified(token, _DOWNLOAD_AUDIENCE, retry_with="get_skill")
        return DownloadTicket(
            machine_id=uuid.UUID(claims["sub"]),
            skill_version_id=uuid.UUID(claims["skill_version_id"]),
        )

    def _signed(self, audience: str, machine_id: uuid.UUID, claims: dict) -> str:
        return jwt.encode(
            {
                "aud": audience,
                "sub": str(machine_id),
                "exp": int(time.time()) + self._lifetime_seconds,
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
            raise InvalidTicket(
                "This transfer URL is not valid. Use the URL exactly as the tool returned "
                f"it, or call {retry_with} again for a fresh one."
            ) from error
