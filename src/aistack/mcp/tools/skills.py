import logging
from inspect import cleandoc
from time import perf_counter
from typing import NotRequired, TypedDict

from fastmcp.server.dependencies import get_http_request

from aistack.bootstrap.context.application_context import (
    get_read_session_factory,
    get_session_factory,
    get_ticket_signer,
)
from aistack.commons.exceptions import ValidationError
from aistack.commons.text import loggable
from aistack.mcp.auth.principal import current_machine
from aistack.mcp.mcp import mcp
from aistack.mcp.mcp_error_handler import handle_mcp_errors
from aistack.mcp.routes.transfer import DOWNLOAD_PATH, UPLOAD_PATH
from aistack.mcp.server_url import server_base_url
from aistack.services import project_service, projects, skill_service
from aistack.services.harnesses import HarnessKey, validated_harness
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


class UploadEntry(TypedDict):
    name: str
    upload_url: str


class RefusedEntry(TypedDict):
    name: str
    reason: str


class PushSkillResult(TypedDict):
    # With name: that skill's URL. With names: one URL per accepted name in uploads, and
    # the rest in refused.
    name: NotRequired[str]
    upload_url: NotRequired[str]
    uploads: NotRequired[list[UploadEntry]]
    refused: NotRequired[list[RefusedEntry]]
    expires_in_seconds: int


@mcp.tool(
    description=cleandoc("""Back up a local skill to the user's own skills. Returns a URL to upload to.

    The Library is private: it mirrors the user's computers. Use this for the skills sync
    listed under backup, and after the user edits one of their skills. To put a skill in front of other people, call share_skill afterwards. Pushing a
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
    The skill is now enabled in this harness on this machine, so sync keeps it current.

    Args:
        name: The skill's name, exactly as in the 'name' field of its SKILL.md frontmatter.
        names: Instead of name, every skill sync listed under backup, in one call.
        origin: The http(s) URL the skill came from, when you know it. Omit it for a skill
               the user wrote themselves.
        harness: The folder it was pushed from, as sync was given. Omit for claude_code.
        project: The project's key, when it was pushed from that project's folder.

    Returns:
        PushSkillResult containing:
            - name: the skill name the upload URL is bound to
            - upload_url: where to PUT the archive. A credential: do not show the user.
            - uploads: with names, a name and upload_url for each, uploaded the same way
            - refused: with names, each name refused and why
            - expires_in_seconds: how long the URLs work
    """))
@handle_mcp_errors
def push_skill(name: str | None = None, names: list[str] | None = None,
               origin: str | None = None, harness: HarnessKey = "claude_code",
               project: str | None = None) -> PushSkillResult:
    caller = current_machine()
    many = one_or_many(name, names)
    origin = validated_origin(origin)
    harness = validated_harness(harness)
    folder = None if project is None else _project_folder(caller, project, harness)
    base = server_base_url(get_http_request())

    def upload_url(skill: str) -> str:
        ticket = get_ticket_signer().sign_upload(UploadTicket(
            machine_id=caller.machine_id,
            user_id=caller.user_id,
            token_prefix=caller.token_prefix,
            skill_name=skill,
            origin=origin,
            harness=harness,
            project_id=None if folder is None else folder.project_id,
        ))
        return f"{base}{UPLOAD_PATH}/{ticket}"

    # Rejected here, a bad name costs one tool call instead of an archive and an upload.
    if many is None:
        name = validated_skill_name(name)
        # The URL carries the ticket, so it is returned and never logged.
        logger.info(f"Upload URL issued. Skill: '{name}'. User: '{caller.user_id}'. "
                    f"Project: '{None if folder is None else folder.project_id}'.")
        return PushSkillResult(name=name, upload_url=upload_url(name),
                               expires_in_seconds=TICKET_LIFETIME_SECONDS)

    uploads, refused = [], []
    for each in many:
        try:
            each = validated_skill_name(each)
        except ValidationError as error:
            refused.append(RefusedEntry(name=loggable(str(each)), reason=error.message))
            continue
        uploads.append(UploadEntry(name=each, upload_url=upload_url(each)))
    logger.info(f"Upload URLs issued. Count: '{len(uploads)}'. Refused: '{len(refused)}'. "
                f"User: '{caller.user_id}'.")
    return PushSkillResult(uploads=uploads, refused=refused,
                           expires_in_seconds=TICKET_LIFETIME_SECONDS)


