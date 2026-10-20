"""Optional copied-connection binding; absence remains compatible with older clients."""

import re
import uuid

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from aistack.commons.exceptions import Conflict, NotFound, ValidationError
from aistack.commons.text import loggable
from aistack.db.models.machine import Machine


def validated(fingerprint: str | None) -> str | None:
    if fingerprint is not None and re.fullmatch(r"[a-f0-9]{64}", fingerprint) is None:
        raise ValidationError("fingerprint must be a lowercase sha256 digest. Upgrade the installed program and try again.")
    return fingerprint


def bind(session: Session, machine_id: uuid.UUID, user_id: uuid.UUID, fingerprint: str | None) -> None:
    if fingerprint is None:
        return
    session.execute(
        update(Machine)
        .where(
            Machine.machine_id == machine_id,
            Machine.user_id == user_id,
            Machine.fingerprint_hash.is_(None),
        )
        .values(fingerprint_hash=fingerprint)
        .execution_options(synchronize_session=False)
    )
    row = session.execute(
        select(Machine.fingerprint_hash, Machine.name).where(
            Machine.machine_id == machine_id,
            Machine.user_id == user_id,
        )
    ).one_or_none()
    if row is None:
        raise NotFound("This computer is no longer registered. Add it from the dashboard with Add a computer.")
    if row.fingerprint_hash != fingerprint:
        name = loggable(row.name)
        raise Conflict(f"This looks like a different computer using {name}'s key, for example after restoring a backup. Add it as its own computer from the dashboard with Add a computer, and remove {name} if it is gone.")
