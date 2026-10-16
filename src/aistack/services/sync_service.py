import hashlib
import logging
import uuid
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from time import perf_counter

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from aistack.bundled import SYNC_SKILL_NAME, sync_skill_document
from aistack.commons.exceptions import ValidationError
from aistack.db.models.harness import Harness
from aistack.db.models.machine_harness import MachineHarness
from aistack.db.models.machine_project import MachineProject
from aistack.db.models.machine_skill import MachineSkill
from aistack.db.models.skill import Skill
from aistack.db.models.skill_version import SkillVersion
from aistack.db.models.timestamps import utc_now
from aistack.db.models.user import User
from aistack.db.ordering import bytewise
from aistack.services import project_service, projects, revisions, skill_service, visibility
from aistack.services.content_hash import canonical_content_hash, normalized_path
from aistack.services.harnesses import validated_harness
from aistack.services.reconciliation import Desired, Observed, Option, Step, reconcile
from aistack.services.skill_archive import in_git_folder, is_filesystem_noise
from aistack.services.skill_validation import CLAUDE_CODE_FOLDER, refusal_from_listing

logger = logging.getLogger(__name__)

# Far beyond any real skills directory, and a ceiling on what one call can make the server
# hash and look up.
MAX_LOCAL_SKILLS = 1000
MAX_LOCAL_FILES = 20_000
# A folder name git holds in a project's skills folder: any text a file system allows.
_REPOSITORY_NAME_MAX_LENGTH = 255



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
    # For a copy that matches none: the revision last installed or pushed in this folder, which
    # it was edited from. Older than the latest means another computer pushed meanwhile, and
    # pushing this copy would take the place of that change. None when it is not known.
    edited_from: int | None
    latest_revision: int
    pushed_by: str
    options: tuple[Option, ...]
    # The user removed it from their Library: the question is whether to delete the folder.
    removed_from_library: bool = False


@dataclass(frozen=True)
class CannotBackUp:
    """A skill on disk, not in the Library, that a push would refuse, and why (IMP-16)."""

    name: str
    reason: str


@dataclass(frozen=True)
class TeamUpdate:
    """A team holds a newer revision of a skill this machine took from it or shared to it.

    An offer, never applied unasked: the user decides each time (ADR-0015).
    """

    name: str
    team: str
    from_revision: int
    to_revision: int
    pushed_by: str
    # The user changed their copy since taking from_revision: taking replaces their edits
    # on every computer that has it.
    own_changes: bool
    # A share since from_revision put a different skill of the same name in the team: this
    # is not an edit of the one the user took (UX-06).
    different_skill: bool = False


@dataclass(frozen=True)
class ProjectHere:
    """The repository the session runs in, as this server knows it (ADR-0026)."""

    key: str
    name: str
    # This computer manages a folder in it. Nothing is stored for one it does not.
    managed: bool


@dataclass(frozen=True)
class SyncReport:
    install: tuple[Install, ...]
    update: tuple[Update, ...]
    ask: tuple[Question, ...]
    # On disk and not yet in the user's own skills. The agent backs each one up without
    # asking: the Library is private and mirrors the computer, so nothing is shared and
    # nobody else sees the user as the pusher of something they only downloaded. Sharing is
    # a separate, deliberate step.
    backup: tuple[str, ...]
    team_updates: tuple[TeamUpdate, ...]
    # Enabled skills whose local copy already matches the latest revision.
    up_to_date: int
    # The sync skill on this machine is missing or is not the one this server ships. Setup
    # fetched it once and add_machine never did, so this is the only way it stays current.
    refresh_sync_skill: bool
    # This folder has never synced on this machine before. The agent offers, once, to put
    # the skills its other folder has here too (ADR-0021).
    first_sync: bool
    # The repository the session runs in, when the agent named one.
    project: ProjectHere | None = None
    # Enabled in this project folder, but a folder the repository holds has the name, so
    # nothing of the Library's goes there. The agent says so once.
    left_to_repository: tuple[str, ...] = ()
    # A project folder's first sync: skills enabled in this project on the user's other
    # computers, and in none of this folder's decisions or folders. Offered once.
    from_other_computers: tuple[str, ...] = ()
    # Not in the Library and never accepted by a push as they are: said once, not pushed.
    cannot_back_up: tuple[CannotBackUp, ...] = ()


@dataclass(frozen=True)
class _Revision:
    revision: int
    content_hash: str
    pushed_by: str


