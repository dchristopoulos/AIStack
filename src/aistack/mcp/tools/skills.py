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
    description="""Start pushing a local skill to the vault. Returns a URL to upload it to.

    Use when the user wants to share or back up a skill ("push my wizard skill to aistack").
    Pushing a name the vault already has adds a new revision; nothing is overwritten. The
    skill's files are never passed to this tool. Upload them in two shell commands:

        tar -czf <tmp>/skill.tgz -C <skill folder> .
        curl -sS -X PUT --data-binary @<tmp>/skill.tgz "<upload_url>"

    On macOS put COPYFILE_DISABLE=1 before tar. On Windows the commands are tar.exe and
    curl.exe. Leave .git out with --exclude .git. Delete the .tgz afterwards.

    curl prints the result as JSON. An "error" field means nothing was stored: it says what
    to fix. Otherwise report "revision", and:
      - "unchanged" true: the vault already held exactly these files; nothing was added.
      - "created" false and "same_origin" false: tell the user plainly that the vault
        already had a skill by this name, last pushed by "previous_pushed_by", and that
        this may be an unrelated skill sharing the name.
    The skill is now enabled for this machine, so sync will keep it current.

    Args:
        name: The skill's name, exactly as in the 'name' field of its SKILL.md frontmatter.
        origin: Where the skill came from, when you know it (a repository or page URL).
               Omit it for a skill the user wrote themselves.

    Returns:
        PushSkillResult containing:
            - name: the skill name the upload URL is bound to
            - upload_url: where to PUT the archive. It is a credential: use it once, and do
                         not repeat it to the user.
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


class SkillListing(TypedDict):
    name: str
    description: str


class ListSkillsResult(TypedDict):
    skills: list[SkillListing]


@mcp.tool(
    meta={"anthropic/maxResultSizeChars": _LISTING_RESULT_MAX_CHARS},
    description="""List every skill in the team's vault, with its description.

    Use when the user asks what is available ("what skills does the team have?") or is
    looking for a skill to do something: this listing is the search. It is the only way to
    discover skills; sync reports only on skills this machine already manages. To install
    one, call get_skill with its name.

    Returns:
        ListSkillsResult containing:
            - skills: one entry per skill, sorted by name, each with:
                - name: the skill's name, used with get_skill and disable_skill
                - description: what it does and when an agent should use it
    """)
@handle_mcp_errors
def list_skills() -> ListSkillsResult:
    started_at = perf_counter()

    with get_session_factory().begin() as session:
        skills = skill_service.list_skills(session)

    logger.info(f"Skills listed. Count: '{len(skills)}'. "
                f"Elapsed: '{(perf_counter() - started_at) * 1000:.0f}ms'.")
    return ListSkillsResult(skills=[
        SkillListing(name=skill.name, description=skill.description) for skill in skills
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
    description="""Enable a vault skill on this machine and get a URL to download its files.

    Use to install a skill, update it, restore a locally edited copy, or re-enable one that
    was disabled: each means "this machine should have the latest revision". It replaces the
    local folder, so if sync reported local edits, the user must have agreed to lose them.

    The files are not in this result. Install them with shell commands, where <skills> is
    the global skills directory (~/.claude/skills) and <stage> is <skills>/.aistack-staging:

        curl -sS -o <stage>/<name>.tgz "<download_url>"
        mkdir <stage>/<name>, then: tar -xzf <stage>/<name>.tgz -C <stage>/<name>
        remove <skills>/<name> if it exists, then move <stage>/<name> to <skills>/<name>
        delete <stage>/<name>.tgz

    Create <stage> first and clear any leftover <stage>/<name>. If tar fails, the .tgz is a
    JSON error message: read it. On Windows the commands are curl.exe and tar.exe. Staging
    inside the skills directory makes the final move a rename, so a failed download never
    leaves half a skill in place. The skill is usable as soon as the move completes.

    Args:
        name: The skill's name, as list_skills or sync reported it.

    Returns:
        GetSkillResult containing:
            - name, description: the skill
            - revision: the vault's revision number for what you are installing
            - version: the author's own version string, or null if they gave none
            - pushed_by: who uploaded this revision (not necessarily who wrote it)
            - content_hash: the vault's hash of this revision
            - files: each file's path, sha256, and whether it is executable
            - download_url: where to GET the archive. A credential: do not show the user.
            - expires_in_seconds: how long the URL works
    """)
@handle_mcp_errors
def get_skill(name: str) -> GetSkillResult:
    started_at = perf_counter()
    caller = current_machine()
    logger.debug(f"Getting skill. Skill: '{loggable(name)}'. Machine: '{caller.machine_id}'.")

    with get_session_factory().begin() as session:
        skill = skill_service.get_skill(session, caller.machine_id, name)

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

    The skill stays in the vault and on the user's other machines. To bring it back here,
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
        disabled = skill_service.disable_skill(session, caller.machine_id, name)

    logger.info(f"Skill disabled. Skill: '{disabled}'. Machine: '{caller.machine_id}'. "
                f"Elapsed: '{(perf_counter() - started_at) * 1000:.0f}ms'.")
    return DisableSkillResult(name=disabled, enabled=False)
