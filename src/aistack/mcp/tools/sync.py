import logging
from time import perf_counter
from typing import TypedDict

from fastmcp.server.dependencies import get_http_request

from aistack.bootstrap.context.application_context import get_session_factory
from aistack.bundled import SYNC_SKILL_NAME
from aistack.commons.text import loggable
from aistack.mcp.auth.principal import current_machine
from aistack.mcp.mcp import mcp
from aistack.mcp.mcp_error_handler import handle_mcp_errors
from aistack.mcp.routes.setup import SETUP_PATH
from aistack.mcp.server_url import server_base_url
from aistack.services import sync_service
from aistack.services.harnesses import HarnessKey

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


class TeamUpdateEntry(TypedDict):
    name: str
    team: str
    from_revision: int
    to_revision: int
    pushed_by: str


class SyncResult(TypedDict):
    install: list[InstallEntry]
    update: list[UpdateEntry]
    ask: list[AskEntry]
    backup: list[str]
    team_updates: list[TeamUpdateEntry]
    up_to_date: int
    sync_skill_url: str | None
    first_sync: bool


@mcp.tool(
    description="""Compare one skills folder on this machine with the user's own skills.

    Use when the user says "sync aistack" or starts work. It changes nothing. Send every
    skill folder in <folder> (harness claude_code: ~/.claude/skills; agents:
    ~/.agents/skills) with the sha256 of each file, paths relative to the skill's folder.
    Skip 'synced', dot-folders, and .DS_Store. Get digests from a shell:

        cd <folder> && find -L . -mindepth 2 -type f ! -name .DS_Store \\
          ! -path './.*' ! -path './synced/*' -exec shasum -a 256 {} +
        Windows: Get-ChildItem <folder> -Recurse -File | Get-FileHash

    Then, per field of the result, passing the same harness to each tool:
      - install and update: call get_skill and install, without asking. Then say what
        updated, between which revisions, and who pushed it.
      - backup: local skills not yet in the user's own skills. push_skill each, without
        asking: that space is private and mirrors this computer. Nothing is shared.
      - ask: put each to the user and act only on their answer. desired: enabled,
        disabled, or undecided here; local: current, stale, or unknown (edited). Offer
        exactly the listed options. overwrites_local: say local files will be replaced;
        loses_local_edits: say their edits will be lost. enable, restore = get_skill and
        install; push = push_skill; remove = delete the folder; skip = nothing.
      - team_updates: a team has a newer version of a skill the user took from it. Ask
        each time. Yes = get_skill with that team, and install.
      - up_to_date: how many enabled skills match.
      - sync_skill_url: null, or where the server's own sync-aistack skill is. Without
        asking, curl -sS -o it to <folder>/sync-aistack/SKILL.md.
      - first_sync: true the first time this folder syncs here. See the sync-aistack skill.

    Args:
        local: {skill folder: {relative file path: sha256 hex}}. {} if there are none.
        harness: Which folder this is. Omit for claude_code.
    """)
@handle_mcp_errors
def sync(local: dict[str, dict[str, str]],
         harness: HarnessKey = "claude_code") -> SyncResult:
    started_at = perf_counter()
    caller = current_machine()

    with get_session_factory().begin() as session:
        report = sync_service.sync(session, caller.machine_id, caller.user_id, local, harness)

    sync_skill_url = None
    if report.refresh_sync_skill:
        sync_skill_url = (f"{server_base_url(get_http_request())}{SETUP_PATH}/"
                          f"{SYNC_SKILL_NAME}/SKILL.md")

    logger.info(
        f"Sync reported. Machine: '{caller.machine_id}'. Harness: '{loggable(harness)}'. "
        f"Local skills: '{len(local)}'. "
        f"Install: '{len(report.install)}'. Update: '{len(report.update)}'. "
        f"Ask: '{len(report.ask)}'. Backup: '{len(report.backup)}'. "
        f"Team updates: '{len(report.team_updates)}'. "
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
        backup=list(report.backup),
        team_updates=[TeamUpdateEntry(name=entry.name, team=entry.team,
                                      from_revision=entry.from_revision,
                                      to_revision=entry.to_revision,
                                      pushed_by=entry.pushed_by)
                      for entry in report.team_updates],
        up_to_date=report.up_to_date,
        sync_skill_url=sync_skill_url,
        first_sync=report.first_sync,
    )
