import logging
import uuid
from dataclasses import dataclass
from time import perf_counter

from sqlalchemy import func, null, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from aistack.commons.exceptions import Conflict, InvalidTicket, NotFound
from aistack.commons.text import loggable
from aistack.db.models.harness import Harness
from aistack.db.models.machine import Machine
from aistack.db.models.machine_skill import MachineSkill
from aistack.db.models.skill import Skill
from aistack.db.models.skill_file import SkillFile
from aistack.db.models.skill_version import SkillVersion
from aistack.db.models.team import Team, TeamGroup
from aistack.db.models.timestamps import as_utc
from aistack.db.models.user import User
from aistack.services import visibility
from aistack.services.harnesses import folder, validated_harness
from aistack.services.skill_archive import build_archive, read_archive
from aistack.services.skill_validation import ValidatedFile, ValidatedSkill, validated_skill

logger = logging.getLogger(__name__)

# How many times a push re-reads the latest revision after losing a race for the next number.
# Each loss means another push committed, so three in a row is a stampede, not bad luck.
_REVISION_ATTEMPTS = 3


@dataclass(frozen=True)
class PushedSkill:
    """What a push did, as facts for the agent to report."""

    name: str
    revision: int
    # True when this push introduced the skill to the user's own skills.
    created: bool
    # True when the upload matched the latest revision and no new one was stored.
    unchanged: bool
    content_hash: str
    file_count: int
    # Who pushed the revision that was latest before this upload; None for a new skill.
    previous_pushed_by: str | None
    stored_origin: str | None


def push(session: Session, machine_id: uuid.UUID, user_id: uuid.UUID, name: str,
         origin: str | None, archive: bytes, harness: str | None = None) -> PushedSkill:
    """Store an uploaded archive as the next revision of the user's own skill `name`, and
    enable it for the machine in the harness it was pushed from.

    A push only ever lands in the pusher's personal team. Putting a skill in front of other
    people is `share`, a separate act. A skill backed up from one folder is placed in that
    folder only: the machine's other harnesses have not decided about it (ADR-0018).

    Everything about the archive is validated before the first query, so a rejected upload
    costs no database work and leaves no row.
    """
    started_at = perf_counter()
    uploaded = validated_skill(name, read_archive(archive))
    harness = validated_harness(harness)
    _require_registered_machine(session, machine_id, user_id)

    skill, created = _find_or_create_skill(
        session, visibility.personal_team(session, user_id).team_id, uploaded, origin, user_id)
    version, previous = _store_revision(session, skill, uploaded,
                                        _latest_version(session, skill.skill_id), user_id)
    unchanged = version is previous
    previous_pushed_by = None if previous is None else _username(session, previous.pushed_by)
    if not unchanged:
        # Denormalized from the latest revision, so a listing reads one table.
        skill.description = uploaded.description
    # Pushing a skill the user had removed brings it back.
    skill.archived = False

    set_enabled(session, machine_id, harness, skill.skill_id, enabled=True)

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
    )


@dataclass(frozen=True)
class SkillSummary:
    name: str
    # The team that shares it, or None for one of the caller's own.
    team: str | None
    group: str | None
    description: str
    revision: int
    pushed_by: str


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
    # Where the harness keeps its skills on this machine: the agent installs there.
    folder: str


def list_skills(session: Session, user_id: uuid.UUID) -> list[SkillSummary]:
    """The caller's own skills, then every team skill they may see. The listing is the search."""
    newest = (
        select(SkillVersion.skill_id, func.max(SkillVersion.revision).label("revision"))
        .group_by(SkillVersion.skill_id).subquery()
    )

    def described(skills) -> list:
        chosen = skills.subquery()
        in_a_team = "team" in chosen.c
        team = chosen.c.team if in_a_team else null()
        group = chosen.c.group if in_a_team else null()
        # PostgreSQL refuses to order by a constant, which is what `team` is for one's own.
        order = (chosen.c.team, chosen.c.name) if in_a_team else (chosen.c.name,)
        return session.execute(
            select(chosen.c.name, team, group, chosen.c.description, newest.c.revision,
                   User.username)
            .join(newest, newest.c.skill_id == chosen.c.skill_id)
            .join(SkillVersion, (SkillVersion.skill_id == newest.c.skill_id)
                  & (SkillVersion.revision == newest.c.revision))
            .join(User, User.user_id == SkillVersion.pushed_by)
            .order_by(*order)
        ).all()

    mine = described(visibility.my_skills(user_id).where(Skill.archived.is_(False)))
    shared = described(visibility.team_skills(session, user_id))
    return [SkillSummary(*row) for row in (*mine, *shared)]


