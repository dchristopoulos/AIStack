import logging
from time import perf_counter
from typing import TypedDict

from fastmcp.server.dependencies import get_http_request

from aistack.bootstrap.context.application_context import (
    get_session_factory,
    get_ticket_signer,
)
from aistack.commons.text import loggable
from aistack.mcp.auth.principal import current_machine
from aistack.mcp.mcp import mcp
from aistack.mcp.mcp_error_handler import handle_mcp_errors
from aistack.mcp.routes.transfer import DOWNLOAD_PATH, UPLOAD_PATH
from aistack.mcp.server_url import server_base_url
from aistack.services import skill_service
from aistack.services.skill_validation import validated_origin, validated_skill_name
from aistack.services.transfer_ticket import (
    TICKET_LIFETIME_SECONDS,
    DownloadTicket,
    UploadTicket,
)

logger = logging.getLogger(__name__)

# Claude Code diverts a tool result over 50,000 characters to a file unless the tool raises
# its own ceiling. A vault of a few hundred skills with full descriptions passes that, and
# the listing is the only way to discover what the vault holds.
_LISTING_RESULT_MAX_CHARS = 500_000


class PushSkillResult(TypedDict):
    name: str
    upload_url: str
    expires_in_seconds: int


@mcp.tool(
    description="""Back up a local skill to the user's own skills. Returns a URL to upload to.

    "My skills" is private: it mirrors what is on the user's computers, and nobody else sees
    it. Use this for a skill sync listed under backup, and after the user edits one of their
    skills. To put a skill in front of other people, call share_skill afterwards. Pushing a
    name they already have adds a revision; nothing is overwritten. The files are never
    passed to this tool. Upload them from a shell:

        COPYFILE_DISABLE=1 tar -czf <tmp>/skill.tgz --exclude .git -C <skill folder> .
        curl -sS -X PUT --data-binary @<tmp>/skill.tgz "<upload_url>"

    On Windows drop the COPYFILE_DISABLE=1 prefix and use tar.exe and curl.exe. Delete the
    .tgz afterwards.

    curl prints the result as JSON. An "error" field means nothing was stored and says what
    to fix. Otherwise:
      - "unchanged" true: these exact files were already stored, so no revision was added.
        Only content counts: a chmod alone is not a change.
      - otherwise it is now revision "revision" of the user's own skill.
    The skill is now enabled for this machine, so sync will keep it current.

    Args:
        name: The skill's name, exactly as in the 'name' field of its SKILL.md frontmatter.
        origin: The http(s) URL the skill came from, when you know it. Omit it for a skill
               the user wrote themselves.

    Returns:
        PushSkillResult containing:
            - name: the skill name the upload URL is bound to
            - upload_url: where to PUT the archive. A credential: do not show the user.
            - expires_in_seconds: how long the URL works
    """)
@handle_mcp_errors
def push_skill(name: str, origin: str | None = None) -> PushSkillResult:
    caller = current_machine()
    logger.debug(f"Preparing push. Skill: '{loggable(name)}'. User: '{caller.user_id}'.")

    # Rejected here, a bad name costs one tool call instead of an archive and an upload.
    name = validated_skill_name(name)
    origin = validated_origin(origin)

    ticket = get_ticket_signer().sign_upload(UploadTicket(
        machine_id=caller.machine_id,
        user_id=caller.user_id,
        skill_name=name,
        origin=origin,
    ))

    # The URL carries the ticket, so it is returned and never logged.
    logger.info(f"Upload URL issued. Skill: '{name}'. User: '{caller.user_id}'.")
    return PushSkillResult(
        name=name,
        upload_url=f"{server_base_url(get_http_request())}{UPLOAD_PATH}/{ticket}",
        expires_in_seconds=TICKET_LIFETIME_SECONDS,
    )


class ShareSkillResult(TypedDict):
    name: str
    team: str
    group: str | None
    revision: int
    created: bool
    unchanged: bool
    previous_pushed_by: str | None
    possibly_unrelated: bool


