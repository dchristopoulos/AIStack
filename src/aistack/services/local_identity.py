"""Who is calling, in local mode: the person who started the process, on this computer.

There is no invite code and no bearer (ADR-0020). A local mode database is one person's
Library, so its one user is the caller, and the computer is the machine whose id it keeps.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from aistack.commons.exceptions import Conflict
from aistack.db.models.machine import MACHINE_NAME_MAX_LENGTH, Machine
from aistack.db.models.user import User
from aistack.services import onboarding_service


def local_machine(session: Session, machine_id: uuid.UUID, username: str,
                  machine_name: str, os: str) -> Machine:
    """The machine with the id this computer claimed, registering it, and on a new database
    its user, if this is its first start.

    Registering goes through `join` and `add_machine`, so a local Library holds exactly what a
    server's would. The machine token they mint is dropped: nothing in local mode reads one.
    """
    machine = session.get(Machine, machine_id)
    if machine is not None:
        return machine

    users = session.scalars(select(User).limit(2)).all()
    if len(users) > 1:
        raise Conflict(
            "This database holds more than one person's skills, so it belongs to an AIStack "
            "server, and local mode is one person's Library. Connect this computer to that "
            "server instead, or point AISTACK_DATABASE_URL at a database of your own."
        )
    if not users:
        return onboarding_service.join(session, username, machine_name, os,
                                       machine_id=machine_id).machine
    user_id = users[0].user_id
    return onboarding_service.add_machine(session, user_id,
                                          _free_name(session, user_id, machine_name), os,
                                          machine_id=machine_id).machine


def _free_name(session: Session, user_id: uuid.UUID, wanted: str) -> str:
    """`wanted`, or `wanted-2`, `wanted-3`...: two computers often share a default hostname."""
    taken = set(session.scalars(select(Machine.name).where(Machine.user_id == user_id)))
    name, number = wanted, 1
    while name in taken:
        number += 1
        suffix = f"-{number}"
        name = wanted[:MACHINE_NAME_MAX_LENGTH - len(suffix)] + suffix
    return name