def sync(session: Session, machine_id: uuid.UUID, user_id: uuid.UUID,
         local: Mapping[str, Mapping[str, str]], harness: str | None = None,
         here: projects.Here | None = None, project: str | None = None,
         repository: Collection[str] = ()) -> SyncReport:
    """Compare one harness's folder on this machine with what its user's own skills say it
    should have.

    A machine installs only from its user's personal team, so teams never enter the
    comparison. They appear once, as updates on offer. Only this harness's decisions are
    read: each folder is reconciled on its own, by the same table (ADR-0018).

    Sync never changes desired state and never returns file content: every action it
    reports is carried out by a later get_skill, push_skill, or disable_skill call. The one
    thing it writes is that this harness synced, and when.

    With `project`, the folder compared is that project's, in the repository `here` names,
    and the one thing it writes is that folder, which is how a computer starts managing it
    (ADR-0026). `local` then holds only the folders git ignores, and `repository` names
    every other folder there: the repository's, which nothing of the Library's replaces.
    """
    started_at = perf_counter()
    harness = validated_harness(harness)
    local_hashes = _local_hashes(local)
    blocked = _repository_names(repository, project)
    where = None if here is None else _here(session, user_id, machine_id, here)
    registered = None
    if project is not None:
        if where is None or projects.validated_key(project) != where.key:
            raise ValidationError("project must be the key sync reported for the repository "
                                  "here names. Sync with here first, and send its key.")
        registered = project_service.register_folder(session, user_id, machine_id, where.key,
                                                      where.name, harness, here.path)
        where = ProjectHere(where.key, where.name, managed=True)
        decisions = project_service.decisions(session, registered.folder)
    else:
        decisions = _decisions(session, machine_id, harness)
    # The sync skill never goes in a project folder: it is the agent's own, in the global one.
    left_alone = blocked | ({SYNC_SKILL_NAME} if registered is not None else set())
    for name in left_alone:
        local_hashes.pop(name, None)
    revisions = _revisions(session, user_id, (set(local_hashes) | set(decisions)) - left_alone)
    removed = _removed(session, user_id, set(revisions))

    install: list[Install] = []
    update: list[Update] = []
    ask: list[Question] = []
    up_to_date = 0

    for name in sorted(revisions):
        history = revisions[name]
        latest = history[-1]
        enabled, last_revision = decisions.get(name, (None, None))
        # Removed from the Library means wanted in no folder, decided here or not (PH-11).
        desired = _desired(False if name in removed else enabled)
        observed, local_revision = _observed(name in local_hashes, local_hashes.get(name),
                                             history)
        verdict = reconcile(desired, observed)

        if verdict.step is Step.INSTALL:
            install.append(Install(name, latest.revision, latest.pushed_by))
        elif verdict.step is Step.UPDATE:
            update.append(Update(name, local_revision, latest.revision, latest.pushed_by))
        elif verdict.step is Step.ASK:
            edited_from = last_revision if observed is Observed.UNKNOWN else None
            ask.append(Question(name, desired, observed, local_revision, edited_from,
                                latest.revision, latest.pushed_by, verdict.options,
                                removed_from_library=name in removed))
        elif desired is Desired.ENABLED and observed is Observed.CURRENT:
            up_to_date += 1

    # Setup wrote the sync skill from this server, so it is on every machine and needs no
    # backing up. Once the user pushes their own, it is in `revisions` like any other.
    candidates = sorted(name for name in local_hashes
                        if name not in revisions and name != SYNC_SKILL_NAME)
    refused = {name: reason for name in candidates
               if (reason := refusal_from_listing(name, _pushed_paths(local[name]))) is not None}
    backup = tuple(name for name in candidates if name not in refused)
    cannot_back_up = tuple(CannotBackUp(name, reason) for name, reason in refused.items())
    enabled_here = {name for name, (enabled, _) in decisions.items() if enabled}
    team_updates = _team_updates(session, user_id, enabled_here - left_alone)

    if registered is not None:
        offered = () if not registered.first_sync else tuple(
            name for name in project_service.placed_elsewhere(
                session, user_id, registered.folder.project_id, machine_id)
            if name not in decisions and name not in local_hashes and name not in left_alone)
        _log_reconciled(machine_id, harness, local_hashes, install, update, ask, backup,
                        team_updates, up_to_date, started_at)
        return SyncReport(install=tuple(install), update=tuple(update), ask=tuple(ask),
                          backup=backup, team_updates=team_updates, up_to_date=up_to_date,
                          refresh_sync_skill=False, first_sync=registered.first_sync,
                          project=where,
                          left_to_repository=tuple(sorted(enabled_here & blocked)),
                          from_other_computers=offered, cannot_back_up=cannot_back_up)

    # A user who keeps their own sync skill manages it like any other; otherwise the server's
    # copy is the reference. It belongs in Claude Code's folder, and in the agents folder only
    # where an agent there talks to AIStack itself: setup marked that by putting it there, and
    # a computer whose Claude Code never synced is one where the caller is that agent, as on
    # one added by add_machine with Codex alone. Elsewhere it would tell an agent with no
    # connection to sync (ADR-0021).
    talks_through_agents = (SYNC_SKILL_NAME in local_hashes
                            or not _ever_synced_claude_code(session, machine_id))
    refresh_sync_skill = (SYNC_SKILL_NAME not in revisions
                          and (harness is Harness.CLAUDE_CODE or talks_through_agents)
                          and local_hashes.get(SYNC_SKILL_NAME) != _bundled_sync_skill_hash())
    first_sync = record_sync(session, machine_id, harness)

    _log_reconciled(machine_id, harness, local_hashes, install, update, ask, backup,
                    team_updates, up_to_date, started_at)
    return SyncReport(install=tuple(install), update=tuple(update), ask=tuple(ask),
                      backup=backup, team_updates=team_updates, up_to_date=up_to_date,
                      refresh_sync_skill=refresh_sync_skill, first_sync=first_sync,
                      project=where, cannot_back_up=cannot_back_up)