@mcp.tool(
    description="""Share one of the user's own skills with a team they are in.

    Use when the user wants teammates to have a skill ("share wizard with backend"). The
    team gets its own copy of the skill's latest revision, and its members see who shared
    it. Nothing is uploaded: the skill must already be in the user's own skills, so call
    push_skill first if sync lists it under backup or the user just edited it.

    Sharing a name the team already has adds a revision there. Any member may do that.
    Tell the user the team and revision, and:
      - "unchanged" true: the team already had exactly this.
      - "possibly_unrelated" true: the team already had a skill of this name, last pushed
        by "previous_pushed_by", that the user's copy was never taken from. Say plainly
        that this may have replaced a different skill that shares the name.

    Args:
        name: The skill's name, one of the user's own.
        team: A team the user is in, as list_teams names it.
        group: A group inside that team the user belongs to. Omit for the whole team.

    Returns:
        ShareSkillResult containing:
            - name, team, group: where the skill now is
            - revision: its revision number in that team
            - created: true when the team did not have this skill before
            - unchanged, previous_pushed_by, possibly_unrelated: as described above
    """)
@handle_mcp_errors
def share_skill(name: str, team: str, group: str | None = None) -> ShareSkillResult:
    started_at = perf_counter()
    caller = current_machine()

    with get_session_factory().begin() as session:
        shared = skill_service.share(session, caller.user_id, name, team, group)

    logger.info(f"Skill shared. Skill: '{shared.name}'. Revision: '{shared.revision}'. "
                f"User: '{caller.user_id}'. "
                f"Elapsed: '{(perf_counter() - started_at) * 1000:.0f}ms'.")
    return ShareSkillResult(
        name=shared.name,
        team=shared.team,
        group=shared.group,
        revision=shared.revision,
        created=shared.created,
        unchanged=shared.unchanged,
        previous_pushed_by=shared.previous_pushed_by,
        possibly_unrelated=shared.possibly_unrelated,
    )


class SkillListing(TypedDict):
    name: str
    team: str | None
    group: str | None
    description: str
    revision: int
    pushed_by: str


class ListSkillsResult(TypedDict):
    skills: list[SkillListing]


@mcp.tool(
    meta={"anthropic/maxResultSizeChars": _LISTING_RESULT_MAX_CHARS},
    description="""List the user's own skills and every skill their teams have shared.

    Use when the user asks what they have or what is available ("what skills does the team
    have?"), or is looking for a skill to do something: this listing is the search. Answer
    in two parts: their own skills (team is null), then each team's.

    To install a team's skill on this machine, call get_skill with its name and team: it
    is copied into the user's own skills and stays theirs. To give one of their own to a
    team, call share_skill.

    Returns:
        ListSkillsResult containing:
            - skills: the user's own first, then by team and name, each with:
                - name: the skill's name
                - team: the team that shares it, or null for one of the user's own
                - group: the group inside that team, or null
                - description: what it does and when an agent should use it
                - revision, pushed_by: its latest revision there and who pushed it
    """)
@handle_mcp_errors
def list_skills() -> ListSkillsResult:
    started_at = perf_counter()

    with get_session_factory().begin() as session:
        skills = skill_service.list_skills(session, current_machine().user_id)

    logger.info(f"Skills listed. Count: '{len(skills)}'. "
                f"Elapsed: '{(perf_counter() - started_at) * 1000:.0f}ms'.")
    return ListSkillsResult(skills=[
        SkillListing(name=skill.name, team=skill.team, group=skill.group,
                     description=skill.description, revision=skill.revision,
                     pushed_by=skill.pushed_by)
        for skill in skills
    ])


class SkillFileEntry(TypedDict):
    path: str
    sha256: str
    executable: bool


class GetSkillResult(TypedDict):
    name: str
    description: str
    revision: int
    version: str | None
    pushed_by: str
    content_hash: str
    files: list[SkillFileEntry]
    download_url: str
    expires_in_seconds: int


