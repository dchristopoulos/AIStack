import logging
import re
import uuid
from dataclasses import dataclass, field
from time import perf_counter

from sqlalchemy import exists, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from aistack.commons.exceptions import Conflict, NotFound, ValidationError
from aistack.commons.text import loggable
from aistack.db.models.machine import MACHINE_NAME_MAX_LENGTH, Machine
from aistack.db.models.operating_system import OperatingSystem
from aistack.db.models.team import Team, TeamKind, TeamMember, TeamRole
from aistack.db.models.user import FULL_NAME_MAX_LENGTH, USERNAME_MAX_LENGTH, User
from aistack.services import team_service
from aistack.services.token_service import generate_machine_token, hash_token

logger = logging.getLogger(__name__)

_USERNAME = re.compile(r"[a-z0-9]+([._-][a-z0-9]+)*")


@dataclass(frozen=True)
class JoinedMachine:
    """Persisted identities and the token returned once by the tool."""

    user: User
    machine: Machine
    token: str = field(repr=False)
    # The team whose invite code admitted them, or None for the server's own code.
    team: str | None = None


def join(session: Session, username: str, machine_name: str, os: str,
         team_invite: str | None = None, machine_id: uuid.UUID | None = None,
         user_id: uuid.UUID | None = None) -> JoinedMachine:
    """Create a user and first machine within the caller's transaction.

    With `team_invite`, the bearer the caller presented was that team's invite code, and the
    new user is also made a member of the team (ADR-0019). `machine_id` and `user_id` are
    local mode's, which every computer sharing a log must agree on (ADR-0025); a server always
    makes new ones.
    """
    started_at = perf_counter()
    username = validated_username(username)
    machine_name = _validated_name(machine_name, "machine_name", MACHINE_NAME_MAX_LENGTH)
    operating_system = _validated_operating_system(os)
    # Resolved in this transaction, before anything is written: a code replaced since the
    # bearer was verified admits nobody.
    invite = None if team_invite is None else team_service.invited_to(session, team_invite)

    user = User(user_id=user_id, username=username)
    session.add(user)
    try:
        session.flush()
        # A personal team carries its user's name, so a username must also be free as a team
        # name. Flushed together: either name being taken is the same rejection.
        personal_team = Team(name=username, kind=TeamKind.PERSONAL, created_by=user.user_id)
        session.add(personal_team)
        session.flush()
    except IntegrityError as error:
        # The answer to a join can be lost after it committed, and it was the only copy of
        # the token, so the retry lands here too (ENT-11). Which of the two holds the name is
        # not said, as `create_team` does not say it: a team's name is its members' to know.
        raise Conflict(
            f"Username '{username}' is already taken, by a user or by a team. Pick a "
            "different one. If it is your own and this is a new computer, add the machine "
            "from a computer that is already registered instead of joining again. If you "
            "joined with this name moments ago and the answer never arrived, the account was "
            "made but no computer has its token: ask whoever runs the AIStack server to "
            "register this computer for you."
        ) from error

    token = generate_machine_token()
    machine = Machine(
        machine_id=machine_id,
        user_id=user.user_id,
        name=machine_name,
        os=operating_system,
        token_hash=hash_token(token),
    )
    session.add(machine)
    session.flush()

    _claim_admin(session, user)
    session.add(TeamMember(team_id=personal_team.team_id, user_id=user.user_id,
                           role=TeamRole.ADMIN))
    session.flush()
    team = None if invite is None else team_service.admit(session, invite, user.user_id)

    logger.debug(
        f"Join persisted. Username: '{loggable(username)}'. "
        f"Machine: '{loggable(machine_name)}'. "
        f"Elapsed: '{(perf_counter() - started_at) * 1000:.0f}ms'."
    )
    return JoinedMachine(user=user, machine=machine, token=token,
                         team=team)


@dataclass(frozen=True)
class AddedMachine:
    """A machine registered for an existing user, and the token returned once by the tool."""

    machine: Machine
    token: str = field(repr=False)


