"""Local mode's tools: the same services as the server's, with the disk work done here.

Each call is one transaction, as on the server, and the disk is touched only outside it:
reading a skill before the transaction opens, writing one after it commits. A SQLite
transaction holds the write lock from its first statement, so file I/O inside it would make
every other session on this computer wait.
"""

import logging
import webbrowser
from pathlib import Path
from typing import TypedDict

from aistack.bootstrap.context.application_context import (
    get_local_principal,
    get_read_session_factory,
    get_session_factory,
    library_after_write,
    library_before_read,
    library_problem,
)
from aistack.bundled import SYNC_SKILL_NAME, local_sync_skill_document
from aistack.mcp import local_dashboard
from aistack.mcp.local import local_mcp
from aistack.mcp.mcp_error_handler import handle_mcp_errors
from aistack.mcp.tools.skills import ListSkillsResult, SkillListing
from aistack.mcp.tools.sync import SyncResult, sync_result
from aistack.services import library_log, local_skills, skill_service, sync_service
from aistack.services.harnesses import HarnessKey, validated_harness
from aistack.services.skill_validation import validated_origin, validated_skill_name
from aistack.services.transfer_ticket import DASHBOARD_LINK_LIFETIME_SECONDS

logger = logging.getLogger(__name__)


def _folder(harness: HarnessKey) -> Path:
    return local_skills.skills_folder(validated_harness(harness), Path.home())


class LocalSyncResult(SyncResult):
    folders: list[str]
    harness: str
    library_reachable: bool
    library_problem: str | None


class LocalListSkillsResult(ListSkillsResult):
    library_reachable: bool
    library_problem: str | None


@local_mcp.tool(
    description="""Compare one skills folder on this computer with the user's Library.

    Use when the user says "sync aistack" or starts work. It reads the folder itself and
    changes nothing but AIStack's own sync-aistack skill, which it keeps current. Then, per
    field, passing the same harness to each tool:
      - install and update: call get_skill for each, without asking. Then say what
        updated, between which revisions.
      - backup: skills on this computer not yet in the Library. push_skill each, without
        asking: the Library is private and mirrors this computer.
      - ask: put each to the user and act only on their answer. desired: enabled,
        disabled, or undecided here; local: current, stale, or unknown (edited). Offer
        exactly the listed options. overwrites_local: say local files will be replaced;
        loses_local_edits: say their edits will be lost. edited_from < latest_revision:
        say push replaces another computer's newer edit. enable, restore = get_skill;
        push = push_skill; remove = disable_skill; skip = nothing.
      - up_to_date: how many enabled skills match.
      - folders: every skills folder this computer has an agent for, and harness the one
        this call synced. Sync each of the others too.
      - first_sync: true the first time this folder syncs here. Then call list_skills and
        ask once whether to install the user's own skills that are on no folder here: they
        come from their other computers. See the sync-aistack skill.
      - library_reachable: false when the Library's GitHub repository could not be
        reached, so this compared against this computer's copy. Tell the user
        library_problem, as it is, before anything else.
    team_updates is always empty and sync_skill_url always null here.

    Args:
        harness: claude_code (~/.claude/skills) or agents (~/.agents/skills, read by Codex,
                 Gemini CLI, Cursor and others). Omit for the computer's first folder.
    """)
@handle_mcp_errors
def sync(harness: HarnessKey | None = None) -> LocalSyncResult:
    library_before_read(force=True)
    caller = get_local_principal()
    folders = local_skills.folders_in_use(Path.home())
    # No harness: the first folder this computer has, so a computer with only Codex does not
    # get a Claude Code folder recorded on it.
    harness = harness or (folders[0] if folders else "claude_code")
    folder = _folder(harness)
    local = local_skills.observed(folder)
    # AIStack's own skill, where setup put it, is kept at this release's copy: the server
    # mode equivalent is sync_skill_url, which here would have nowhere to point.
    if SYNC_SKILL_NAME in local:
        local_skills.refresh(folder, SYNC_SKILL_NAME, local_sync_skill_document())

    with get_session_factory().begin() as session:
        report = sync_service.sync(session, caller.machine_id, caller.user_id, local, harness)
        # Only the first sync of a folder is shared: it is what other computers and a rebuilt
        # copy need, and logging every sync would grow the log by one file per session.
        if report.first_sync:
            library_log.record(session, library_log.new_event(
                session, caller.machine_id, library_log.FOLDER_SYNCED, harness=harness))

    library_after_write()
    logger.info(f"Sync reported. Local skills: '{len(local)}'.")
    problem = library_problem()
    return LocalSyncResult(**sync_result(report, sync_skill_url=None), folders=folders,
                           harness=harness, library_reachable=problem is None,
                           library_problem=problem)


