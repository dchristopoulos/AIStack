import logging
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from time import perf_counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from aistack.bundled import SYNC_SKILL_NAME
from aistack.commons.exceptions import ValidationError
from aistack.db.models.machine_skill import MachineSkill
from aistack.db.models.skill import Skill
from aistack.db.models.skill_version import SkillVersion
from aistack.db.models.user import User
from aistack.services.content_hash import canonical_content_hash, normalized_path
from aistack.services.reconciliation import Desired, Observed, Option, Step, reconcile
from aistack.services.skill_archive import is_filesystem_noise

logger = logging.getLogger(__name__)

# Far beyond any real skills directory, and a ceiling on what one call can make the server
# hash and look up.
MAX_LOCAL_SKILLS = 1000
MAX_LOCAL_FILES = 20_000

# Claude Code downloads claude.ai skills into this folder and overwrites edits to it. It is
# not the user's to push and not AIStack's to manage.
_RESERVED_FOLDER = "synced"


@dataclass(frozen=True)
class Install:
    """An enabled skill with no local copy. The agent calls get_skill for it."""

    name: str
    revision: int
    pushed_by: str


@dataclass(frozen=True)
class Update:
    """An enabled skill whose local copy is an older, unmodified revision."""

    name: str
    from_revision: int
    to_revision: int
    # Who pushed the revision about to be installed: provenance at the moment of risk.
    pushed_by: str


@dataclass(frozen=True)
class Question:
    """A skill sync will not act on without the user. The options say what each answer costs."""

    name: str
    desired: Desired
    local: Observed
    # The revision the local copy matches, or None when it matches none.
    local_revision: int | None
    latest_revision: int
    pushed_by: str
    options: tuple[Option, ...]


@dataclass(frozen=True)
class SyncReport:
    install: tuple[Install, ...]
    update: tuple[Update, ...]
    ask: tuple[Question, ...]
    # On disk and not in the vault at all. Reported, offered for push, never pushed unasked:
    # a fresh machine may hold dozens of third-party skills, and importing them would record
    # this user as the pusher of things they only downloaded.
    orphans: tuple[str, ...]
    # Enabled skills whose local copy already matches the latest revision.
    up_to_date: int


@dataclass(frozen=True)
class _Revision:
    revision: int
    content_hash: str
    pushed_by: str


def sync(session: Session, machine_id: uuid.UUID,
         local: Mapping[str, Mapping[str, str]]) -> SyncReport:
    """Compare what this machine has with what it should have, and say what to do.

    Read-only. Sync never changes desired state and never returns file content: every action
    it reports is carried out by a later get_skill, push_skill, or disable_skill call.
    """
    started_at = perf_counter()
    local_hashes = _local_hashes(local)
    decisions = _decisions(session, machine_id)
    revisions = _revisions(session, set(local_hashes) | set(decisions))

    install: list[Install] = []
    update: list[Update] = []
    ask: list[Question] = []
    up_to_date = 0

    for name in sorted(revisions):
        history = revisions[name]
        latest = history[-1]
        desired = _desired(decisions.get(name))
        observed, local_revision = _observed(name in local_hashes, local_hashes.get(name),
                                             history)
        verdict = reconcile(desired, observed)

        if verdict.step is Step.INSTALL:
            install.append(Install(name, latest.revision, latest.pushed_by))
        elif verdict.step is Step.UPDATE:
            update.append(Update(name, local_revision, latest.revision, latest.pushed_by))
        elif verdict.step is Step.ASK:
            ask.append(Question(name, desired, observed, local_revision, latest.revision,
                                latest.pushed_by, verdict.options))
        elif desired is Desired.ENABLED and observed is Observed.CURRENT:
            up_to_date += 1

    # Setup wrote the sync skill from this server, so it is on every machine and in no fresh
    # vault. Once someone pushes it, it is in `revisions` and reconciled like any other.
    orphans = tuple(sorted(name for name in local_hashes
                           if name not in revisions and name != SYNC_SKILL_NAME))

    logger.debug(
        f"Sync reconciled. Machine: '{machine_id}'. Local: '{len(local_hashes)}'. "
        f"Install: '{len(install)}'. Update: '{len(update)}'. Ask: '{len(ask)}'. "
        f"Orphans: '{len(orphans)}'. Current: '{up_to_date}'. "
        f"Elapsed: '{(perf_counter() - started_at) * 1000:.0f}ms'."
    )
    return SyncReport(install=tuple(install), update=tuple(update), ask=tuple(ask),
                      orphans=orphans, up_to_date=up_to_date)


