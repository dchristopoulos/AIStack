import hmac
import logging
import uuid
from dataclasses import dataclass
from time import perf_counter

from sqlalchemy import and_, func, null, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from aistack.commons.exceptions import Conflict, InvalidTicket, NotFound
from aistack.commons.text import loggable
from aistack.db.models.harness import Harness
from aistack.db.models.machine import Machine
from aistack.db.models.machine_project import MachineProject
from aistack.db.models.machine_project_skill import MachineProjectSkill
from aistack.db.models.machine_skill import MachineSkill
from aistack.db.models.skill import Skill
from aistack.db.models.skill_file import SkillFile
from aistack.db.models.skill_version import SkillVersion
from aistack.db.models.team import Team, TeamGroup
from aistack.db.models.timestamps import as_utc
from aistack.db.models.user import User
from aistack.db.ordering import bytewise
from aistack.services import (
    project_service,
    revisions,
    team_service,
    transfer_ticket,
    visibility,
)
from aistack.services.harnesses import folder, validated_harness
from aistack.services.harnesses import project_folder as project_folder_path
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
    # True when the push brought back a removed skill or changed what this harness of the
    # machine has, which an unchanged push can still do.
    placement_changed: bool = False


def push(session: Session, machine_id: uuid.UUID, user_id: uuid.UUID, name: str,
         origin: str | None, archive: bytes, harness: str | None = None,
         token_prefix: str | None = None,
         project_folder: MachineProject | None = None) -> PushedSkill:
    """Store an uploaded archive as the next revision of the user's own skill `name`, and
    enable it for the machine in the harness it was pushed from.

    A push only ever lands in the pusher's personal team. Putting a skill in front of other
    people is `share`, a separate act. A skill backed up from one folder is placed in that
    folder only: the machine's other harnesses have not decided about it (ADR-0018).

    Everything about the archive is validated before the first query, so a rejected upload
    costs no database work and leaves no row. An upload URL passes the `token_prefix` it was
    minted with, and lands only while its machine still holds that token (ADR-0027). A push
    from a project folder passes that `project_folder`, and is placed there instead (ADR-0026).
    """
    return store(session, machine_id, user_id, validated_skill(name, read_archive(archive)),
                 origin, harness, token_prefix, project_folder)