@mcp.tool(
    description="""Enable a skill on this machine and get a URL to download its files.

    Use to install a skill, update it, restore an edited copy, or re-enable a disabled one:
    each means "this machine should have the latest revision". It replaces the local
    folder, so if sync reported local edits, the user must have agreed to lose them. With
    team, the team's latest revision is first copied into the user's own skills: that is
    how a team's skill is installed, and how an update sync offered is accepted.

    The files are not in this result. Install them from a shell, where <skills> is
    ~/.claude/skills and <stage> is <skills>/.aistack-staging:

        curl -sS -o <stage>/<name>.tgz "<download_url>"
        mkdir <stage>/<name>, then: tar -xzf <stage>/<name>.tgz -C <stage>/<name>
        remove <skills>/<name> if it exists, then move <stage>/<name> to <skills>/<name>
        delete <stage>/<name>.tgz

    Create <stage> first and clear any leftover <stage>/<name>. If tar fails, the .tgz is a
    JSON error message: read it. On Windows the commands are curl.exe and tar.exe. The
    final move is a rename, so a failed download never leaves half a skill in place, and
    the skill is usable as soon as it completes. tar restores file modes, so run no chmod.
    Leave <stage> itself in place; sync ignores it. The listed hashes need no checking.

    Args:
        name: The skill's name, as list_skills or sync reported it.
        team: Omit for one of the user's own. Name a team to take its copy.

    Returns:
        GetSkillResult containing:
            - name, description: the skill
            - revision: the revision you are installing
            - version: the author's version string, or null
            - pushed_by: who uploaded this revision, not necessarily its author
            - content_hash, files: its hash, and each file's path, sha256, executable bit
            - download_url: where to GET the archive. A credential: keep it private.
            - expires_in_seconds: how long the URL works
    """)
@handle_mcp_errors
def get_skill(name: str, team: str | None = None) -> GetSkillResult:
    started_at = perf_counter()
    caller = current_machine()
    logger.debug(f"Getting skill. Skill: '{loggable(name)}'. Machine: '{caller.machine_id}'.")

    with get_session_factory().begin() as session:
        skill = skill_service.get_skill(session, caller.machine_id, caller.user_id, name, team)

    ticket = get_ticket_signer().sign_download(DownloadTicket(
        machine_id=caller.machine_id,
        skill_version_id=skill.skill_version_id,
    ))

    logger.info(
        f"Skill enabled and download URL issued. Skill: '{skill.name}'. "
        f"Revision: '{skill.revision}'. Machine: '{caller.machine_id}'. "
        f"Elapsed: '{(perf_counter() - started_at) * 1000:.0f}ms'."
    )
    return GetSkillResult(
        name=skill.name,
        description=skill.description,
        revision=skill.revision,
        version=skill.version,
        pushed_by=skill.pushed_by,
        content_hash=skill.content_hash,
        files=[SkillFileEntry(path=file.path, sha256=file.sha256, executable=file.executable)
               for file in skill.files],
        download_url=f"{server_base_url(get_http_request())}{DOWNLOAD_PATH}/{ticket}",
        expires_in_seconds=TICKET_LIFETIME_SECONDS,
    )


class DisableSkillResult(TypedDict):
    name: str
    enabled: bool


@mcp.tool(
    description="""Disable a skill on this machine, so sync stops installing and updating it.

    Use when the user wants a skill removed from this computer ("remove wizard"). This
    records the decision; it does not touch the disk. After it succeeds, delete the skill's
    folder from the global skills directory (~/.claude/skills/<name>) to finish the removal.

    The skill stays in their own skills and on their other machines. To bring it back here,
    call get_skill.

    Args:
        name: The skill's name.

    Returns:
        DisableSkillResult containing:
            - name: the skill that was disabled
            - enabled: always false
    """)
@handle_mcp_errors
def disable_skill(name: str) -> DisableSkillResult:
    started_at = perf_counter()
    caller = current_machine()
    logger.debug(f"Disabling skill. Skill: '{loggable(name)}'. Machine: '{caller.machine_id}'.")

    with get_session_factory().begin() as session:
        disabled = skill_service.disable_skill(session, caller.machine_id, caller.user_id,
                                               name)

    logger.info(f"Skill disabled. Skill: '{disabled}'. Machine: '{caller.machine_id}'. "
                f"Elapsed: '{(perf_counter() - started_at) * 1000:.0f}ms'.")
    return DisableSkillResult(name=disabled, enabled=False)
