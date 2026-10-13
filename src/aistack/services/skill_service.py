import logging
import uuid
from dataclasses import dataclass
from time import perf_counter

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from aistack.commons.exceptions import Conflict, InvalidTicket, NotFound
from aistack.commons.text import loggable
from aistack.db.models.machine import Machine
from aistack.db.models.machine_skill import MachineSkill
from aistack.db.models.skill import Skill
from aistack.db.models.skill_file import SkillFile
from aistack.db.models.skill_version import SkillVersion
from aistack.db.models.timestamps import as_utc
from aistack.db.models.user import User
from aistack.services.skill_archive import build_archive, read_archive
from aistack.services.skill_validation import (
    ValidatedSkill,
    validated_skill,
    validated_skill_name,
)

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
    # True when this push may have landed on somebody else's unrelated skill of the same
    # name, and the agent must say so. See _possibly_unrelated.
    possibly_unrelated: bool


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
    version, previous = _store_revision(session, skill, uploaded,
                                        _latest_version(session, skill.skill_id), user_id)
    unchanged = version is previous
    previous_pushed_by = None if previous is None else _username(session, previous.pushed_by)
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
        possibly_unrelated=(not unchanged
                            and _possibly_unrelated(previous, user_id, origin, skill.origin)),
    )


@dataclass(frozen=True)
class SkillSummary:
    name: str
    description: str


@dataclass(frozen=True)
class InstallableFile:
    path: str
    sha256: str
    executable: bool


@dataclass(frozen=True)
class InstallableSkill:
    """The latest revision of a skill, described but not carried: bytes travel separately."""

    name: str
    description: str
    skill_version_id: uuid.UUID
    revision: int
    version: str | None
    pushed_by: str
    content_hash: str
    files: tuple[InstallableFile, ...]


def list_skills(session: Session) -> list[SkillSummary]:
    """Every skill in the vault, by name. The listing is also the search."""
    rows = session.execute(select(Skill.name, Skill.description).order_by(Skill.name)).all()
    return [SkillSummary(name=name, description=description) for name, description in rows]


def get_skill(session: Session, machine_id: uuid.UUID, name: str) -> InstallableSkill:
    """Enable `name` for this machine and describe its latest revision.

    Install, restore, re-enable, and adopt are all this call: each one means "this machine
    should have the latest revision", and the answer to each is the same files.
    """
    skill = _required_skill(session, name)
    version = _latest_version(session, skill.skill_id)
    set_enabled(session, machine_id, skill.skill_id, enabled=True)

    files = session.execute(
        select(SkillFile.path, SkillFile.sha256, SkillFile.executable)
        .where(SkillFile.skill_version_id == version.skill_version_id)
        .order_by(SkillFile.path)
    ).all()
    return InstallableSkill(
        name=skill.name,
        description=skill.description,
        skill_version_id=version.skill_version_id,
        revision=version.revision,
        version=version.version,
        pushed_by=_username(session, version.pushed_by),
        content_hash=version.content_hash,
        files=tuple(InstallableFile(path=path, sha256=sha256, executable=executable)
                    for path, sha256, executable in files),
    )


def disable_skill(session: Session, machine_id: uuid.UUID, name: str) -> str:
    """Record that this machine should not have `name`. The row stays, as `enabled = False`.

    Keeping the row is the point (ADR-0006): sync tells "the user removed this here" apart
    from "this machine never decided", and only the first is a reason to stay quiet.
    """
    skill = _required_skill(session, name)
    decision = _machine_skill(session, machine_id, skill.skill_id)
    if decision is None:
        raise NotFound(
            f"'{skill.name}' was never enabled on this machine, so there is nothing to "
            "disable. If its folder is on disk and the user wants it gone, delete the folder; "
            "the vault holds no decision about it for this machine."
        )
    decision.enabled = False
    return skill.name


def archive_of(session: Session, machine_id: uuid.UUID,
               skill_version_id: uuid.UUID) -> tuple[str, bytes]:
    """The skill name and gzipped tar of one exact revision, for a machine still registered.

    The revision was chosen when the ticket was minted, so a push that lands between the
    tool call and the download cannot serve files that disagree with what the tool described.
    """
    if session.get(Machine, machine_id) is None:
        raise InvalidTicket(
            "The machine this transfer URL was issued to is no longer registered, so the URL "
            "is void. Reconnect this computer to AIStack before trying again."
        )

    revision = session.execute(
        select(Skill.name, SkillVersion.created_on)
        .join(SkillVersion, SkillVersion.skill_id == Skill.skill_id)
        .where(SkillVersion.skill_version_id == skill_version_id)
    ).one_or_none()
    if revision is None:
        raise NotFound("The revision this transfer URL points at no longer exists. Call "
                       "get_skill again for the current one.")
    name, pushed_on = revision

    files = session.execute(
        select(SkillFile.path, SkillFile.content, SkillFile.executable)
        .where(SkillFile.skill_version_id == skill_version_id)
    ).all()
    return name, build_archive(
        ((path, content.encode("utf-8"), executable) for path, content, executable in files),
        # Installed files are dated by when the revision was pushed, not 1970 and not now.
        modified_at=int(as_utc(pushed_on).timestamp()),
    )


def _possibly_unrelated(previous: SkillVersion | None, user_id: uuid.UUID,
                        pushed_origin: str | None, stored_origin: str | None) -> bool:
    """Whether a new revision may be a different skill that happens to share the name.

    Names are the only identity a skill has, so two people can push unrelated skills called
    `review` and the second silently becomes revision 2 of the first. Nothing can detect that
    for certain. What can be known is when it is ruled out:

    - there was no previous revision, so there is nothing to collide with;
    - the same user pushed the previous revision, so they know what they are replacing;
    - both pushes named the same origin, so they came from the same place.

    Two unknown origins rule nothing out. That is the motivating case, not an edge: most
    skills are written by their pusher and have no origin at all.
    """
    if previous is None or previous.pushed_by == user_id:
        return False
    return pushed_origin is None or pushed_origin != stored_origin


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
                    user_id: uuid.UUID) -> tuple[SkillVersion, SkillVersion | None]:
    """Insert the next revision and return it with the one it follows.

    When the content is identical to the latest revision nothing is inserted, and that
    revision is returned as both: it is its own predecessor.

    The revision number is MAX + 1, read and written inside this transaction. Two pushes can
    read the same MAX; the unique constraint on (skill_id, revision) lets one through, and
    the other rolls back to its savepoint and reads again. The predecessor returned is the
    one the insert finally followed, which after a lost race is not the one first read.
    """
    for _ in range(_REVISION_ATTEMPTS):
        if latest is not None and latest.content_hash == uploaded.content_hash:
            return latest, latest

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
            return version, latest
        except IntegrityError:
            logger.info(f"Revision number taken concurrently; retrying. "
                        f"Skill: '{skill.name}'. Revision: '{version.revision}'.")
            latest = _latest_version(session, skill.skill_id)

    raise Conflict(
        f"Several pushes to '{skill.name}' landed at the same moment and this one kept "
        "losing the race for a revision number. Nothing was stored; push it again."
    )


def _required_skill(session: Session, name: str) -> Skill:
    """The skill called `name`, or a rejection that says where to look instead."""
    skill = _skill_named(session, validated_skill_name(name))
    if skill is None:
        raise NotFound(f"The vault has no skill named '{name}'. Call list_skills to see "
                       "what it holds; names are exact.")
    return skill


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
