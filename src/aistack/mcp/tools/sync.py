import logging
from time import perf_counter
from typing import TypedDict

from aistack.bootstrap.context.application_context import get_session_factory
from aistack.mcp.auth.principal import current_machine
from aistack.mcp.mcp import mcp
from aistack.mcp.mcp_error_handler import handle_mcp_errors
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


class SyncResult(TypedDict):
    install: list[InstallEntry]
    update: list[UpdateEntry]
    up_to_date: int


@mcp.tool(
    description="""Compare this machine's skills with the vault and report what to do.

    Use when the user says "sync aistack", and when they start work. It changes nothing and
    returns no files: it reports, and you act on the report with get_skill.

    Send every skill folder in the global skills directory (~/.claude/skills) with the
    sha256 of each file in it. Leave out the 'synced' folder, folders starting with a dot,
    and .DS_Store files. Paths are relative to the skill's own folder. Get the digests from
    a shell, never by reading the files:

        macOS/Linux: cd ~/.claude/skills && find -L . -mindepth 2 -type f -exec shasum -a 256 {} +
        Windows:     Get-ChildItem $HOME\\.claude\\skills -Recurse -File | Get-FileHash

    Then, for each entry:
      - install: call get_skill and install it. No need to ask first.
      - update: call get_skill and install it. No need to ask first, but tell the user
        afterwards which skills changed, from which revision to which, and who pushed.

    Args:
        local: {skill folder name: {relative file path: sha256 hex}} for every local skill.
              Send {} if the skills directory is empty.

    Returns:
        SyncResult containing:
            - install: enabled skills missing from this machine (name, revision, pushed_by)
            - update: enabled skills whose local copy is an older revision (name,
                     from_revision, to_revision, pushed_by)
            - up_to_date: how many enabled skills already match the vault
    """)
@handle_mcp_errors
def sync(local: dict[str, dict[str, str]]) -> SyncResult:
    started_at = perf_counter()
    caller = current_machine()

    with get_session_factory().begin() as session:
        report = sync_service.sync(session, caller.machine_id, local)

    logger.info(
        f"Sync reported. Machine: '{caller.machine_id}'. Local skills: '{len(local)}'. "
        f"Install: '{len(report.install)}'. Update: '{len(report.update)}'. "
        f"Up to date: '{report.up_to_date}'. "
        f"Elapsed: '{(perf_counter() - started_at) * 1000:.0f}ms'."
    )
    return SyncResult(
        install=[InstallEntry(name=entry.name, revision=entry.revision,
                              pushed_by=entry.pushed_by) for entry in report.install],
        update=[UpdateEntry(name=entry.name, from_revision=entry.from_revision,
                            to_revision=entry.to_revision, pushed_by=entry.pushed_by)
                for entry in report.update],
        up_to_date=report.up_to_date,
    )