# More than sync ever lists for backup in one folder would be a mistake, not a backup.
MAX_NAMES = 1000


def one_or_many(name: str | None, names: list[str] | None) -> list[str] | None:
    """None for a push of one `name`, or the `names` of a push of many (IMP-11)."""
    if (name is None) == (names is None):
        raise ValidationError("Give push_skill either name, for one skill, or names, for "
                              "several; not both and not neither.")
    if names is not None and len(names) > MAX_NAMES:
        raise ValidationError(f"names lists {len(names)} skills, and one call takes at most "
                              f"{MAX_NAMES}.")
    return names


class ShareSkillResult(TypedDict):
    name: str
    team: str
    group: str | None
    revision: int
    created: bool
    unchanged: bool
    previous_pushed_by: str | None
    possibly_unrelated: bool
    overwrote_revision: int | None
    updates_from: str | None


@mcp.tool(
    description=cleandoc("""Share one of the user's own skills with a team they are in.

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
      - "overwrote_revision" set: the user's copy was taken from an older team revision,
        and this replaced the team's newer one, last pushed by "previous_pushed_by", which
        the user never took. Say that its changes are no longer in the team's latest.
      - "updates_from" set: the user's copy was taken from that other team and still
        follows it for updates; sharing it here did not change that.

    Args:
        name: The skill's name, one of the user's own.
        team: The team as the user named it. list_teams lists theirs if they did not.
        group: A group inside that team the user belongs to. Omit for the whole team.

    Returns:
        ShareSkillResult containing:
            - name, team, group: where the skill now is
            - revision: its revision number in that team
            - created: true when the team did not have this skill before
            - unchanged, previous_pushed_by, possibly_unrelated, overwrote_revision,
              updates_from: as described above
    """))
@handle_mcp_errors
def share_skill(name: str, team: str, group: str | None = None) -> ShareSkillResult:
    started_at = perf_counter()
    caller = current_machine()

    with get_session_factory().begin() as session:
        shared = skill_service.share(session, caller.user_id, name, team, group)

    logger.debug(f"Skill shared. Skill: '{shared.name}'. Revision: '{shared.revision}'. "
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
        overwrote_revision=shared.overwrote_revision,
        updates_from=shared.updates_from,
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
    description=cleandoc("""List the user's own skills and every skill their teams have shared.

    Use when the user asks what they have or what is available ("what skills does the team
    have?"), or is looking for a skill to do something: this listing is the search. Answer
    in two parts: their own skills (team is null), then each team's. Revisions count
    separately in each place, so a team's number and the user's own say nothing about
    which is newer; sync's team_updates does.

    To install a team's skill on this machine, call get_skill with its name and team: it
    is copied into the user's own skills and stays theirs. To give one of their own to a
    team, call share_skill.

    Args:
        team: Only that team's skills. Omit for the user's own and every team's.
        query: Only skills whose name or description contains these words, in any case.

    Returns:
        ListSkillsResult containing:
            - skills: the user's own first, then by team and name, each with:
                - name: the skill's name
                - team: the team that shares it, or null for one of the user's own
                - group: the group inside that team, or null
                - description: what it does and when an agent should use it
                - revision, pushed_by: its latest revision there and who pushed it
    """))
@handle_mcp_errors
def list_skills(team: str | None = None, query: str | None = None) -> ListSkillsResult:
    started_at = perf_counter()

    with get_read_session_factory().begin() as session:
        skills = skill_service.list_skills(session, current_machine().user_id, team, query)

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
    folder: str
    download_url: str
    expires_in_seconds: int


@mcp.tool(
    description=cleandoc("""Enable a skill on this machine and get a URL to download its files.

    Use to install, update, restore, or re-enable a skill: each means "this folder should
    have the latest revision". It replaces the local folder, so if sync reported local
    edits, the user must have agreed to lose them. With team, the team's latest revision
    is first copied into the user's own skills: that is how a team's skill is installed
    and an offered update accepted. Refused over their own namesake: ask, then replace.

    Prefer `aistack sync` for automatic installs. Manual fallback: use a fresh unique
    directory under <skills>/.aistack-staging per attempt. Download and extract a complete
    revision there; on failure leave installed files alone. Recheck local digests before
    replacement: changed files need a decision. Rename the old folder into this attempt's
    stage, then rename the new one into place. On failure restore the old copy if possible,
    otherwise keep it and report its path. Clean up only this attempt after success.
    Never clear shared staging. Windows: curl.exe and tar.exe. See sync-aistack for details.

    Args:
        name: The skill's name.
        team: The team to take it from ("from backend"). Omit for the user's own.
        harness: The skills folder, as given to sync. Omit for claude_code.
        replace: True once the user agreed to replace their own skill.
        project: A project's key, to install in its folder; folder is then relative.

    Returns:
        GetSkillResult containing:
            - name, description: the skill
            - revision: the revision you are installing
            - version: the author's version string, or null
            - pushed_by: who uploaded this revision, not necessarily its author
            - download_url: the archive, a credential: keep it private
            - expires_in_seconds: how long the URL works
    """))