def get_skill(session: Session, machine_id: uuid.UUID, user_id: uuid.UUID, name: str,
              team: str | None = None, harness: str | None = None) -> InstallableSkill:
    """Enable the user's own skill `name` in one harness of this machine and describe its
    latest revision.

    Install, restore, re-enable, and adopt are all this call: each one means "this machine
    should have the latest revision", and the answer to each is the same files.

    With `team`, the team's latest revision is first taken into the user's own skills. That
    is how a team skill is installed and how an offered update is accepted, and it is why a
    copy survives its user leaving the team: what a machine runs was always their own.
    """
    harness = validated_harness(harness)
    # Sync offers "enable" for a skill the user removed whose folder is still on disk.
    # Saying yes brings it back.
    skill = (visibility.required_my_skill(session, user_id, name, removed_too=True)
             if team is None else take_from_team(session, user_id, name, team))
    skill.archived = False
    version = _latest_version(session, skill.skill_id)
    set_enabled(session, machine_id, harness, skill.skill_id, enabled=True)

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
        folder=folder(harness, session.get(Machine, machine_id).os),
    )


def take_from_team(session: Session, user_id: uuid.UUID, name: str, team: str) -> Skill:
    """Copy a team skill's latest revision into the user's own skills, and link the two.

    The copy becomes the newest revision of their own skill of that name, keeping the name of
    whoever pushed it to the team. The user asked for it, so a different version they had is
    superseded, not lost: it stays in their history.
    """
    source = visibility.team_skill(session, user_id, name, team)
    latest = _latest_version(session, source.skill_id)
    copied = _stored_as_uploaded(session, source, latest)

    mine, _ = _find_or_create_skill(
        session, visibility.personal_team(session, user_id).team_id, copied, source.origin,
        user_id)
    _store_revision(session, mine, copied, _latest_version(session, mine.skill_id),
                    latest.pushed_by)
    mine.description = source.description
    mine.archived = False
    mine.source_skill_id = source.skill_id
    mine.source_revision = latest.revision
    return mine


@dataclass(frozen=True)
class SharedSkill:
    """What sharing did, as facts for the agent or the screen to report."""

    name: str
    team: str
    group: str | None
    revision: int
    # True when the team did not have a skill of this name before.
    created: bool
    # True when the team already held exactly these files.
    unchanged: bool
    previous_pushed_by: str | None
    # True when the team already had a skill of this name that the user's copy was never
    # taken from: it may be someone else's unrelated skill, now with this on top.
    possibly_unrelated: bool


def share(session: Session, user_id: uuid.UUID, name: str, team: str,
          group: str | None = None) -> SharedSkill:
    """Put the latest revision of the user's own skill in front of a team.

    The team keeps its own copy with its own history, so later changes to either side reach
    the other only when someone shares or takes again. Any member may share over a team's
    skill; every revision says who did.
    """
    mine = visibility.required_my_skill(session, user_id, name)
    destination, _ = visibility.membership(session, user_id, team)
    target_group = None if group is None else _group_to_share_into(session, user_id,
                                                                    destination, group)
    copied = _stored_as_uploaded(session, mine, _latest_version(session, mine.skill_id))

    existing = session.scalar(select(Skill).where(Skill.team_id == destination.team_id,
                                                  Skill.name == mine.name))
    if existing is not None and not visibility.can_see_team_skill(session, user_id,
                                                                  existing.skill_id):
        raise Conflict(
            f"Team '{destination.name}' already uses the name '{mine.name}' somewhere you "
            "cannot see. Ask a team admin, or share it under a different name."
        )
    if existing is not None and target_group is not None \
            and existing.group_id != target_group.group_id:
        raise Conflict(
            f"'{mine.name}' is already in team '{destination.name}', outside group "
            f"'{target_group.path}'. Share it without a group to update it where it is; a "
            "team admin can move it."
        )

    target, created = _find_or_create_skill(session, destination.team_id, copied, mine.origin,
                                            user_id)
    if created and target_group is not None:
        target.group_id = target_group.group_id
    version, previous = _store_revision(session, target, copied,
                                        _latest_version(session, target.skill_id), user_id)
    unchanged = version is previous
    if not unchanged:
        target.description = mine.description

    related = created or mine.source_skill_id == target.skill_id
    mine.source_skill_id = target.skill_id
    mine.source_revision = version.revision
    return SharedSkill(
        name=target.name,
        team=destination.name,
        group=_group_name(session, target.group_id),
        revision=version.revision,
        created=created,
        unchanged=unchanged,
        previous_pushed_by=(None if previous is None
                            else _username(session, previous.pushed_by)),
        possibly_unrelated=not unchanged and not related,
    )


