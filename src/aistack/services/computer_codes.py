"""Computer codes and approval, with no recoverable permanent credentials (ADR-0035)."""

import re
import secrets
import shlex
import uuid
from datetime import timedelta

from sqlalchemy import exists, func, or_, select, update
from sqlalchemy.orm import Session

from aistack.bundled import RUN_COMMAND
from aistack.commons.exceptions import Conflict, NotFound, SignedOut, ValidationError
from aistack.db.models.computer_code import ComputerCode
from aistack.db.models.machine import Machine
from aistack.db.models.timestamps import as_utc, utc_now
from aistack.db.models.user import User
from aistack.services import computer_fingerprint, onboarding_service
from aistack.services.token_service import hash_token
from aistack.services.transfer_ticket import token_prefix

ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
REQUEST_PREFIX = "aistreq_"
REFUSAL = (
    "This computer code or request does not work. Cancel it and make another from Add a computer."
)
DEFAULTS = {
    "name": None,
    "expires_hours": 24,
    "agents": "find",
    "skills": "library",
    "hook": True,
    "approval": True,
}


def normalized(value: str) -> str | None:
    if (
        not value.isascii()
        or re.fullmatch(r"[a-zA-Z0-9]{12}|[a-zA-Z0-9]{4}-[a-zA-Z0-9]{4}-[a-zA-Z0-9]{4}", value)
        is None
    ):
        return None
    value = value.replace("-", "").upper()
    return value if all(character in ALPHABET for character in value) else None


def options(value: dict | None, previous: dict | None = None) -> dict:
    if value is not None and (not isinstance(value, dict) or value.keys() - DEFAULTS.keys()):
        raise ValidationError(
            "Computer options are name, expires_hours, agents, skills, hook and approval."
        )
    result = (previous or DEFAULTS) | (value or {})
    if result["name"] is not None:
        if not isinstance(result["name"], str):
            raise ValidationError("The computer name must be text, or empty to use its hostname.")
        result["name"] = onboarding_service._validated_name(result["name"], "name", 64)
    if type(result["expires_hours"]) is not int or result["expires_hours"] not in (1, 24, 168):
        raise ValidationError("Choose an expiry of 1 hour, 24 hours or 7 days.")
    if result["agents"] not in ("find", "claude-code", "codex"):
        raise ValidationError("Choose Find them, Claude Code or Codex.")
    if result["skills"] not in ("library", "empty"):
        raise ValidationError("Choose Add my Library's skills or Start empty.")
    if type(result["hook"]) is not bool or type(result["approval"]) is not bool:
        raise ValidationError("The hook and approval options must be true or false.")
    return result


def _account_lock(session: Session, user_id: uuid.UUID) -> None:
    # A real row lock on PG, and BEGIN IMMEDIATE on SQLite. Counts and claims must
    # serialize even when no existing code can be locked yet.
    if (
        session.execute(
            update(User).where(User.user_id == user_id).values(user_id=user_id)
        ).rowcount
        != 1
    ):
        raise NotFound(REFUSAL)


def _issuer_valid(session: Session, row: ComputerCode, lock: bool = False) -> bool:
    if row.issuing_machine_id is None:
        return session.get(User, row.user_id) is not None
    query = select(Machine.machine_id).where(
        Machine.machine_id == row.issuing_machine_id,
        Machine.user_id == row.user_id,
        Machine.token_hash == row.issuing_token_hash,
    )
    if lock:
        query = query.with_for_update()
    return session.scalar(query) is not None


def _active(row: ComputerCode) -> bool:
    return as_utc(row.expires_on) > utc_now() and row.cancelled_on is None and row.denied_on is None


def _live_condition():
    return (
        ComputerCode.expires_on > utc_now(),
        ComputerCode.cancelled_on.is_(None),
        ComputerCode.denied_on.is_(None),
        ComputerCode.completed_on.is_(None),
        or_(
            ComputerCode.issuing_machine_id.is_(None),
            exists(
                select(Machine.machine_id).where(
                    Machine.machine_id == ComputerCode.issuing_machine_id,
                    Machine.user_id == ComputerCode.user_id,
                    Machine.token_hash == ComputerCode.issuing_token_hash,
                )
            ),
        ),
    )


