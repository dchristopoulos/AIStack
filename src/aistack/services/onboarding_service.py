import logging
from dataclasses import dataclass, field
from time import perf_counter

from sqlalchemy import exists, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from aistack.commons.exceptions import Conflict, ValidationError
from aistack.commons.text import loggable
from aistack.db.models.machine import MACHINE_NAME_MAX_LENGTH, Machine
from aistack.db.models.operating_system import OperatingSystem
from aistack.db.models.user import USERNAME_MAX_LENGTH, User
from aistack.services.token_service import generate_machine_token, hash_token

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class JoinedMachine:
    """Persisted identities and the token returned once by the tool."""

    user: User
    machine: Machine
    token: str = field(repr=False)


def join(session: Session, username: str, machine_name: str, os: str) -> JoinedMachine:
    """Create a user and first machine within the caller's transaction."""
    started_at = perf_counter()
    username = _validated_name(username, "username", USERNAME_MAX_LENGTH)
    machine_name = _validated_name(machine_name, "machine_name", MACHINE_NAME_MAX_LENGTH)
    operating_system = _validated_operating_system(os)

    user = User(username=username)
    session.add(user)
    try:
        session.flush()
    except IntegrityError as error:
        raise Conflict(
            f"Username '{username}' is already taken. Pick a different one, or, if "
            "this is you on a new computer, add the machine from a computer that "
            "is already registered instead of joining again."
        ) from error

    token = generate_machine_token()
    machine = Machine(
        user_id=user.user_id,
        name=machine_name,
        os=operating_system,
        token_hash=hash_token(token),
    )
    session.add(machine)
    session.flush()

    _claim_admin(session, user)

    logger.debug(
        f"Join persisted. Username: '{loggable(username)}'. "
        f"Machine: '{loggable(machine_name)}'. "
        f"Elapsed: '{(perf_counter() - started_at) * 1000:.0f}ms'."
    )
    return JoinedMachine(user=user, machine=machine, token=token)


def _claim_admin(session: Session, user: User) -> None:
    """Claim admin if none exists, preserving the join if another caller wins.

    The partial unique index enforces one admin. The guard avoids routine conflicts;
    the savepoint keeps a Postgres race loser from aborting the join. See ADR-0008.
    """
    try:
        with session.begin_nested():
            session.execute(
                update(User)
                .where(
                    User.user_id == user.user_id,
                    ~exists(select(User.user_id).where(User.is_admin.is_(True))),
                )
                .values(is_admin=True)
            )
    except IntegrityError:
        logger.info(
            "Admin already claimed concurrently; joining as a regular user. "
            f"Username: '{loggable(user.username)}'."
        )
        return

    session.refresh(user, ["is_admin"])


def _validated_name(value: str, field: str, max_length: int) -> str:
    """Trim names and enforce limits before either database sees them."""
    if not isinstance(value, str):
        raise ValidationError(f"{field} must be text, but a {type(value).__name__} arrived.")

    stripped = value.strip()
    if "\x00" in stripped:
        raise ValidationError(f"{field} contains NUL. Remove it. Received: '{loggable(stripped)}'.")
    if not stripped:
        raise ValidationError(
            f"{field} is blank. Give a name with at least one non-whitespace character."
        )
    if len(stripped) > max_length:
        raise ValidationError(
            f"{field} is {len(stripped)} characters long, and the limit is "
            f"{max_length}. Received: '{stripped[:max_length]}...'."
        )
    return stripped


def _validated_operating_system(os: str) -> OperatingSystem:
    """Accept the same OS values advertised by the tool schema."""
    try:
        return OperatingSystem(os)
    except ValueError as error:
        supported = ", ".join(member.value for member in OperatingSystem)
        raise ValidationError(f"os must be one of {supported}. Received: '{os}'.") from error