def store(session: Session, machine_id: uuid.UUID, user_id: uuid.UUID,
          uploaded: ValidatedSkill, origin: str | None,
          harness: str | None = None, token_prefix: str | None = None,
          project_folder: MachineProject | None = None) -> PushedSkill:
    """`push`, for an archive validated before the caller's transaction opened: parsing one
    is slow, and nothing slow runs while SQLite's write lock is held."""
    started_at = perf_counter()
    harness = validated_harness(harness)
    _require_registered_machine(session, machine_id, user_id, token_prefix)

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
    restored = skill.archived
    _bring_back(session, skill)

    if project_folder is None:
        placed = set_enabled(session, machine_id, harness, skill.skill_id, enabled=True,
                             revision=version.revision)
    else:
        placed = project_service.set_enabled(session, project_folder, skill.skill_id, enabled=True,
                                             revision=version.revision)

    logger.debug(
        f"Push persisted. Skill: '{skill.name}'. Revision: '{version.revision}'. "
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
        placement_changed=restored or placed,
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
    # False when this harness of the machine already had this revision enabled, so the
    # call changed nothing stored, though the files are installed again.
    changed: bool = True


def list_skills(session: Session, user_id: uuid.UUID) -> list[SkillSummary]:
    """The caller's own skills, then every team skill they may see. The listing is the search."""

    def described(skills) -> list:
        chosen = skills.subquery()
        newest = revisions.latest(select(chosen.c.skill_id))
        in_a_team = "team" in chosen.c
        team = chosen.c.team if in_a_team else null()
        group = chosen.c.group if in_a_team else null()
        # PostgreSQL refuses to order by a constant, which is what `team` is for one's own.
        order = ((bytewise(chosen.c.team), bytewise(chosen.c.name)) if in_a_team
                 else (bytewise(chosen.c.name),))
        return session.execute(
            select(chosen.c.name, team, group, chosen.c.description, newest.c.revision,
                   User.username)
            .join(newest, newest.c.skill_id == chosen.c.skill_id)
            .join(User, User.user_id == newest.c.pushed_by)
            .order_by(*order)
        ).all()

    mine = described(visibility.my_skills(user_id).where(Skill.archived.is_(False)))
    shared = described(visibility.team_skills(session, user_id))
    return [SkillSummary(*row) for row in (*mine, *shared)]


def get_skill(session: Session, machine_id: uuid.UUID, user_id: uuid.UUID, name: str,
              team: str | None = None, harness: str | None = None,
              replace: bool = False,
              project_folder: MachineProject | None = None) -> InstallableSkill:
    """Enable the user's own skill `name` in one harness of this machine and describe its
    latest revision.

    Install, restore, re-enable, and adopt are all this call: each one means "this machine
    should have the latest revision", and the answer to each is the same files.

    With `team`, the team's latest revision is first taken into the user's own skills. That
    is how a team skill is installed and how an offered update is accepted, and it is why a
    copy survives its user leaving the team: what a machine runs was always their own.

    With `project_folder`, the skill is enabled in that project folder instead, and the
    folder returned is relative to the project's top level (ADR-0026).
    """
    harness = validated_harness(harness)
    # Sync offers "enable" for a skill the user removed whose folder is still on disk.
    # Saying yes brings it back.
    skill = (visibility.required_my_skill(session, user_id, name, removed_too=True)
             if team is None else take_from_team(session, user_id, name, team, replace))
    restored = skill.archived
    _bring_back(session, skill)
    version = _latest_version(session, skill.skill_id)
    if project_folder is None:
        placed = set_enabled(session, machine_id, harness, skill.skill_id, enabled=True,
                             revision=version.revision)
    else:
        placed = project_service.set_enabled(session, project_folder, skill.skill_id,
                                             enabled=True, revision=version.revision)
    operating_system = session.get(Machine, machine_id).os

    files = session.execute(
        select(SkillFile.path, SkillFile.sha256, SkillFile.executable)
        .where(SkillFile.skill_version_id == version.skill_version_id)
        .order_by(bytewise(SkillFile.path))
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
        folder=(folder(harness, operating_system) if project_folder is None
                else project_folder_path(harness, operating_system)),
        changed=restored or placed,
    )


def take_from_team(session: Session, user_id: uuid.UUID, name: str, team: str,
                   replace: bool = False) -> Skill:
    """Copy a team skill's latest revision into the user's own skills, and link the two.

    The copy becomes the newest revision of their own skill of that name, keeping the name of
    whoever pushed it to the team. A different version they had is superseded, not lost: it
    stays in their history. A skill of their own that was never taken from this one is
    refused unless `replace` says the user agreed: it may be a different skill that only
    shares the name, and taking replaces it on every computer that has it.
    """
    # One the caller cannot reach is refused before anything is locked.
    visibility.team_skill(session, user_id, name, team)
    # A team admin may be removing or moving it at the same moment: read it again once the
    # team is locked.
    team_service.lock(session, user_id, team, shared=True)
    source = visibility.team_skill(session, user_id, name, team)
    latest = _latest_version(session, source.skill_id)
    if not replace:
        _refuse_replacing_an_unrelated_skill(session, user_id, source, latest, team)
    copied = _stored_as_uploaded(session, source, latest)

    mine, _ = _find_or_create_skill(
        session, visibility.personal_team(session, user_id).team_id, copied, source.origin,
        user_id)
    _store_revision(session, mine, copied, _latest_version(session, mine.skill_id),
                    latest.pushed_by)
    mine.description = source.description
    _bring_back(session, mine)
    mine.source_skill_id = source.skill_id
    mine.source_revision = latest.revision
    return mine


def _refuse_replacing_an_unrelated_skill(session: Session, user_id: uuid.UUID, source: Skill,
                                        latest: SkillVersion, team: str) -> None:
    mine = visibility.my_skill(session, user_id, source.name)
    if mine is None or mine.archived or mine.source_skill_id == source.skill_id:
        return
    own = _latest_version(session, mine.skill_id)
    if own is None or own.content_hash == latest.content_hash:
        return
    computers = session.scalars(
        select(Machine.name)
        .join(MachineSkill, MachineSkill.machine_id == Machine.machine_id)
        .where(MachineSkill.skill_id == mine.skill_id, MachineSkill.enabled.is_(True))
        .group_by(Machine.name).order_by(bytewise(Machine.name))).all()
    where = (f" on {', '.join(computers)} at their next sync" if computers
             else " in your Library")
    raise Conflict(
        f"You already have your own '{source.name}' (revision {own.revision}, last pushed by "
        f"{_username(session, own.pushed_by)}) that was not taken from team '{team}'. Taking "
        f"the team's replaces yours{where}; yours stays in your history. Ask the user, and "
        "take it with replace if they agree."
    )


def changed_since_taken(session: Session,
                        copies: list[tuple[uuid.UUID, uuid.UUID, int]]) -> set[uuid.UUID]:
    """Which of the user's own skills differ from the team revision they were last taken at.

    Each copy is (own skill, the team skill it follows, that skill's revision then). A copy
    that differs holds the user's own edits, which taking the team's newer revision replaces.
    """
    if not copies:
        return set()
    own_latest = (select(SkillVersion.skill_id, func.max(SkillVersion.revision).label("revision"))
                  .where(SkillVersion.skill_id.in_([own for own, _, _ in copies]))
                  .group_by(SkillVersion.skill_id).subquery())
    own_hash = dict(session.execute(
        select(SkillVersion.skill_id, SkillVersion.content_hash)
        .join(own_latest, (own_latest.c.skill_id == SkillVersion.skill_id)
              & (own_latest.c.revision == SkillVersion.revision))).all())
    taken_hash = {(skill_id, revision): content_hash
                  for skill_id, revision, content_hash in session.execute(
                      select(SkillVersion.skill_id, SkillVersion.revision,
                             SkillVersion.content_hash)
                      .where(or_(*(and_(SkillVersion.skill_id == source,
                                        SkillVersion.revision == revision)
                                   for _, source, revision in copies)))).all()}
    return {own for own, source, revision in copies
            if (source, revision) in taken_hash
            and own_hash.get(own) != taken_hash[(source, revision)]}


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
    # The team's revision this share went on top of, when the user's copy was taken from an
    # older one: whatever changed in between is no longer in the team's latest.
    overwrote_revision: int | None = None
    # The team the user's copy still follows for updates, when it is not this one: a copy
    # follows one team, and sharing it somewhere else does not change which.
    updates_from: str | None = None


def share(session: Session, user_id: uuid.UUID, name: str, team: str,
          group: str | None = None) -> SharedSkill:
    """Put the latest revision of the user's own skill in front of a team.

    The team keeps its own copy with its own history, so later changes to either side reach
    the other only when someone shares or takes again. Any member may share over a team's
    skill where they may share a new one (ADR-0029); every revision says who did.
    """
    mine = visibility.required_my_skill(session, user_id, name)
    destination, _ = team_service.lock(session, user_id, team)
    access = visibility.group_access(session, user_id)
    target_group = None if group is None else _group_to_share_into(session, access,
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
    if existing is not None and not visibility.may_share_over(access, existing):
        raise Conflict(
            f"'{mine.name}' is in group '{_group_name(session, existing.group_id)}' of team "
            f"'{destination.name}', which you can read but not share into. Ask a team admin "
            "to add you to it, or share yours under a different name."
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

    follows = _team_it_follows(session, mine, target)
    linked = mine.source_skill_id == target.skill_id
    # A copy that follows another team is related to this one when this one's latest came
    # from it: an earlier share of the same copy.
    related = created or linked or (follows is not None and previous is not None
                                    and _ever_held(session, mine, previous.content_hash))
    # Shared from an older team revision than the latest: the newer one's changes are gone.
    overwrote = (previous.revision if linked and not unchanged and previous is not None
                 and mine.source_revision is not None
                 and mine.source_revision < previous.revision else None)
    if follows is None:
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
        overwrote_revision=overwrote,
        updates_from=follows,
    )


def _ever_held(session: Session, skill: Skill, content_hash: str) -> bool:
    return session.scalar(select(SkillVersion.skill_version_id).where(
        SkillVersion.skill_id == skill.skill_id,
        SkillVersion.content_hash == content_hash).limit(1)) is not None


def _team_it_follows(session: Session, mine: Skill, target: Skill) -> str | None:
    """The other team a copy follows for updates, if it follows one it can still see."""
    if mine.source_skill_id is None or mine.source_skill_id == target.skill_id:
        return None
    source = session.get(Skill, mine.source_skill_id)
    if source is None or source.team_id == target.team_id:
        return None
    return session.scalar(select(Team.name).where(Team.team_id == source.team_id))


def remove_from_my_skills(session: Session, user_id: uuid.UUID, name: str) -> str:
    """Take a skill out of the user's own skills, on every computer of theirs.

    Nothing on a disk is touched: the decision in every folder of every machine, project
    folders included, becomes "not here", and the next sync there asks whether to delete the
    folder. The row is kept so that sync does not take that folder for a new skill and back
    it up again.
    """
    skill = visibility.required_my_skill(session, user_id, name)
    skill.archived = True
    session.execute(
        update(MachineSkill)
        .where(MachineSkill.skill_id == skill.skill_id)
        .values(enabled=False)
    )
    session.execute(
        update(MachineProjectSkill)
        .where(MachineProjectSkill.skill_id == skill.skill_id)
        .values(enabled=False)
    )
    return skill.name


def disable_skill(session: Session, machine_id: uuid.UUID, user_id: uuid.UUID,
                  name: str, harness: str | None = None,
                  project_folder: MachineProject | None = None) -> str:
    """Record that this harness on this machine should not have `name`. The row stays, as
    `enabled = False`.

    Keeping the row is the point (ADR-0006): sync tells "the user removed this here" apart
    from "this machine never decided", and only the first is a reason to stay quiet.
    """
    harness = validated_harness(harness)
    skill = visibility.required_my_skill(session, user_id, name, removed_too=True)
    if project_folder is not None:
        if not project_service.disable(session, project_folder, skill.skill_id):
            raise NotFound(f"'{skill.name}' was never enabled in this project folder, so "
                           "there is nothing to disable. If its folder is on disk and the "
                           "user wants it gone, delete the folder.")
        return skill.name
    decision = _machine_skill(session, machine_id, harness, skill.skill_id)
    if decision is None:
        raise NotFound(
            f"'{skill.name}' was never enabled on this machine in harness '{harness}', so "
            "there is nothing to disable. If its folder is on disk and the user wants it gone, "
            "delete the folder; the server holds no decision about it there."
        )
    decision.enabled = False
    return skill.name


def archive_of(session: Session, machine_id: uuid.UUID, skill_version_id: uuid.UUID,
               token_prefix: str | None = None) -> tuple[str, bytes]:
    """The skill name and gzipped tar of one exact revision, for a machine still registered.

    The revision was chosen when the ticket was minted, so a push that lands between the
    tool call and the download cannot serve files that disagree with what the tool described.
    A download URL passes the `token_prefix` it was minted with (ADR-0027).
    """
    machine = _require_registered_machine(session, machine_id, None, token_prefix)

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
    files: tuple[tuple[str, bytes, bool], ...]
    # When the revision was pushed, which its files are dated by, as an install dates them.
    modified_at: int

    def archive(self) -> bytes:
        """Packed as an install gets it. Built by the caller once its transaction is over."""
        return build_archive(self.files, modified_at=self.modified_at)


def export_library(session: Session, user_id: uuid.UUID) -> list[ExportedSkill]:
    """The latest revision of every skill in the user's Library, read in two statements.

    Removed skills stay out, and so does the history: what moves to another Library is what
    this one would install today. Nothing is packed here, because on SQLite this holds the
    write lock: the caller builds each archive after the transaction.
    """
    mine = visibility.my_skills(user_id).where(Skill.archived.is_(False)).subquery()
    latest = revisions.latest(select(mine.c.skill_id))
    rows = session.execute(
        select(mine.c.name, latest.c.skill_version_id, latest.c.content_hash,
               latest.c.created_on)
        .join(latest, latest.c.skill_id == mine.c.skill_id)
        .order_by(bytewise(mine.c.name))).all()
    files: dict[uuid.UUID, list[tuple[str, bytes, bool]]] = {}
    for version_id, path, content, executable in session.execute(
            select(SkillFile.skill_version_id, SkillFile.path, SkillFile.content,
                   SkillFile.executable)
            .where(SkillFile.skill_version_id.in_(select(latest.c.skill_version_id)))).all():
        files.setdefault(version_id, []).append((path, content.encode("utf-8"), executable))
    return [ExportedSkill(name, content_hash, tuple(files.get(version_id, ())),
                          int(as_utc(pushed_on).timestamp()))
            for name, version_id, content_hash, pushed_on in rows]


def set_enabled(session: Session, machine_id: uuid.UUID, harness: Harness,
                skill_id: uuid.UUID, enabled: bool, revision: int | None = None) -> bool:
    """Record a decision about a skill in one harness of a machine, keeping exactly one row
    per machine, harness, and skill. `revision` is the one just installed or pushed there.
    True when the decision differs from the one stored."""
    decision = _machine_skill(session, machine_id, harness, skill_id)
    if decision is None:
        try:
            # A savepoint, so losing a race for the row costs a re-read and not the push.
            with session.begin_nested():
                session.add(MachineSkill(machine_id=machine_id, harness=harness,
                                         skill_id=skill_id, enabled=enabled,
                                         revision=revision))
            return True
        except IntegrityError:
            decision = _machine_skill(session, machine_id, harness, skill_id)
    changed = decision.enabled != enabled or (revision is not None
                                              and decision.revision != revision)
    decision.enabled = enabled
    if revision is not None:
        decision.revision = revision
    return changed


def _bring_back(session: Session, skill: Skill) -> None:
    """Un-remove a skill of the user's own, even if a remove committed since it was read.

    An UPDATE, not an attribute: the ORM writes nothing when the value it loaded is already
    False, so a remove from the dashboard that lands meanwhile would win and leave the skill
    hidden from the Library while enabled on this machine.
    """
    session.execute(update(Skill).where(Skill.skill_id == skill.skill_id).values(archived=False))


def _require_registered_machine(session: Session, machine_id: uuid.UUID,
                                user_id: uuid.UUID | None, token_prefix: str | None) -> Machine:
    """A ticket outlives the tool call that minted it, so the machine may be gone by now, or
    hold a new token after the old one was lost (ADR-0027)."""
    machine = session.get(Machine, machine_id)
    if (machine is None or (user_id is not None and machine.user_id != user_id)
            or (token_prefix is not None and not hmac.compare_digest(
                transfer_ticket.token_prefix(machine.token_hash), token_prefix))):
        raise InvalidTicket(
            "The machine this transfer URL was issued to is no longer registered, so the URL "
            "is void. Reconnect this computer to AIStack before trying again."
        )
    return machine


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
        .order_by(bytewise(SkillFile.path))
    ).all()
    return ValidatedSkill(
        name=skill.name,
        description=skill.description,
        version=version.version,
        frontmatter=version.frontmatter_json,
        files=tuple(ValidatedFile(*file) for file in files),
        content_hash=version.content_hash,
    )


def _group_to_share_into(session: Session, access: visibility.GroupAccess, team: Team,
                         group: str) -> TeamGroup:
    """The group at this path, if the caller may share into it.

    That takes belonging to the group or to one above it. A group they may not see is
    answered like one that does not exist, after the same queries, so it takes no longer.
    """
    found = session.scalar(select(TeamGroup).where(TeamGroup.team_id == team.team_id,
                                                   TeamGroup.path == group,
                                                   TeamGroup.group_id.in_(access.writable)))
    if found is None:
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