def remove_from_my_skills(session: Session, user_id: uuid.UUID, name: str) -> str:
    """Take a skill out of the user's own skills, on every computer of theirs.

    Nothing on a disk is touched: the decision in every harness of every machine becomes
    "not here", and the next sync there asks whether to delete the folder. The row is kept
    so that sync does not take that folder for a new skill and back it up again.
    """
    skill = visibility.required_my_skill(session, user_id, name)
    skill.archived = True
    session.execute(
        update(MachineSkill)
        .where(MachineSkill.skill_id == skill.skill_id)
        .values(enabled=False)
    )
    return skill.name


def disable_skill(session: Session, machine_id: uuid.UUID, user_id: uuid.UUID,
                  name: str, harness: str | None = None) -> str:
    """Record that this harness on this machine should not have `name`. The row stays, as
    `enabled = False`.

    Keeping the row is the point (ADR-0006): sync tells "the user removed this here" apart
    from "this machine never decided", and only the first is a reason to stay quiet.
    """
    harness = validated_harness(harness)
    skill = visibility.required_my_skill(session, user_id, name, removed_too=True)
    decision = _machine_skill(session, machine_id, harness, skill.skill_id)
    if decision is None:
        raise NotFound(
            f"'{skill.name}' was never enabled on this machine in harness '{harness}', so "
            "there is nothing to disable. If its folder is on disk and the user wants it gone, "
            "delete the folder; the server holds no decision about it there."
        )
    decision.enabled = False
    return skill.name


def archive_of(session: Session, machine_id: uuid.UUID,
               skill_version_id: uuid.UUID) -> tuple[str, bytes]:
    """The skill name and gzipped tar of one exact revision, for a machine still registered.

    The revision was chosen when the ticket was minted, so a push that lands between the
    tool call and the download cannot serve files that disagree with what the tool described.
    """
    machine = session.get(Machine, machine_id)
    if machine is None:
        raise InvalidTicket(
            "The machine this transfer URL was issued to is no longer registered, so the URL "
            "is void. Reconnect this computer to AIStack before trying again."
        )

    revision = session.execute(
        select(Skill.skill_id, Skill.name, SkillVersion.created_on)
        .join(SkillVersion, SkillVersion.skill_id == Skill.skill_id)
        .where(SkillVersion.skill_version_id == skill_version_id)
    ).one_or_none()
    # A machine installs only from its user's own skills, so a ticket for anything else is
    # not one this server issued to it.
    if revision is None or not visibility.is_my_skill(session, machine.user_id,
                                                      revision.skill_id):
        raise NotFound("The revision this transfer URL points at no longer exists. Call "
                       "get_skill again for the current one.")
    _, name, pushed_on = revision

    files = session.execute(
        select(SkillFile.path, SkillFile.content, SkillFile.executable)
        .where(SkillFile.skill_version_id == skill_version_id)
    ).all()
    return name, build_archive(
        ((path, content.encode("utf-8"), executable) for path, content, executable in files),
        # Installed files are dated by when the revision was pushed, not 1970 and not now.
        modified_at=int(as_utc(pushed_on).timestamp()),
    )


@dataclass(frozen=True)
class ExportedSkill:
    name: str
    content_hash: str
    archive: bytes


def export_library(session: Session, machine_id: uuid.UUID,
                   user_id: uuid.UUID) -> list[ExportedSkill]:
    """The latest revision of every skill in the user's Library, packed as an install gets it.

    Removed skills stay out, and so does the history: what moves to another Library is what
    this one would install today.
    """
    exported = []
    for skill in session.scalars(visibility.my_skills(user_id)
                                 .where(Skill.archived.is_(False)).order_by(Skill.name)):
        version = _latest_version(session, skill.skill_id)
        _, archive = archive_of(session, machine_id, version.skill_version_id)
        exported.append(ExportedSkill(skill.name, version.content_hash, archive))
    return exported


