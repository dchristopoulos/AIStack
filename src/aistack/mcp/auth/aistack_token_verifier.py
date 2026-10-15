import asyncio
import logging
from time import perf_counter

from fastmcp.server.auth import AccessToken, TokenVerifier
from fastmcp.server.dependencies import get_http_request
from pydantic import Field, SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from aistack.db.models.machine import Machine
from aistack.mcp.auth.failure_limiter import FailureLimiter, client_address, note_failure
from aistack.mcp.auth.scopes import BOOTSTRAP_SCOPE, MACHINE_SCOPE
from aistack.services import team_service
from aistack.services.token_service import TEAM_INVITE_PREFIX, hash_token, matches_invite_code
from aistack.services.transfer_ticket import token_prefix

logger = logging.getLogger(__name__)


class AIStackAccessToken(AccessToken):
    """Keep the SDK token contract without exposing the bearer in object representations."""

    token: str = Field(repr=False)


class AIStackTokenVerifier(TokenVerifier):
    """Resolve the bearer before tool dispatch.

    Machine claims carry machine_id, user_id, and the token's prefix so tools need no
    identity lookup, and the tickets they mint die with the token.
    """

    def __init__(self, invite_code: SecretStr, session_factory: sessionmaker[Session],
                 failure_limiter: FailureLimiter):
        super().__init__()
        self._invite_code = invite_code
        self._session_factory = session_factory
        self._failure_limiter = failure_limiter

    async def verify_token(self, token: str) -> AccessToken | None:
        """Return a scoped principal, or None when the bearer is unrecognized."""
        started_at = perf_counter()

        if matches_invite_code(token, self._invite_code):
            logger.debug(
                "Bearer authenticated. Principal: 'bootstrap'. "
                f"Elapsed: '{(perf_counter() - started_at) * 1000:.0f}ms'."
            )
            return AIStackAccessToken(token=token, client_id="bootstrap", scopes=[BOOTSTRAP_SCOPE])

        if token.startswith(TEAM_INVITE_PREFIX):
            # A team's invite code reaches `join` and nothing else (ADR-0019). The claim says
            # only which kind of invite this is: `join` resolves the team again in its own
            # transaction, so no team or user identity rides on a bearer that is shared.
            invited = await asyncio.to_thread(self._is_team_invite, token)
            if invited:
                logger.debug(
                    "Bearer authenticated. Principal: 'bootstrap'. Invite: 'team'. "
                    f"Elapsed: '{(perf_counter() - started_at) * 1000:.0f}ms'."
                )
                return AIStackAccessToken(token=token, client_id="bootstrap",
                                          scopes=[BOOTSTRAP_SCOPE], claims={"invite": "team"})

        # FastMCP requires async here; keep the blocking driver off the event loop.
        machine = await asyncio.to_thread(self._find_machine, hash_token(token))
        if machine is None:
            # The address is what an operator, or fail2ban, can act on (OPERATING.md). The
            # bearer is never written: a near-miss of a real one is still a secret.
            address = _client_address()
            logger.info(
                "Bearer rejected: not an invite code that works and no machine holds it. "
                f"Client: '{address}'. "
                f"Elapsed: '{(perf_counter() - started_at) * 1000:.0f}ms'."
            )
            note_failure(self._failure_limiter, address, "bearer")
            return None

        logger.debug(
            "Bearer authenticated. Principal: 'machine'. "
            f"Machine: '{machine.machine_id}'. User: '{machine.user_id}'. "
            f"Elapsed: '{(perf_counter() - started_at) * 1000:.0f}ms'."
        )
        return AIStackAccessToken(
            token=token,
            client_id=str(machine.machine_id),
            scopes=[MACHINE_SCOPE],
            claims={"machine_id": str(machine.machine_id), "user_id": str(machine.user_id),
                    "token_prefix": token_prefix(machine.token_hash)},
        )

    def _is_team_invite(self, code: str) -> bool:
        """An open invite, looked up through its hash's unique index like a machine token."""
        with self._session_factory() as session:
            return team_service.is_open_invite(session, code)

    def _find_machine(self, token_hash: str) -> Machine | None:
        """Look up the token hash through its unique index.

        Auth owns a short read session because no tool transaction exists yet.
        """
        with self._session_factory() as session:
            return session.scalar(select(Machine).where(Machine.token_hash == token_hash))


def _client_address() -> str:
    """The rejected request's address; FastMCP keeps the request for the verifier's caller."""
    try:
        return client_address(get_http_request())
    except RuntimeError:
        return client_address(None)
