import asyncio
import logging
from time import perf_counter

from fastmcp.server.auth import AccessToken, TokenVerifier
from pydantic import Field, SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from aistack.db.models.machine import Machine
from aistack.mcp.auth.scopes import BOOTSTRAP_SCOPE, MACHINE_SCOPE
from aistack.services.token_service import hash_token, matches_invite_code

logger = logging.getLogger(__name__)


class AIStackAccessToken(AccessToken):
    """Keep the SDK token contract without exposing the bearer in object representations."""

    token: str = Field(repr=False)


class AIStackTokenVerifier(TokenVerifier):
    """Resolve the bearer before tool dispatch.

    Machine claims carry machine_id and user_id so tools need no identity lookup.
    """

    def __init__(self, invite_code: SecretStr, session_factory: sessionmaker[Session]):
        super().__init__()
        self._invite_code = invite_code
        self._session_factory = session_factory

    async def verify_token(self, token: str) -> AccessToken | None:
        """Return a scoped principal, or None when the bearer is unrecognized."""
        started_at = perf_counter()

        if matches_invite_code(token, self._invite_code):
            logger.debug(
                "Bearer authenticated. Principal: 'bootstrap'. "
                f"Elapsed: '{(perf_counter() - started_at) * 1000:.0f}ms'."
            )
            return AIStackAccessToken(token=token, client_id="bootstrap", scopes=[BOOTSTRAP_SCOPE])

        # FastMCP requires async here; keep the blocking driver off the event loop.
        machine = await asyncio.to_thread(self._find_machine, hash_token(token))
        if machine is None:
            # Rejections must never echo the presented bearer.
            logger.info(
                "Bearer rejected: not the invite code and no machine holds it. "
                f"Elapsed: '{(perf_counter() - started_at) * 1000:.0f}ms'."
            )
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
            claims={"machine_id": str(machine.machine_id), "user_id": str(machine.user_id)},
        )

    def _find_machine(self, token_hash: str) -> Machine | None:
        """Look up the token hash through its unique index.

        Auth owns a short read session because no tool transaction exists yet.
        """
        with self._session_factory() as session:
            return session.scalar(select(Machine).where(Machine.token_hash == token_hash))