def create(
    session: Session,
    user_id: uuid.UUID,
    machine_id: uuid.UUID | None,
    prefix: str | None,
    selected: dict | None = None,
) -> dict:
    selected = options(selected)
    _account_lock(session, user_id)
    issuer = None
    if machine_id is not None:
        issuer = session.scalar(
            select(Machine)
            .where(Machine.machine_id == machine_id, Machine.user_id == user_id)
            .with_for_update()
        )
        if issuer is None or token_prefix(issuer.token_hash) != prefix:
            raise SignedOut(
                "This computer's key changed. Open the dashboard again from a connected computer."
            )
    else:
        selected["approval"] = False
    count = session.scalar(
        select(func.count())
        .select_from(ComputerCode)
        .where(ComputerCode.user_id == user_id, *_live_condition())
    )
    if count >= 5:
        raise Conflict("Five computer codes are still live. Cancel one before making another.")
    plain = "".join(secrets.choice(ALPHABET) for _ in range(12))
    row = ComputerCode(
        user_id=user_id,
        issuing_machine_id=machine_id,
        issuing_token_hash=None if issuer is None else issuer.token_hash,
        code_hash=hash_token(plain),
        options=selected,
        expires_on=utc_now() + timedelta(hours=selected["expires_hours"]),
    )
    session.add(row)
    session.flush()
    return shown(session, row) | {"code": "-".join(plain[i : i + 4] for i in (0, 4, 8))}


def commands(result: dict, server: str) -> dict:
    plain = result["code"]
    return result | {
        "command": f"{RUN_COMMAND} join {shlex.quote(server)} {shlex.quote(plain)}",
        "powershell_command": f"{RUN_COMMAND} join '{server.replace(chr(39), chr(39) * 2)}' '{plain}'",
    }


def _owned(session: Session, user_id: uuid.UUID, code_id: str) -> ComputerCode:
    try:
        identity = uuid.UUID(str(code_id))
    except ValueError:
        raise NotFound(REFUSAL) from None
    _account_lock(session, user_id)
    row = session.scalar(
        select(ComputerCode)
        .where(ComputerCode.code_id == identity, ComputerCode.user_id == user_id)
        .with_for_update()
    )
    if (
        row is None
        or not _active(row)
        or row.completed_on is not None
        or not _issuer_valid(session, row, lock=True)
    ):
        raise NotFound(REFUSAL)
    return row


def change(session: Session, user_id: uuid.UUID, code_id: str, selected: dict) -> dict:
    row = _owned(session, user_id, code_id)
    if row.request_hash is not None:
        raise Conflict(
            "This code is already claimed. Cancel it and make another to change its options."
        )
    updated = options(selected, row.options)
    if row.issuing_machine_id is None:
        updated["approval"] = False
    expiry = as_utc(row.created_on) + timedelta(hours=updated["expires_hours"])
    if expiry <= utc_now():
        raise Conflict("That expiry is already past. Cancel this code and make another.")
    row.options = updated
    row.expires_on = expiry
    session.flush()
    return shown(session, row)


def decide(session: Session, user_id: uuid.UUID, code_id: str, decision: str) -> dict:
    row = _owned(session, user_id, code_id)
    if decision == "cancel":
        row.cancelled_on = utc_now()
    elif row.request_hash is None or row.approved_on is not None:
        raise NotFound(REFUSAL)
    elif decision == "approve":
        row.approved_on = utc_now()
    elif decision == "deny":
        row.denied_on = utc_now()
    else:
        raise ValidationError("Choose approve, deny or cancel.")
    session.flush()
    return shown(session, row)


def _credential(session: Session, bearer: str, kind: str) -> ComputerCode:
    plain = normalized(bearer) if kind == "computer_code" else bearer
    if plain is None:
        raise NotFound(REFUSAL)
    column = ComputerCode.code_hash if kind == "computer_code" else ComputerCode.request_hash
    row = session.scalar(select(ComputerCode).where(column == hash_token(plain)))
    if row is None:
        raise NotFound(REFUSAL)
    _account_lock(session, row.user_id)
    session.refresh(row, with_for_update=True)
    if (
        not _active(row)
        or not _issuer_valid(session, row, lock=True)
        or (kind == "computer_code" and row.request_hash is not None)
    ):
        raise NotFound(REFUSAL)
    return row


