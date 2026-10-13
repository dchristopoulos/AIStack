import logging
from time import perf_counter
from typing import TypedDict

from fastmcp.server.dependencies import get_http_request

from aistack.bootstrap.context.application_context import get_session_factory
from aistack.bundled import SYNC_SKILL_NAME
from aistack.mcp.auth.principal import current_machine
from aistack.mcp.mcp import mcp
from aistack.mcp.mcp_error_handler import handle_mcp_errors
from aistack.mcp.routes.setup import SETUP_PATH
from aistack.mcp.server_url import server_base_url
from aistack.services import sync_service

logger = logging.getLogger(__name__)


class InstallEntry(TypedDict):
    name: str
    revision: int
    pushed_by: str


class UpdateEntry(TypedDict):
    name: str
    from_revision: int
    to_revision: int
    pushed_by: str


class OptionEntry(TypedDict):
    choice: str
    overwrites_local: bool
    loses_local_edits: bool


class AskEntry(TypedDict):
    name: str
    desired: str
    local: str
    local_revision: int | None
    latest_revision: int
    pushed_by: str
    options: list[OptionEntry]


class SyncResult(TypedDict):
    install: list[InstallEntry]
    update: list[UpdateEntry]
    ask: list[AskEntry]
    orphans: list[str]
    up_to_date: int
    sync_skill_url: str | None


@mcp.tool(
    description="""Compare this machine's skills with the vault and report what to do.

    Use when the user says "sync aistack" or starts work. It changes nothing. Send every
    folder in the global skills directory (~/.claude/skills) with the sha256 of each file,
    paths relative to the skill's folder. Skip 'synced', dot-folders, and .DS_Store. Get
    digests from a shell, never by reading files:

        cd ~/.claude/skills && find -L . -mindepth 2 -type f ! -name .DS_Store \\
          ! -path './.*' ! -path './synced/*' -exec shasum -a 256 {} +
        Windows: Get-ChildItem $HOME\\.claude\\skills -Recurse -File | Get-FileHash

    Then, per field of the result:
      - install (name, revision, pushed_by) and update (name, from_revision, to_revision,
        pushed_by): call get_skill and install, without asking. Then tell the user what
        updated, between which revisions, and who pushed it.
      - ask (name, desired, local, local_revision, latest_revision, pushed_by, options):
        put each to the user and act only on their answer. desired is enabled, disabled,
        or undecided for this machine; local is current, stale (an older revision), or
        unknown (edited). Offer exactly the listed options. If one has overwrites_local,
        say local files will be replaced; if it has loses_local_edits, say their edits
        will be lost. enable, restore = get_skill and install; push = push_skill; remove =
        delete the local folder; skip = nothing.
      - orphans: local skills the vault has never seen. Offer to push; never push unasked.
      - up_to_date: how many enabled skills already match the vault.
      - sync_skill_url: null, or where the server's own sync-aistack skill is, because the
        local one is missing or differs. Without asking, curl -sS -o it to
        ~/.claude/skills/sync-aistack/SKILL.md (create the folder first).

    Args:
        local: {skill folder: {relative file path: sha256 hex}}. {} if there are none.
    """)
@handle_mcp_errors
def sync(local: dict[str, dict[str, str]]) -> SyncResult:
    started_at = perf_counter()
    caller = current_machine()

    with get_session_factory().begin() as session:
        report = sync_service.sync(session, caller.machine_id, local)

    sync_skill_url = None
    if report.refresh_sync_skill:
        sync_skill_url = (f"{server_base_url(get_http_request())}{SETUP_PATH}/"
                          f"{SYNC_SKILL_NAME}/SKILL.md")

    logger.info(
        f"Sync reported. Machine: '{caller.machine_id}'. Local skills: '{len(local)}'. "
        f"Install: '{len(report.install)}'. Update: '{len(report.update)}'. "
        f"Ask: '{len(report.ask)}'. Orphans: '{len(report.orphans)}'. "
        f"Up to date: '{report.up_to_date}'. "
        f"Elapsed: '{(perf_counter() - started_at) * 1000:.0f}ms'."
    )
    return SyncResult(
        install=[InstallEntry(name=entry.name, revision=entry.revision,
                              pushed_by=entry.pushed_by) for entry in report.install],
        update=[UpdateEntry(name=entry.name, from_revision=entry.from_revision,
                            to_revision=entry.to_revision, pushed_by=entry.pushed_by)
                for entry in report.update],
        ask=[
            AskEntry(
                name=question.name,
                desired=question.desired.value,
                local=question.local.value,
                local_revision=question.local_revision,
                latest_revision=question.latest_revision,
                pushed_by=question.pushed_by,
                options=[OptionEntry(choice=option.choice.value,
                                     overwrites_local=option.overwrites_local,
                                     loses_local_edits=option.loses_local_edits)
                         for option in question.options],
            )
            for question in report.ask
        ],
        orphans=list(report.orphans),
        up_to_date=report.up_to_date,
        sync_skill_url=sync_skill_url,
    )
