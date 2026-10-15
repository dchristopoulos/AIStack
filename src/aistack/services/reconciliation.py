"""The sync policy: what to do about one resource on one machine.

A pure function over two facts: what the machine is supposed to have and what was found on
it, returning what sync does. It knows nothing about skills, hashes, paths, or the database
(ADR-0007). Skill-specific code computes the two facts; a rule or hook adapter will compute
them differently and reuse this table, because the table is where the data-loss decisions are.

The one rule (ADR-0006): act silently only when the resource is enabled here and the local
copy is absent or matches a revision the vault knows. Everything else is a question.
"""

from dataclasses import dataclass
from enum import StrEnum


class Desired(StrEnum):
    """What the server holds for this resource on this machine."""

    ENABLED = "enabled"
    # An explicit decision to not have it here.
    DISABLED = "disabled"
    # No decision was ever made here.
    UNDECIDED = "undecided"


class Observed(StrEnum):
    """What was found on the machine, compared with the vault's revisions."""

    ABSENT = "absent"
    # Matches the latest revision.
    CURRENT = "current"
    # Matches an older revision: unmodified, just behind.
    STALE = "stale"
    # Matches no revision: edited locally, or never from the vault.
    UNKNOWN = "unknown"


class Step(StrEnum):
    NOTHING = "nothing"
    INSTALL = "install"
    UPDATE = "update"
    ASK = "ask"


class Choice(StrEnum):
    """An answer the user may give. Each maps to an existing operation; none is hidden."""

    # Take the vault's latest revision and manage this resource here from now on.
    ENABLE = "enable"
    # Take the vault's latest revision over an edited copy. Already managed here, so nothing
    # about this machine changes except the files.
    RESTORE = "restore"
    # Send the local copy to the vault as a new revision.
    PUSH = "push"
    # Delete the local copy; the server already holds the decision not to have it here.
    REMOVE = "remove"
    # Do nothing now. The same question comes back on the next sync.
    SKIP = "skip"


@dataclass(frozen=True)
class Option:
    """One choice and what it costs.

    The two flags are the contract, not decoration: a prompt that leads to overwriting local
    content must say so, and a choice that destroys work nobody else has must say that too.
    """

    choice: Choice
    # Files on disk will be replaced by the vault's.
    overwrites_local: bool = False
    # The local copy holds content the vault does not, and this choice destroys it.
    loses_local_edits: bool = False


@dataclass(frozen=True)
class Verdict:
    step: Step
    options: tuple[Option, ...] = ()


_NOTHING = Verdict(Step.NOTHING)

_KEEP_AS_IS = Option(Choice.ENABLE)
_REPLACE_UNMODIFIED = Option(Choice.ENABLE, overwrites_local=True)
_REPLACE_EDITED = Option(Choice.ENABLE, overwrites_local=True, loses_local_edits=True)
_RESTORE = Option(Choice.RESTORE, overwrites_local=True, loses_local_edits=True)
_PUSH = Option(Choice.PUSH)
_SKIP = Option(Choice.SKIP)
_REMOVE = Option(Choice.REMOVE)
_REMOVE_EDITED = Option(Choice.REMOVE, loses_local_edits=True)

_POLICY: dict[tuple[Desired, Observed], Verdict] = {
    # Enabled here: the only rows where sync acts without asking.
    (Desired.ENABLED, Observed.ABSENT): Verdict(Step.INSTALL),
    (Desired.ENABLED, Observed.CURRENT): _NOTHING,
    (Desired.ENABLED, Observed.STALE): Verdict(Step.UPDATE),
    (Desired.ENABLED, Observed.UNKNOWN): Verdict(Step.ASK, (_RESTORE, _PUSH, _SKIP)),

    # Explicitly disabled here, yet present on disk.
    (Desired.DISABLED, Observed.ABSENT): _NOTHING,
    (Desired.DISABLED, Observed.CURRENT): Verdict(Step.ASK, (_KEEP_AS_IS, _REMOVE)),
    (Desired.DISABLED, Observed.STALE): Verdict(Step.ASK, (_REPLACE_UNMODIFIED, _REMOVE)),
    (Desired.DISABLED, Observed.UNKNOWN): Verdict(
        Step.ASK, (_PUSH, _REPLACE_EDITED, _REMOVE_EDITED, _SKIP)),

    # In the vault and on disk, with no decision here. Never enabled silently: enabling means
    # future revisions overwrite the folder, which the user must agree to once.
    (Desired.UNDECIDED, Observed.ABSENT): _NOTHING,
    (Desired.UNDECIDED, Observed.CURRENT): Verdict(Step.ASK, (_KEEP_AS_IS, _SKIP)),
    (Desired.UNDECIDED, Observed.STALE): Verdict(Step.ASK, (_REPLACE_UNMODIFIED, _SKIP)),
    (Desired.UNDECIDED, Observed.UNKNOWN): Verdict(Step.ASK, (_PUSH, _REPLACE_EDITED, _SKIP)),
}


def reconcile(desired: Desired, observed: Observed) -> Verdict:
    """What sync does for one resource, given what is wanted and what was found."""
    return _POLICY[desired, observed]