def add_machine(session: Session, user_id: uuid.UUID, machine_name: str, os: str,
                machine_id: uuid.UUID | None = None,
                added_by: uuid.UUID | None = None) -> AddedMachine:
    """Register another machine for `user_id` within the caller's transaction.

    `user_id` comes from the verified bearer, never from a tool argument: a machine can only
    ever add a sibling for its own user. `added_by` is the machine that asked, recorded so a
    person can tell a computer they added from one somebody else did (ADR-0027).
    """
    started_at = perf_counter()
    machine_name = _validated_name(machine_name, "name", MACHINE_NAME_MAX_LENGTH)
    operating_system = _validated_operating_system(os)

    token = generate_machine_token()
    machine = Machine(
        machine_id=machine_id,
        user_id=user_id,
        name=machine_name,
        os=operating_system,
        token_hash=hash_token(token),
        added_by_machine_id=added_by,
    )
    session.add(machine)
    try:
        session.flush()
    except IntegrityError as error:
        raise Conflict(
            f"You already have a machine named '{machine_name}'. Machine names are unique "
            "per user, so pick a different one for this computer."
        ) from error

    logger.debug(
        f"Machine persisted. Machine: '{loggable(machine_name)}'. User: '{user_id}'. "
        f"Elapsed: '{(perf_counter() - started_at) * 1000:.0f}ms'."
    )
    return AddedMachine(machine=machine, token=token)


def own_machine(session: Session, user_id: uuid.UUID, machine_id: str) -> Machine:
    """One of the caller's own computers, by the id the dashboard holds. Somebody else's
    computer is answered exactly like one that does not exist."""
    try:
        machine = session.get(Machine, uuid.UUID(machine_id))
    except (ValueError, TypeError, AttributeError):
        machine = None
    if machine is None or machine.user_id != user_id:
        raise NotFound(f"You have no computer '{loggable(str(machine_id))}'.")
    return machine


def remove_machine(session: Session, user_id: uuid.UUID, machine_id: str) -> str:
    """Take one of the caller's computers off the server, and return its name.

    Its token stops working at once, and every dashboard session and transfer URL it opened
    ends with it (ADR-0027). The caller's last computer is refused: without one, nobody can
    open the dashboard to add another, and only the operator could let them back in.
    """
    # Locked, so two removals at once cannot each see the other computer still there and
    # leave none. BEGIN IMMEDIATE already serializes this on SQLite (ADR-0014).
    session.execute(select(User.user_id).where(User.user_id == user_id).with_for_update())
    machine = own_machine(session, user_id, machine_id)
    others = session.scalar(select(func.count()).select_from(Machine).where(
        Machine.user_id == user_id, Machine.machine_id != machine.machine_id))
    if not others:
        raise Conflict(f"'{machine.name}' is your only computer, so it cannot be removed: "
                       "you would have no way back in. Add the computer you use instead "
                       "first, then remove this one.")
    name = machine.name
    # Its placements and sync records go with it (ON DELETE CASCADE).
    session.delete(machine)
    session.flush()
    logger.info(f"Machine removed by its owner. Machine: '{machine.machine_id}'. "
                f"User: '{user_id}'.")
    return name


def rename_machine(session: Session, user_id: uuid.UUID, machine_id: str, name: str) -> str:
    """Give one of the caller's computers a new name, unique among theirs, and return it."""
    name = _validated_name(name, "name", MACHINE_NAME_MAX_LENGTH)
    machine = own_machine(session, user_id, machine_id)
    if machine.name == name:
        return name
    machine.name = name
    try:
        with session.begin_nested():
            session.flush()
    except IntegrityError as error:
        raise Conflict(f"You already have a computer named '{name}'. Pick another name.") \
            from error
    return name


def set_full_name(session: Session, user_id: uuid.UUID, full_name: str) -> str | None:
    """Set or, with blank text, clear the name teammates read beside the caller's username."""
    if isinstance(full_name, str) and not full_name.strip():
        cleaned = None
    else:
        cleaned = _validated_name(full_name, "Full name", FULL_NAME_MAX_LENGTH)
    session.execute(update(User).where(User.user_id == user_id).values(full_name=cleaned))
    return cleaned


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


def validated_username(username: str) -> str:
    """A username is what teammates see as `pushed_by` before a skill changes on their machine.

    So no two may differ only in how they look: one case, one alphabet, no spaces. That rules
    out `Maria` beside `maria`, and a Cyrillic twin of either.
    """
    username = _validated_name(username, "username", USERNAME_MAX_LENGTH)
    if not _USERNAME.fullmatch(username):
        raise ValidationError(
            "A username is a short lowercase handle: letters and digits, joined by single "
            f"'.', '-' or '_', like 'maria' or 'j.smith'. Received: '{loggable(username)}'."
        )
    return username


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
    # A username is returned to other users' agents as `pushed_by`, so it has to be text that
    # cannot be mistaken for anything else: no line breaks, no terminal escapes.
    if not stripped.isprintable():
        raise ValidationError(
            f"{field} contains control characters. Use plain text. "
            f"Received: '{loggable(stripped)}'."
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
