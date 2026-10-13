import logging
from typing import TypedDict

from fastmcp.server.dependencies import get_http_request

from aistack.bootstrap.context.application_context import get_ticket_signer
from aistack.commons.text import loggable
from aistack.mcp.auth.principal import current_machine
from aistack.mcp.mcp import mcp
from aistack.mcp.mcp_error_handler import handle_mcp_errors
from aistack.mcp.routes.transfer import UPLOAD_PATH
from aistack.mcp.server_url import server_base_url
from aistack.services.skill_validation import validated_origin, validated_skill_name
from aistack.services.transfer_ticket import TICKET_LIFETIME_SECONDS, UploadTicket

logger = logging.getLogger(__name__)


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