def _log_reconciled(machine_id, harness, local_hashes, install, update, ask, backup,
                    team_updates, up_to_date, started_at) -> None:
    logger.debug(
        f"Sync reconciled. Machine: '{machine_id}'. Harness: '{harness}'. "
        f"Local: '{len(local_hashes)}'. "
        f"Install: '{len(install)}'. Update: '{len(update)}'. Ask: '{len(ask)}'. "
        f"Backup: '{len(backup)}'. Team updates: '{len(team_updates)}'. "
        f"Current: '{up_to_date}'. "
        f"Elapsed: '{(perf_counter() - started_at) * 1000:.0f}ms'."
    )


def _here(session: Session, user_id: uuid.UUID, machine_id: uuid.UUID,
          here: projects.Here) -> ProjectHere:
    """The repository a session runs in, and whether this computer manages a folder in it.
    Reads only: a repository someone merely works in is never recorded."""
    key = here.key or projects.local_project_key(machine_id, here.path)
    project = visibility.my_project(session, user_id, key)
    managed = project is not None and session.scalar(
        select(MachineProject.machine_project_id).where(
            MachineProject.machine_id == machine_id,
            MachineProject.project_id == project.project_id).limit(1)) is not None
    return ProjectHere(key, projects.project_name(here.key or here.path), managed)


def _repository_names(names: Collection[str], project: str | None) -> set[str]:
    """The folders a project's repository holds, which sync leaves alone. Checked, never
    quoted back: they are only compared with the Library's names."""
    if isinstance(names, str) or not all(isinstance(name, str) and len(name)
                                          <= _REPOSITORY_NAME_MAX_LENGTH for name in names):
        raise ValidationError("repository is a list of folder names, each at most "
                              f"{_REPOSITORY_NAME_MAX_LENGTH} characters.")
    if len(names) > MAX_LOCAL_SKILLS:
        raise ValidationError(f"repository lists {len(names)} folders, and the limit is "
                              f"{MAX_LOCAL_SKILLS}.")
    if names and project is None:
        raise ValidationError("repository names a project folder's own skills; send it with "
                              "project.")
    return set(names)


def _bundled_sync_skill_hash() -> str:
    document = sync_skill_document().encode("utf-8")
    return canonical_content_hash({"SKILL.md": hashlib.sha256(document).hexdigest()})


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
        if name != CLAUDE_CODE_FOLDER and not name.startswith(".")
    }


def _pushed_paths(files: Mapping[str, str]) -> list[str]:
    """The paths a push of this listing would upload."""
    return [path for path in map(normalized_path, files)
            if not is_filesystem_noise(path) and not in_git_folder(path)]


def _canonical_hash(files: Mapping[str, str]) -> str | None:
    digests: dict[str, str] = {}
    for path, digest in files.items():
        path = normalized_path(path)
        if is_filesystem_noise(path) or in_git_folder(path):
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


def _decisions(session: Session, machine_id: uuid.UUID,
               harness: Harness) -> dict[str, tuple[bool, int | None]]:
    """Every skill decided about in this harness of this machine: True enabled, False
    explicitly disabled, with the revision last installed or pushed there. A decision in
    another harness is no decision here."""
    rows = session.execute(
        select(Skill.name, MachineSkill.enabled, MachineSkill.revision, Skill.archived)
        .join(MachineSkill, MachineSkill.skill_id == Skill.skill_id)
        .where(MachineSkill.machine_id == machine_id, MachineSkill.harness == harness)
    ).all()
    return {name: (project_service.removed_reads_disabled(enabled, archived), revision)
            for name, enabled, revision, archived in rows}