def _local_hashes(local: Mapping[str, Mapping[str, str]]) -> dict[str, str | None]:
    """The canonical hash of each local skill, or None where it cannot have one.

    None is not an error. It means "content the vault will not recognize", which is the same
    answer an edited skill gets, and the safe one: sync asks instead of acting.
    """
    if len(local) > MAX_LOCAL_SKILLS:
        raise ValidationError(
            f"sync received {len(local)} skill folders, and the limit is {MAX_LOCAL_SKILLS}. "
            "Send only the folders directly inside the global skills directory."
        )
    file_count = sum(len(files) for files in local.values())
    if file_count > MAX_LOCAL_FILES:
        raise ValidationError(
            f"sync received {file_count} files, and the limit is {MAX_LOCAL_FILES}. If a "
            ".git or node_modules folder sits inside a skill, leave it out of the listing."
        )

    return {
        name: _canonical_hash(files)
        for name, files in local.items()
        if name != _RESERVED_FOLDER and not name.startswith(".")
    }


def _canonical_hash(files: Mapping[str, str]) -> str | None:
    digests: dict[str, str] = {}
    for path, digest in files.items():
        path = normalized_path(path)
        if is_filesystem_noise(path):
            continue
        if path in digests:
            # Two spellings of one path with different digests cannot both be on disk.
            return None
        # Get-FileHash prints uppercase; the digest is the same number either way.
        digests[path] = digest.strip().lower()
    try:
        return canonical_content_hash(digests)
    except ValueError:
        return None


def _decisions(session: Session, machine_id: uuid.UUID) -> dict[str, bool]:
    """Every skill this machine has decided about: True enabled, False explicitly disabled."""
    rows = session.execute(
        select(Skill.name, MachineSkill.enabled)
        .join(MachineSkill, MachineSkill.skill_id == Skill.skill_id)
        .where(MachineSkill.machine_id == machine_id)
    ).all()
    return dict(rows)


def _revisions(session: Session, names: set[str]) -> dict[str, list[_Revision]]:
    """The full history of each named skill the vault holds, oldest first.

    A name missing from the result is not in the vault. Sync is not discovery: only names
    this machine has on disk or has decided about are ever looked up.
    """
    if not names:
        return {}
    rows = session.execute(
        select(Skill.name, SkillVersion.revision, SkillVersion.content_hash, User.username)
        .join(SkillVersion, SkillVersion.skill_id == Skill.skill_id)
        .join(User, User.user_id == SkillVersion.pushed_by)
        .where(Skill.name.in_(names))
        .order_by(Skill.name, SkillVersion.revision)
    ).all()

    history: dict[str, list[_Revision]] = {}
    for name, revision, content_hash, pushed_by in rows:
        history.setdefault(name, []).append(_Revision(revision, content_hash, pushed_by))
    return history


def _desired(enabled: bool | None) -> Desired:
    if enabled is None:
        return Desired.UNDECIDED
    return Desired.ENABLED if enabled else Desired.DISABLED


def _observed(present: bool, local_hash: str | None,
              history: list[_Revision]) -> tuple[Observed, int | None]:
    """Where the local copy stands, and which revision it matches when it matches one.

    Identical content can be pushed as two revisions (A, then B, then A again), so one hash
    can match several. Matching the latest means current; only otherwise does an older match
    mean stale.
    """
    if not present:
        return Observed.ABSENT, None

    latest = history[-1]
    if local_hash == latest.content_hash:
        return Observed.CURRENT, latest.revision

    for older in reversed(history[:-1]):
        if local_hash == older.content_hash:
            return Observed.STALE, older.revision
    return Observed.UNKNOWN, None