@local_mcp.tool(
    description="""List the skills in the user's Library.

    Use when the user asks what they have, or is looking for a skill to do something: this
    listing is the search. To put one on this computer, call get_skill.

    Returns:
        LocalListSkillsResult containing:
            - skills: by name, each with its description, latest revision, and who pushed it
            - library_reachable: false when the Library's GitHub repository could not be
              reached, so this is this computer's copy. Tell the user library_problem.
    """)
@handle_mcp_errors
def list_skills() -> LocalListSkillsResult:
    library_before_read()
    with get_read_session_factory().begin() as session:
        skills = skill_service.list_skills(session, get_local_principal().user_id)

    problem = library_problem()
    return LocalListSkillsResult(library_reachable=problem is None, library_problem=problem,
                                 skills=[
        SkillListing(name=skill.name, team=skill.team, group=skill.group,
                     description=skill.description, revision=skill.revision,
                     pushed_by=skill.pushed_by)
        for skill in skills
    ])


class LocalGetSkillResult(TypedDict):
    name: str
    description: str
    revision: int
    version: str | None
    pushed_by: str
    folder: str


@local_mcp.tool(
    description="""Install the latest revision of a skill from the Library into a skills
    folder on this computer.

    Use to install a skill, update it, restore an edited copy, or re-enable a disabled one.
    It replaces the local folder, so if sync reported local edits, the user must have agreed
    to lose them. The files are checked against the hash they were pushed with before any is
    written, and the folder is swapped in whole, so a failure leaves the old copy in place.
    It is usable without a restart; if it is not found at once, try again.

    Args:
        name: The skill's name, as list_skills or sync reported it.
        harness: The skills folder, as given to sync. Omit for claude_code.

    Returns:
        LocalGetSkillResult containing:
            - name, description: the skill
            - revision: the revision now installed
            - version: the author's version string, or null
            - pushed_by: who uploaded this revision, not necessarily its author
            - folder: where it was installed
    """)
@handle_mcp_errors
def get_skill(name: str, harness: HarnessKey = "claude_code") -> LocalGetSkillResult:
    library_before_read()
    caller = get_local_principal()
    folder = _folder(harness)

    with get_session_factory().begin() as session:
        skill = skill_service.get_skill(session, caller.machine_id, caller.user_id, name,
                                        harness=harness)
        # Installing again what was already installed changes nothing to share. The log is
        # never trimmed, and every rebuild replays it.
        if skill.changed:
            library_log.record(session, library_log.new_event(
                session, caller.machine_id, library_log.SKILL_PLACED, name=skill.name,
                harness=harness, enabled=True, revision=skill.revision))
        _, packed = skill_service.archive_of(session, caller.machine_id, skill.skill_version_id)

    local_skills.install(folder, skill.name, packed, skill.content_hash)
    library_after_write()

    logger.info(f"Skill installed. Skill: '{skill.name}'. Revision: '{skill.revision}'.")
    return LocalGetSkillResult(
        name=skill.name,
        description=skill.description,
        revision=skill.revision,
        version=skill.version,
        pushed_by=skill.pushed_by,
        folder=str(folder / skill.name),
    )


class LocalPushSkillResult(TypedDict):
    name: str
    revision: int
    created: bool
    unchanged: bool
    shared: bool


@local_mcp.tool(
    description="""Back up a skill folder on this computer to the user's Library.

    Use for a skill sync listed under backup, and after the user edits one of their skills.
    The Library is private. Pushing a name it already has adds a revision; nothing is
    overwritten. The skill is then enabled in this folder on this computer, so sync keeps it
    current.

    Args:
        name: The skill's folder name, the same as the 'name' in its SKILL.md frontmatter.
        origin: The http(s) URL the skill came from, when you know it. Omit it for a skill
               the user wrote themselves.
        harness: The skills folder it is in, as given to sync. Omit for claude_code.

    Returns:
        LocalPushSkillResult containing:
            - name, revision: the skill and its revision in the Library now
            - created: true when it was new to the Library
            - unchanged: true when these exact files were already stored, so no revision
              was added. Only content counts: a chmod alone is not a change.
            - shared: false when the Library is on GitHub and this computer could not reach
              it. The revision is kept here and goes out with a later call that reaches it;
              tell the user their other computers get it only then.
    """)
