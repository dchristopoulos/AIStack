"""Who is calling, in local mode: the person who started the process, on this computer.

There is no invite code and no bearer (ADR-0020). A local mode database is one person's
Library, so its one user is the caller, and the computer is the machine whose id it keeps.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from aistack.commons.exceptions import Conflict
from aistack.db.models.machine import Machine
from aistack.db.models.user import User
from aistack.services import library_log


def local_machine(session: Session, machine_id: uuid.UUID, username: str,
                  machine_name: str, os: str) -> Machine:
    """The machine with the id this computer claimed, adding it, and on a new Library its
    user, if this is its first start.

    Adding is an event in the Library's log (ADR-0025), applied through `join` or
    `add_machine`, so a local Library holds exactly what a server's would. The machine token
    they mint is dropped: nothing in local mode reads one.
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
    user_id = users[0].user_id if users else uuid.uuid4()
    event = library_log.new_event(session, machine_id, library_log.MACHINE_ADDED,
                                  user_id=str(user_id), username=username,
                                  machine_name=machine_name, os=os)
    machine = library_log.apply(session, event)
    library_log.record(session, event)
    return machine