def reserve(session: Session, bearer: str, name: str | None, os: str | None) -> dict:
    row = _credential(session, bearer, "computer_code")
    name = onboarding_service._validated_name(row.options["name"] or name, "machine_name", 64)
    os = onboarding_service._validated_operating_system(os)
    if (
        session.scalar(
            select(Machine.machine_id).where(Machine.user_id == row.user_id, Machine.name == name)
        )
        is not None
    ):
        raise Conflict(
            "That computer name is already in use. Cancel the code and make another with a different name."
        )
    request = REQUEST_PREFIX + secrets.token_urlsafe(32)
    reserved = uuid.uuid4()
    count = session.execute(
        update(ComputerCode)
        .where(
            ComputerCode.code_id == row.code_id,
            ComputerCode.request_hash.is_(None),
            ComputerCode.expires_on > utc_now(),
            ComputerCode.cancelled_on.is_(None),
            ComputerCode.denied_on.is_(None),
        )
        .execution_options(synchronize_session=False)
        .values(
            request_hash=hash_token(request),
            machine_id=reserved,
            request={"name": name, "os": os.value},
            requested_on=utc_now(),
        )
    ).rowcount
    if count != 1:
        raise NotFound(REFUSAL)
    session.refresh(row)
    return {
        "status": "waiting" if row.options["approval"] else "ready",
        "request_bearer": request,
        "machine_id": str(reserved),
        "options": row.options,
        "expires_on": as_utc(row.expires_on).isoformat(),
    }


def poll(session: Session, bearer: str, fingerprint: str | None) -> dict:
    fingerprint = computer_fingerprint.validated(fingerprint)
    row = _credential(session, bearer, "computer_request")
    if row.completed_on is not None:
        return {"status": "connected", "machine_id": str(row.machine_id)}
    if row.options["approval"] and row.approved_on is None:
        return {"status": "waiting", "expires_on": as_utc(row.expires_on).isoformat()}
    changed = session.execute(
        update(ComputerCode)
        .where(
            ComputerCode.code_id == row.code_id,
            ComputerCode.completed_on.is_(None),
            ComputerCode.expires_on > utc_now(),
            ComputerCode.cancelled_on.is_(None),
            ComputerCode.denied_on.is_(None),
        )
        .execution_options(synchronize_session=False)
        .values(completed_on=utc_now())
    ).rowcount
    if changed != 1:
        raise NotFound(REFUSAL)
    # No placeholder machine and no token exist before this request wins completion.
    added = onboarding_service.add_machine(
        session,
        row.user_id,
        row.request["name"],
        row.request["os"],
        machine_id=row.machine_id,
        added_by=row.issuing_machine_id,
    )
    added.machine.fingerprint_hash = fingerprint
    session.flush()
    return {
        "status": "connected",
        "machine_id": str(row.machine_id),
        "token": added.token,
        "options": row.options,
    }


def confirm(session: Session, bearer: str, result: dict) -> dict:
    row = _credential(session, bearer, "computer_request")
    if row.completed_on is None:
        raise NotFound(REFUSAL)
    if (
        not isinstance(result, dict)
        or set(result) != {"agents", "skills"}
        or not isinstance(result["agents"], list)
        or any(agent not in ("claude-code", "codex") for agent in result["agents"])
        or type(result["skills"]) is not int
        or not 0 <= result["skills"] <= 100000
    ):
        raise ValidationError(
            "Confirm setup with the configured agents and number of installed skills."
        )
    row.request = row.request | {"setup": result}
    session.flush()
    return {"status": "complete", "machine_id": str(row.machine_id)}


def shown(session: Session, row: ComputerCode) -> dict:
    status = "pending"
    if not _issuer_valid(session, row):
        status = "revoked"
    elif row.cancelled_on is not None:
        status = "cancelled"
    elif row.denied_on is not None:
        status = "denied"
    elif row.completed_on is not None:
        status = "complete" if (row.request or {}).get("setup") is not None else "connected"
    elif as_utc(row.expires_on) <= utc_now():
        status = "expired"
    elif row.approved_on is not None:
        status = "approved"
    elif row.request_hash is not None:
        status = "waiting"
    return {
        "id": str(row.code_id),
        "status": status,
        "options": row.options,
        "expires_on": as_utc(row.expires_on).isoformat(),
        "requested_on": None if row.requested_on is None else as_utc(row.requested_on).isoformat(),
        "request": row.request,
        "machine_id": None if row.machine_id is None else str(row.machine_id),
        "operator_issued": row.issuing_machine_id is None,
    }


def overview(session: Session, user_id: uuid.UUID) -> list[dict]:
    return [
        shown(session, row)
        for row in session.scalars(
            select(ComputerCode)
            .where(ComputerCode.user_id == user_id)
            .order_by(ComputerCode.created_on.desc())
            .limit(30)
        )
    ]


def cancel_for_user(session: Session, user_id: uuid.UUID) -> None:
    _account_lock(session, user_id)
    session.execute(
        update(ComputerCode)
        .where(ComputerCode.user_id == user_id, ComputerCode.completed_on.is_(None))
        .values(cancelled_on=utc_now())
    )