@handle_mcp_errors
def get_skill(name: str, team: str | None = None,
              harness: HarnessKey = "claude_code", replace: bool = False,
              project: str | None = None) -> GetSkillResult:
    started_at = perf_counter()
    caller = current_machine()
    logger.debug(f"Getting skill. Skill: '{loggable(name)}'. Machine: '{caller.machine_id}'.")

    with get_session_factory().begin() as session:
        folder = None if project is None else project_service.required_folder(
            session, caller.user_id, caller.machine_id, projects.validated_key(project),
            validated_harness(harness))
        skill = skill_service.get_skill(session, caller.machine_id, caller.user_id, name, team,
                                        harness, replace, project_folder=folder)

    ticket = get_ticket_signer().sign_download(DownloadTicket(
        machine_id=caller.machine_id,
        token_prefix=caller.token_prefix,
        skill_version_id=skill.skill_version_id,
    ))

    logger.info(
        f"Skill enabled and download URL issued. Skill: '{skill.name}'. "
        f"Revision: '{skill.revision}'. Machine: '{caller.machine_id}'. "
        f"Harness: '{loggable(harness)}'. "
        f"Project: '{None if folder is None else folder.project_id}'. "
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
        folder=skill.folder,
        download_url=f"{server_base_url(get_http_request())}{DOWNLOAD_PATH}/{ticket}",
        expires_in_seconds=TICKET_LIFETIME_SECONDS,
    )


class DisableSkillResult(TypedDict):
    name: str
    enabled: bool


@mcp.tool(
    description=cleandoc("""Disable a skill in one harness on this machine, so sync stops installing
    and updating it there.

    Use when the user wants a skill removed from this computer ("remove wizard"). This
    records the decision; it does not touch the disk. After it succeeds, delete the skill's
    folder from that harness's skills folder (<folder>/<name>, where claude_code is
    ~/.claude/skills and agents is ~/.agents/skills) to finish the removal.

    The skill stays in their own skills, in this machine's other harnesses, and on their
    other machines. To bring it back here, call get_skill.

    Args:
        name: The skill's name.
        harness: The folder to remove it from, as sync was given. Omit for claude_code.
        project: A project's key, to remove it from that project's folder.

    Returns:
        DisableSkillResult containing:
            - name: the skill that was disabled
            - enabled: always false
    """))
@handle_mcp_errors
def disable_skill(name: str, harness: HarnessKey = "claude_code",
                  project: str | None = None) -> DisableSkillResult:
    started_at = perf_counter()
    caller = current_machine()
    logger.debug(f"Disabling skill. Skill: '{loggable(name)}'. Machine: '{caller.machine_id}'.")

    with get_session_factory().begin() as session:
        folder = None if project is None else project_service.required_folder(
            session, caller.user_id, caller.machine_id, projects.validated_key(project),
            validated_harness(harness))
        disabled = skill_service.disable_skill(session, caller.machine_id, caller.user_id,
                                               name, harness, project_folder=folder)

    logger.info(f"Skill disabled. Skill: '{disabled}'. Machine: '{caller.machine_id}'. "
                f"Harness: '{loggable(harness)}'. "
                f"Project: '{None if folder is None else folder.project_id}'. "
                f"Elapsed: '{(perf_counter() - started_at) * 1000:.0f}ms'.")
    return DisableSkillResult(name=disabled, enabled=False)


def _project_folder(caller, project: str, harness):
    """The project folder a push names, which this computer must manage before a URL is
    minted for it. Read only: the upload checks it again before it writes."""
    with get_read_session_factory().begin() as session:
        return project_service.required_folder(session, caller.user_id, caller.machine_id,
                                               projects.validated_key(project), harness)
