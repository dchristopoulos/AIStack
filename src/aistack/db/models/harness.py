from enum import StrEnum

from sqlalchemy import Enum


class Harness(StrEnum):
    """The skills folders a machine's skills are placed in (ADR-0018).

    The values are stored, so a new folder is a new member and a migration that widens the
    CHECK constraints on `machine_skill.harness` and `machine_harness.harness`.
    """

    CLAUDE_CODE = "claude_code"
    AGENTS = "agents"


def harness_type(constraint_name: str) -> Enum:
    """A harness key as VARCHAR + CHECK, stored the way `machine.os` is (see Machine).

    Stored by value: the member names are Python's spelling, the values are the wire's.
    """
    return Enum(Harness, native_enum=False, create_constraint=True, length=16,
                validate_strings=True, name=constraint_name,
                values_callable=lambda members: [member.value for member in members])