def set_enabled(session: Session, machine_id: uuid.UUID, harness: Harness,
                skill_id: uuid.UUID, enabled: bool) -> None:
    """Record a decision about a skill in one harness of a machine, keeping exactly one row
    per machine, harness, and skill."""
    decision = _machine_skill(session, machine_id, harness, skill_id)
    if decision is None:
        try:
            # A savepoint, so losing a race for the row costs a re-read and not the push.
            with session.begin_nested():
                session.add(MachineSkill(machine_id=machine_id, harness=harness,
                                         skill_id=skill_id, enabled=enabled))
            return
        except IntegrityError:
            decision = _machine_skill(session, machine_id, harness, skill_id)
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


def _find_or_create_skill(session: Session, team_id: uuid.UUID, uploaded: ValidatedSkill,
                          origin: str | None, user_id: uuid.UUID) -> tuple[Skill, bool]:
    skill = _skill_in(session, team_id, uploaded.name)
    if skill is not None:
        return skill, False

    try:
        with session.begin_nested():
            skill = Skill(team_id=team_id, name=uploaded.name,
                          description=uploaded.description, origin=origin, pushed_by=user_id)
            session.add(skill)
        return skill, True
    except IntegrityError:
        # Another push introduced the same name between the read and the insert. This one
        # becomes a second revision of that skill, which is what it would have been a
        # moment later anyway.
        logger.info(f"Skill created concurrently; pushing a revision instead. "
                    f"Skill: '{uploaded.name}'.")
        return _skill_in(session, team_id, uploaded.name), False


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


def _skill_in(session: Session, team_id: uuid.UUID, name: str) -> Skill | None:
    """By team, for a caller that has already established the right to write there."""
    return session.scalar(select(Skill).where(Skill.team_id == team_id, Skill.name == name))


def _stored_as_uploaded(session: Session, skill: Skill, version: SkillVersion) -> ValidatedSkill:
    """A stored revision in the shape a push arrives in, so a copy is stored by the same code.

    Its files passed validation when they were first pushed and are immutable since.
    """
    files = session.execute(
        select(SkillFile.path, SkillFile.content, SkillFile.sha256, SkillFile.executable)
        .where(SkillFile.skill_version_id == version.skill_version_id)
        .order_by(SkillFile.path)
    ).all()
    return ValidatedSkill(
        name=skill.name,
        description=skill.description,
        version=version.version,
        frontmatter=version.frontmatter_json,
        files=tuple(ValidatedFile(*file) for file in files),
        content_hash=version.content_hash,
    )


def _group_to_share_into(session: Session, user_id: uuid.UUID, team: Team,
                         group: str) -> TeamGroup:
    """The group at this path, if the caller may share into it.

    That takes belonging to the group or to one above it. A group they may not see is
    answered like one that does not exist.
    """
    found = session.scalar(select(TeamGroup).where(TeamGroup.team_id == team.team_id,
                                                   TeamGroup.path == group))
    if found is None or found.group_id not in visibility.group_access(session,
                                                                     user_id).writable:
        raise NotFound(f"You are not in a group '{loggable(group)}' in team '{team.name}'. "
                       "Share without a group, or ask a team admin to add you to it.")
    return found


def _group_name(session: Session, group_id: uuid.UUID | None) -> str | None:
    if group_id is None:
        return None
    return session.scalar(select(TeamGroup.path).where(TeamGroup.group_id == group_id))


def _latest_version(session: Session, skill_id: uuid.UUID) -> SkillVersion | None:
    return session.scalar(
        select(SkillVersion)
        .where(SkillVersion.skill_id == skill_id)
        .order_by(SkillVersion.revision.desc())
        .limit(1)
        # A retry must see the revision that just beat it, not the one this session cached.
        .execution_options(populate_existing=True)
    )


def _machine_skill(session: Session, machine_id: uuid.UUID, harness: Harness,
                   skill_id: uuid.UUID) -> MachineSkill | None:
    return session.scalar(select(MachineSkill).where(MachineSkill.machine_id == machine_id,
                                                     MachineSkill.harness == harness,
                                                     MachineSkill.skill_id == skill_id))


def _username(session: Session, user_id: uuid.UUID) -> str:
    return session.scalar(select(User.username).where(User.user_id == user_id))
