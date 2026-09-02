import logging
from dataclasses import dataclass
from time import perf_counter

from sqlalchemy import exists, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from aistack.commons.exceptions import Conflict, ValidationError
from aistack.db.models.machine import MACHINE_NAME_MAX_LENGTH, Machine
from aistack.db.models.operating_system import OperatingSystem
from aistack.db.models.user import USERNAME_MAX_LENGTH, User
from aistack.services.token_service import generate_machine_token, hash_token

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class JoinedMachine:
    """What a join produced. The token is plaintext and lives only until the tool result."""

    user: User
    machine: Machine
    token: str


def join(session: Session, username: str, machine_name: str, os: str) -> JoinedMachine:
    """Create a user and their first machine, and mint that machine's permanent token.

    The caller owns the transaction: everything here either lands together or not at all.
    """
    started_at = perf_counter()
    username = _validated_name(username, "username", USERNAME_MAX_LENGTH)
    machine_name = _validated_name(machine_name, "machine_name", MACHINE_NAME_MAX_LENGTH)
    operating_system = _validated_operating_system(os)

    user = User(username=username)
    session.add(user)
    try:
        session.flush()
    except IntegrityError as error:
        # USER.username is the only unique constraint this INSERT can violate, and the machine
        # below cannot collide because its user has just been created.
        raise Conflict(f"Username '{username}' is already taken. Pick a different one, or, if "
                       f"this is you on a new computer, add the machine from a computer that "
                       f"is already registered instead of joining again.") from error

    token = generate_machine_token()
    machine = Machine(user_id=user.user_id, name=machine_name, os=operating_system,
                      token_hash=hash_token(token))
    session.add(machine)
    session.flush()

    _claim_admin(session, user)

    logger.debug(f"Join persisted. Username: '{username}'. Machine: '{machine_name}'. "
                 f"Elapsed: '{(perf_counter() - started_at) * 1000:.0f}ms'.")
    return JoinedMachine(user=user, machine=machine, token=token)


def _claim_admin(session: Session, user: User) -> None:
    """Make this user the admin if the vault has none.

    Correctness rests entirely on the unique partial index (ADR-0008); the guarded UPDATE only
    saves the ordinary second join from raising a routine constraint error. Under Postgres
    READ COMMITTED two concurrent joins both pass the guard, the index rejects the loser, and
    the savepoint absorbs that rejection so the loser still keeps the user and machine it
    inserted above — it simply joins as a non-admin.
    """
    try:
        with session.begin_nested():
            session.execute(
                update(User)
                .where(User.user_id == user.user_id,
                       ~exists(select(User.user_id).where(User.is_admin.is_(True))))
                .values(is_admin=True)
            )
    except IntegrityError:
        logger.info(f"Admin already claimed concurrently; joining as a regular user. "
                    f"Username: '{user.username}'.")
        return

    session.refresh(user, ["is_admin"])


def _validated_name(value: str, field: str, max_length: int) -> str:
    """Reject blank and over-length names, saying what arrived.

    Length is enforced here rather than left to the column: SQLite silently accepts an
    oversized VARCHAR(n) and Postgres rejects it, so an unchecked name is a rejection that
    only happens on one of the two databases.
    """
    if not isinstance(value, str):
        raise ValidationError(f"{field} must be text, but a {type(value).__name__} arrived.")

    stripped = value.strip()
    if not stripped:
        raise ValidationError(f"{field} is blank. Give a name with at least one "
                              f"non-whitespace character.")
    if len(stripped) > max_length:
        raise ValidationError(f"{field} is {len(stripped)} characters long, and the limit is "
                              f"{max_length}. Received: '{stripped[:max_length]}...'.")
    return stripped


def _validated_operating_system(os: str) -> OperatingSystem:
    """Resolve the OS string to the enum, case-insensitively.

    MACHINE.os is NOT NULL and MCP cannot reveal the client's platform, so this value is
    always something the agent asserted and always worth checking.
    """
    try:
        return OperatingSystem(str(os).strip().upper())
    except ValueError as error:
        supported = ", ".join(member.value for member in OperatingSystem)
        raise ValidationError(f"os must be one of {supported}. Received: '{os}'.") from error