@handle_mcp_errors
def push_skill(name: str, origin: str | None = None,
               harness: HarnessKey = "claude_code") -> LocalPushSkillResult:
    caller = get_local_principal()
    # Validated before it is joined to a path, so a name cannot leave the skills folder.
    name = validated_skill_name(name)
    origin = validated_origin(origin)
    packed = local_skills.archive(_folder(harness), name)

    with get_session_factory().begin() as session:
        pushed = skill_service.push(session, caller.machine_id, caller.user_id, name, origin,
                                    packed, harness)
        # An unchanged push stores no revision, so its archive is not logged again. What it
        # may still change, a removed skill back or this folder enabled, is a placement.
        if not pushed.unchanged:
            library_log.record(session, library_log.pushed(session, caller.machine_id, name,
                                                           origin, harness, packed))
        elif pushed.placement_changed:
            library_log.record(session, library_log.new_event(
                session, caller.machine_id, library_log.SKILL_PLACED, name=pushed.name,
                harness=harness, enabled=True, revision=pushed.revision))

    shared = library_after_write()
    logger.info(f"Skill pushed. Skill: '{pushed.name}'. Revision: '{pushed.revision}'.")
    return LocalPushSkillResult(name=pushed.name, revision=pushed.revision,
                                created=pushed.created, unchanged=pushed.unchanged,
                                shared=shared)


class LocalDisableSkillResult(TypedDict):
    name: str
    enabled: bool
    removed: bool


@local_mcp.tool(
    description="""Remove a skill from one skills folder on this computer, and stop sync
    installing it there.

    Use when the user wants a skill off this computer ("remove wizard"). Its folder is
    deleted; a folder that is a link loses only the link. The skill stays in the Library,
    in the other folder, and on the user's other computers. To bring it back, call get_skill.

    Args:
        name: The skill's name.
        harness: The folder to remove it from, as given to sync. Omit for claude_code.

    Returns:
        LocalDisableSkillResult containing:
            - name: the skill
            - enabled: always false
            - removed: whether a folder was there to delete
    """)
@handle_mcp_errors
def disable_skill(name: str, harness: HarnessKey = "claude_code") -> LocalDisableSkillResult:
    caller = get_local_principal()

    with get_session_factory().begin() as session:
        disabled = skill_service.disable_skill(session, caller.machine_id, caller.user_id,
                                               name, harness)
        library_log.record(session, library_log.new_event(
            session, caller.machine_id, library_log.SKILL_PLACED, name=disabled,
            harness=harness, enabled=False))

    library_after_write()
    # The service returned the stored name, which passed validation when it was pushed.
    removed = local_skills.remove(_folder(harness), disabled)
    logger.info(f"Skill disabled. Skill: '{disabled}'. Removed: '{removed}'.")
    return LocalDisableSkillResult(name=disabled, enabled=False, removed=removed)


class LocalDashboardResult(TypedDict):
    url: str
    expires_in_seconds: int


@local_mcp.tool(
    description="""Open the user's Library in their browser, signed in.

    Use when the user wants to see or manage their skills on a screen ("open my aistack
    dashboard"): every skill in their Library and which of their computers has it. It opens
    the browser itself; also give the user the link, in case it did not. The link signs in
    for a few minutes, and the page runs on this computer for as long as this session does.

    Returns:
        LocalDashboardResult containing:
            - url: the sign-in link. A credential: show it to the user only.
            - expires_in_seconds: how long the link can be used to sign in
    """)
@handle_mcp_errors
def open_dashboard() -> LocalDashboardResult:
    library_before_read()
    url = local_dashboard.dashboard_link()
    try:
        webbrowser.open(url)
    except webbrowser.Error:
        # No browser this process can reach; the agent hands the link over instead.
        pass
    logger.info("Dashboard link issued.")
    return LocalDashboardResult(url=url, expires_in_seconds=DASHBOARD_LINK_LIFETIME_SECONDS)
