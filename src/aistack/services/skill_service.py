import logging
import uuid
from dataclasses import dataclass
from time import perf_counter

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from aistack.commons.exceptions import Conflict, InvalidTicket
from aistack.commons.text import loggable
from aistack.db.models.machine import Machine
from aistack.db.models.machine_skill import MachineSkill
from aistack.db.models.skill import Skill
from aistack.db.models.skill_file import SkillFile
from aistack.db.models.skill_version import SkillVersion
from aistack.db.models.user import User
from aistack.services.skill_archive import read_archive
from aistack.services.skill_validation import ValidatedSkill, validated_skill

logger = logging.getLogger(__name__)

# How many times a push re-reads the latest revision after losing a race for the next number.
# Each loss means another push committed, so three in a row is a stampede, not bad luck.
_REVISION_ATTEMPTS = 3


@dataclass(frozen=True)
class PushedSkill:
    """What a push did, as facts for the agent to report."""

    name: str
    revision: int
    # True when this push introduced the skill to the vault.
    created: bool
    # True when the upload matched the latest revision and no new one was stored.
    unchanged: bool
    content_hash: str
    file_count: int
    # Who pushed the revision that was latest before this upload; None for a new skill.
    previous_pushed_by: str | None
    stored_origin: str | None
    # False when the origins differ or either is unknown: the name may be shared by two
    # unrelated skills, and the agent must say so.
    same_origin: bool


def push(session: Session, machine_id: uuid.UUID, user_id: uuid.UUID, name: str,
         origin: str | None, archive: bytes) -> PushedSkill:
    """Store an uploaded archive as the next revision of `name`, and enable it for the machine.

    Everything about the archive is validated before the first query, so a rejected upload
    costs no database work and leaves no row.
    """
    started_at = perf_counter()
    uploaded = validated_skill(name, read_archive(archive))
    _require_registered_machine(session, machine_id, user_id)

    skill, created = _find_or_create_skill(session, uploaded, origin, user_id)
    previous = _latest_version(session, skill.skill_id)
    previous_pushed_by = None if previous is None else _username(session, previous.pushed_by)

    version, unchanged = _store_revision(session, skill, uploaded, previous, user_id)
    if not unchanged:
        # Denormalized from the latest revision, so list_skills reads one table.
        skill.description = uploaded.description

    set_enabled(session, machine_id, skill.skill_id, enabled=True)

    logger.debug(
        f"Push persisted. Skill: '{name}'. Revision: '{version.revision}'. "
        f"Created: '{created}'. Unchanged: '{unchanged}'. Files: '{len(uploaded.files)}'. "
        f"Elapsed: '{(perf_counter() - started_at) * 1000:.0f}ms'."
    )
    return PushedSkill(
        name=skill.name,
        revision=version.revision,
        created=created,
        unchanged=unchanged,
        content_hash=version.content_hash,
        file_count=len(uploaded.files),
        previous_pushed_by=previous_pushed_by,
        stored_origin=skill.origin,
        same_origin=created or (origin is not None and origin == skill.origin),
    )


def set_enabled(session: Session, machine_id: uuid.UUID, skill_id: uuid.UUID,
                enabled: bool) -> None:
    """Record this machine's decision about a skill, keeping exactly one row per pair."""
    decision = _machine_skill(session, machine_id, skill_id)
    if decision is None:
        try:
            # A savepoint, so losing a race for the row costs a re-read and not the push.
            with session.begin_nested():
                session.add(MachineSkill(machine_id=machine_id, skill_id=skill_id,
                                         enabled=enabled))
            return
        except IntegrityError:
            decision = _machine_skill(session, machine_id, skill_id)
    decision.enabled = enabled


def _require_registered_machine(session: Session, machine_id: uuid.UUID,
                                user_id: uuid.UUID) -> None:
    """A ticket outlives the tool call that minted it, so the machine may be gone by now."""
    machine = session.get(Machine, machine_id)
    if machine is None or machine.user_id != user_id:
        raise InvalidTicket(
            "The machine this transfer URL was issued to is no longer registered, so the URL "
            "is void. Reconnect this computer to AIStack before trying again."
        )


def _find_or_create_skill(session: Session, uploaded: ValidatedSkill, origin: str | None,
                          user_id: uuid.UUID) -> tuple[Skill, bool]:
    skill = _skill_named(session, uploaded.name)
    if skill is not None:
        return skill, False

    try:
        with session.begin_nested():
            skill = Skill(name=uploaded.name, description=uploaded.description, origin=origin,
                          pushed_by=user_id)
            session.add(skill)
        return skill, True
    except IntegrityError:
        # Another push introduced the same name between the read and the insert. This one
        # becomes a second revision of that skill, which is what it would have been a
        # moment later anyway.
        logger.info(f"Skill created concurrently; pushing a revision instead. "
                    f"Skill: '{uploaded.name}'.")
        return _skill_named(session, uploaded.name), False


def _store_revision(session: Session, skill: Skill, uploaded: ValidatedSkill,
                    latest: SkillVersion | None,
                    user_id: uuid.UUID) -> tuple[SkillVersion, bool]:
    """Insert the next revision, or return the latest one when the content is identical.

    The revision number is MAX + 1, read and written inside this transaction. Two pushes can
    read the same MAX; the unique constraint on (skill_id, revision) lets one through, and
    the other rolls back to its savepoint and reads again.
    """
    for _ in range(_REVISION_ATTEMPTS):
        if latest is not None and latest.content_hash == uploaded.content_hash:
            return latest, True

        version = SkillVersion(
            skill_id=skill.skill_id,
            revision=1 if latest is None else latest.revision + 1,
            version=uploaded.version,
            content_hash=uploaded.content_hash,
            frontmatter_json=uploaded.frontmatter,
            pushed_by=user_id,
        )
        try:
            with session.begin_nested():
                session.add(version)
                session.flush()
                session.add_all(
                    SkillFile(
                        skill_version_id=version.skill_version_id,
                        path=file.path,
                        content=file.content,
                        sha256=file.sha256,
                        executable=file.executable,
                    )
                    for file in uploaded.files
                )
            return version, False
        except IntegrityError:
            logger.info(f"Revision number taken concurrently; retrying. "
                        f"Skill: '{skill.name}'. Revision: '{version.revision}'.")
            latest = _latest_version(session, skill.skill_id)

    raise Conflict(
        f"Several pushes to '{skill.name}' landed at the same moment and this one kept "
        "losing the race for a revision number. Nothing was stored; push it again."
    )


def _skill_named(session: Session, name: str) -> Skill | None:
    return session.scalar(select(Skill).where(Skill.name == name))


def _latest_version(session: Session, skill_id: uuid.UUID) -> SkillVersion | None:
    return session.scalar(
        select(SkillVersion)
        .where(SkillVersion.skill_id == skill_id)
        .order_by(SkillVersion.revision.desc())
        .limit(1)
        # A retry must see the revision that just beat it, not the one this session cached.
        .execution_options(populate_existing=True)
    )


def _machine_skill(session: Session, machine_id: uuid.UUID,
                   skill_id: uuid.UUID) -> MachineSkill | None:
    return session.scalar(select(MachineSkill).where(MachineSkill.machine_id == machine_id,
                                                     MachineSkill.skill_id == skill_id))


def _username(session: Session, user_id: uuid.UUID) -> str:
    return session.scalar(select(User.username).where(User.user_id == user_id))
