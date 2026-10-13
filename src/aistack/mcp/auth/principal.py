import uuid
from dataclasses import dataclass

from fastmcp.server.dependencies import get_access_token


@dataclass(frozen=True)
class MachinePrincipal:
    """The registered machine making this call, and the user it belongs to."""

    machine_id: uuid.UUID
    user_id: uuid.UUID


def current_machine() -> MachinePrincipal:
    """Read the caller from the verified bearer's claims.

    The token verifier resolved both ids before dispatch, so a tool never queries identity and
    never takes it as an argument. Only machine-scope tools may call this: the bootstrap
    principal carries no claims, and the KeyError that follows is masked as a server fault,
    which is what calling it from an onboarding tool would be.
    """
    claims = get_access_token().claims
    return MachinePrincipal(
        machine_id=uuid.UUID(claims["machine_id"]),
        user_id=uuid.UUID(claims["user_id"]),
    )
