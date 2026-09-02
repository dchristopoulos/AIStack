import asyncio
import logging
from time import perf_counter

from fastmcp.server.auth import AccessToken, TokenVerifier
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from aistack.db.models.machine import Machine
from aistack.mcp.auth.scopes import BOOTSTRAP_SCOPE, MACHINE_SCOPE
from aistack.services.token_service import hash_token, matches_invite_code

logger = logging.getLogger(__name__)


class AIStackTokenVerifier(TokenVerifier):
    """Resolves a bearer token to one of the two AIStack principals.

    Runs before tool dispatch, so an invalid bearer never reaches a tool. The claims it
    returns carry `machine_id` and `user_id`, which means no tool re-queries identity.
    """

    def __init__(self, invite_code: SecretStr, session_factory: sessionmaker[Session]):
        super().__init__()
        self._invite_code = invite_code
        self._session_factory = session_factory

    async def verify_token(self, token: str) -> AccessToken | None:
        """Verify a bearer. Returns None for anything unrecognized.

        FastMCP forces an async signature here, so the one blocking database call is pushed to
        a thread rather than stalling the event loop for every other in-flight request
        (ADR-0005 covers tools; this is the one place that cannot be a plain `def`).
        """
        started_at = perf_counter()

        if matches_invite_code(token, self._invite_code):
            # Debug, not info: this runs on every request of every session, and a
            # successful authentication is the unremarkable case. Rejections stay at info.
            logger.debug(f"Bearer authenticated. Principal: 'bootstrap'. "
                        f"Elapsed: '{(perf_counter() - started_at) * 1000:.0f}ms'.")
            return AccessToken(token=token, client_id="bootstrap", scopes=[BOOTSTRAP_SCOPE])

        machine = await asyncio.to_thread(self._find_machine, hash_token(token))
        if machine is None:
            # The presented bearer is deliberately absent from this line and from the 401 that
            # follows it: a bad token in a log is still a token, and the next one might be good.
            logger.info(f"Bearer rejected: not the invite code and no machine holds it. "
                        f"Elapsed: '{(perf_counter() - started_at) * 1000:.0f}ms'.")
            return None

        logger.debug(f"Bearer authenticated. Principal: 'machine'. "
                    f"Machine: '{machine.machine_id}'. User: '{machine.user_id}'. "
                    f"Elapsed: '{(perf_counter() - started_at) * 1000:.0f}ms'.")
        return AccessToken(
            token=token,
            client_id=str(machine.machine_id),
            scopes=[MACHINE_SCOPE],
            claims={"machine_id": str(machine.machine_id), "user_id": str(machine.user_id)},
        )

    def _find_machine(self, token_hash: str) -> Machine | None:
        """One indexed lookup on the unique token_hash — nothing is compared in Python.

        The single place outside a tool that opens its own session: verification runs before
        tool dispatch, so there is no tool transaction to join.
        """
        with self._session_factory() as session:
            return session.scalar(select(Machine).where(Machine.token_hash == token_hash))