def record_sync(session: Session, machine_id: uuid.UUID, harness: Harness) -> bool:
    """Remember that this harness is on this machine, and when it last synced.

    True when this is its first sync here. Of two first syncs at once, only one says so.
    """
    now = utc_now()
    synced = _machine_harness(session, machine_id, harness)
    if synced is None:
        try:
            # A savepoint, so two first syncs at once cost a re-read and not the report.
            with session.begin_nested():
                session.add(MachineHarness(machine_id=machine_id, harness=harness,
                                           last_synced_on=now))
            return True
        except IntegrityError:
            synced = _machine_harness(session, machine_id, harness)
    synced.last_synced_on = now
    return False


def _ever_synced_claude_code(session: Session, machine_id: uuid.UUID) -> bool:
    """Whether Claude Code's folder synced on this machine, or holds a decision from a release
    that recorded decisions before it recorded syncs."""
    if _machine_harness(session, machine_id, Harness.CLAUDE_CODE) is not None:
        return True
    return session.scalar(select(MachineSkill.machine_id).where(
        MachineSkill.machine_id == machine_id,
        MachineSkill.harness == Harness.CLAUDE_CODE).limit(1)) is not None


def _machine_harness(session: Session, machine_id: uuid.UUID,
                     harness: Harness) -> MachineHarness | None:
    return session.scalar(select(MachineHarness).where(MachineHarness.machine_id == machine_id,
                                                       MachineHarness.harness == harness))


def _revisions(session: Session, user_id: uuid.UUID,
               names: set[str]) -> dict[str, list[_Revision]]:
    """The full history of each named skill among the user's own, oldest first.

    A name missing from the result is not one of theirs. Sync is not discovery: only names
    this machine has on disk or has decided about are ever looked up.
    """
    if not names:
        return {}
    mine = visibility.my_skills(user_id).where(Skill.name.in_(names)).subquery()
    rows = session.execute(
        select(mine.c.name, SkillVersion.revision, SkillVersion.content_hash, User.username)
        .join(SkillVersion, SkillVersion.skill_id == mine.c.skill_id)
        .join(User, User.user_id == SkillVersion.pushed_by)
        # Named, so the history is read for these skills only and never walked whole.
        .where(SkillVersion.skill_id.in_(select(mine.c.skill_id)))
        .order_by(bytewise(mine.c.name), SkillVersion.revision)
    ).all()

    history: dict[str, list[_Revision]] = {}
    for name, revision, content_hash, pushed_by in rows:
        history.setdefault(name, []).append(_Revision(revision, content_hash, pushed_by))
    return history


def _removed(session: Session, user_id: uuid.UUID, names: set[str]) -> set[str]:
    """Which of the named skills of the user's own were removed from their Library."""
    if not names:
        return set()
    return set(session.scalars(visibility.my_skills(user_id).with_only_columns(Skill.name)
                               .where(Skill.name.in_(names), Skill.archived.is_(True))))


def _team_updates(session: Session, user_id: uuid.UUID,
                  enabled_here: set[str]) -> tuple[TeamUpdate, ...]:
    """Skills enabled on this machine whose team source has moved on since they were taken.

    Only a source the user can still see counts: after leaving a team their copy is simply
    theirs, with nothing further on offer.
    """
    if not enabled_here:
        return ()
    mine = visibility.my_skills(user_id).where(
        Skill.name.in_(enabled_here), Skill.archived.is_(False),
        Skill.source_skill_id.is_not(None)).subquery()
    newest = revisions.latest(select(mine.c.source_skill_id))
    # A group the user unsubscribed from stays visible; only its updates go unmentioned.
    access = visibility.group_access(session, user_id)
    visible = visibility.team_skills(session, user_id, access).where(
        Skill.group_id.is_(None) | Skill.group_id.not_in(access.unsubscribed)).subquery()
    rows = session.execute(
        select(mine.c.name, visible.c.team, mine.c.source_revision, newest.c.revision,
               User.username, mine.c.skill_id, mine.c.source_skill_id)
        .join(visible, visible.c.skill_id == mine.c.source_skill_id)
        .join(newest, newest.c.skill_id == mine.c.source_skill_id)
        .join(User, User.user_id == newest.c.pushed_by)
        .where(newest.c.revision > mine.c.source_revision)
        .order_by(bytewise(mine.c.name))
    ).all()
    copies = [(own, source, taken) for _, _, taken, _, _, own, source in rows]
    changed = skill_service.changed_since_taken(session, copies)
    replaced = skill_service.replaced_since_taken(session, copies)
    return tuple(TeamUpdate(name, team, taken, latest, pushed_by, own in changed, own in replaced)
                 for name, team, taken, latest, pushed_by, own, source in rows)


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
