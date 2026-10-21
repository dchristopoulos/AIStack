import logging
from inspect import cleandoc
from time import perf_counter
from typing import NotRequired, TypedDict

from fastmcp.server.dependencies import get_http_request

from aistack.bootstrap.context.application_context import get_session_factory, get_ticket_signer
from aistack.bundled import SYNC_SKILL_NAME
from aistack.commons.exceptions import ValidationError
from aistack.commons.text import loggable
from aistack.mcp.auth.principal import current_machine
from aistack.mcp.mcp import mcp
from aistack.mcp.mcp_error_handler import handle_mcp_errors
from aistack.mcp.routes.setup import SETUP_PATH
from aistack.mcp.routes.transfer import (
    PROJECT_FILE_EDIT_PATH,
    PROJECT_FILE_UPLOAD_PATH,
    RULE_DOWNLOAD_PATH,
    RULE_UPLOAD_PATH,
)
from aistack.mcp.server_url import server_base_url
from aistack.services import (
    computer_fingerprint,
    project_file_service,
    projects,
    rule_sync,
    sync_service,
    visibility,
)
from aistack.services.harnesses import HarnessKey
from aistack.services.reconciliation import Choice, Step
from aistack.services.transfer_ticket import (
    ProjectFileEditTicket,
    ProjectFileUploadTicket,
    RuleDownloadTicket,
    RuleUploadTicket,
)

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
    edited_from: int | None
    latest_revision: int
    pushed_by: str
    options: list[OptionEntry]
    removed_from_library: bool


class CannotBackUpEntry(TypedDict):
    name: str
    reason: str


class TeamUpdateEntry(TypedDict):
    name: str
    team: str
    from_revision: int
    to_revision: int
    pushed_by: str
    own_changes: bool
    different_skill: bool


class ProjectEntry(TypedDict):
    key: str
    name: str
    managed: bool


class Here(TypedDict):
    path: str
    remote: str | None


class RuleFile(TypedDict):
    agent: str
    place: str
    name: str | None
    digest: str | None


class RuleEntry(TypedDict):
    agent: str
    place: str
    name: str
    action: str
    desired: str | None
    local: str
    revision: int | None
    local_revision: int | None
    edited_from: int | None
    pushed_by: str | None
    options: list[OptionEntry]
    removed_from_library: bool
    download_url: str | None
    upload_url: str | None


class RepositoryFileEntry(TypedDict):
    path: str
    agent: str
    turned_off: bool


class ListedFile(TypedDict):
    path: str
    size: int


class TickedFileEntry(TypedDict):
    path: str
    content_hash: str | None
    upload_url: str


class EditEntry(TypedDict):
    path: str
    base_hash: str
    content_hash: str
    note: str | None
    url: str


class SyncResult(TypedDict):
    machine_id: NotRequired[str]
    # Only when the caller sent `rules`: older programs see nothing new.
    rules: NotRequired[list[RuleEntry]]
    repository_files: NotRequired[list[RepositoryFileEntry]]
    ticked_files: NotRequired[list[TickedFileEntry]]
    edits: NotRequired[list[EditEntry]]
    install: list[InstallEntry]
    update: list[UpdateEntry]
    ask: list[AskEntry]
    backup: list[str]
    cannot_back_up: list[CannotBackUpEntry]
    team_updates: list[TeamUpdateEntry]
    up_to_date: int
    sync_skill_url: str | None
    first_sync: bool
    project: ProjectEntry | None
    left_to_repository: list[str]
    from_other_computers: list[str]


@mcp.tool(
    description=cleandoc("""Compare one skills folder on this machine with the user's own skills.

    Use when the user says "sync aistack" or starts work. It changes nothing. Send every
    skill folder in <folder> (harness claude_code: ~/.claude/skills; agents:
    ~/.agents/skills, or the same under a project's top level) with the sha256 of each
    file, as the sync-aistack skill says. Skip 'synced', dot-folders, .git and .DS_Store.

    Per result field, passing the same harness and project on:
      - install and update: get_skill and install each, without asking. Say what
        updated, between which revisions, and who pushed it.
      - backup: local skills not yet in the user's own. push_skill them all as names,
        without asking: that space is private.
      - ask: put each to the user; act only on their answer. desired: enabled,
        disabled, or undecided here; local: current, stale, or unknown (edited). Offer
        exactly the listed options. overwrites_local: say local files will be replaced;
        loses_local_edits: say their edits will be lost. edited_from < latest_revision:
        say push replaces another computer's newer edit. enable, restore = get_skill
        and install; push = push_skill; remove = delete the folder; skip = nothing.
      - team_updates: a team's newer version of a skill the user took. Ask; yes =
        get_skill with that team, and install.
      - up_to_date: how many enabled skills match.
      - sync_skill_url: when set, curl -sS --create-dirs -o <folder>/sync-aistack/SKILL.md
        it, without asking.
      - first_sync: do step 5 of <folder>/sync-aistack/SKILL.md.
      - cannot_back_up, project, left_to_repository, from_other_computers, and
        removed_from_library in ask: as the sync-aistack skill says.

    Args:
        local: {skill folder: {relative file path: sha256 hex}}. {} if there are none.
        harness: Which folder this is. Omit for claude_code.
        here, project, repository: a project's folder, as the sync-aistack skill says.
    """))
@handle_mcp_errors
def sync(local: dict[str, dict[str, str]],
         harness: HarnessKey = "claude_code", here: Here | None = None,
         project: str | None = None, repository: list[str] | None = None,
         fingerprint: str | None = None, identify: bool = False,
         rules: list[RuleFile] | None = None,
         project_files: list[ListedFile] | None = None) -> SyncResult:
    started_at = perf_counter()
    caller = current_machine()
    fingerprint = computer_fingerprint.validated(fingerprint)
    if identify:
        if fingerprint is not None:
            with get_session_factory().begin() as session:
                computer_fingerprint.bind(session, caller.machine_id, caller.user_id, fingerprint)
        # Identity discovery consumes no first-sync choice and performs no disk action.
        return SyncResult(
            machine_id=str(caller.machine_id),
            install=[],
            update=[],
            ask=[],
            backup=[],
            cannot_back_up=[],
            team_updates=[],
            up_to_date=0,
            sync_skill_url=None,
            first_sync=False,
            project=None,
            left_to_repository=[],
            from_other_computers=[],
        )
    # Checked before the transaction. A remote can carry a token: it is never logged, and
    # only the key made from it is kept.
    where = None if here is None else projects.validated_here(here.get("path"),
                                                               here.get("remote"))
    observed = None if rules is None else rule_sync.validated_observation(rules)
    listing = None if project_files is None else project_file_service.validated_listing(
        project_files)
    if listing is not None and project is None:
        raise ValidationError("project_files lists a project's files; send it with project.")
    rule_report = work = None

    with get_session_factory().begin() as session:
        computer_fingerprint.bind(session, caller.machine_id, caller.user_id, fingerprint)
        report = sync_service.sync(session, caller.machine_id, caller.user_id, local, harness,
                                   here=where, project=project, repository=repository or ())
        if listing is not None:
            project_file_service.record_listing(
                session, visibility.my_project(session, caller.user_id, report.project.key),
                listing)
        if observed is not None:
            # Project rules only where this computer manages the project it syncs in.
            managed = None if report.project is None or not report.project.managed else (
                visibility.my_project(session, caller.user_id, report.project.key))
            rule_report = rule_sync.reconcile(session, caller.machine_id, caller.user_id,
                                              observed, managed)
            if managed is not None:
                work = project_file_service.work(session, caller.machine_id, managed)

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
        f"Up to date: '{report.up_to_date}'. Project folder: '{project is not None}'. "
        f"Elapsed: '{(perf_counter() - started_at) * 1000:.0f}ms'."
    )
    result = sync_result(report, sync_skill_url)
    result["machine_id"] = str(caller.machine_id)
    if rule_report is not None:
        result["rules"] = [_rule_entry(caller, action) for action in rule_report.actions]
        result["repository_files"] = [
            RepositoryFileEntry(path=file.path, agent=file.agent.value,
                                turned_off=file.turned_off)
            for file in rule_report.repository_files]
        result["ticked_files"], result["edits"] = _project_work(caller, work)
    return result


def _project_work(caller, work) -> tuple[list[TickedFileEntry], list[EditEntry]]:
    """The managed project's ticked files and the edits waiting for this computer, each with
    the transfer URL it needs. The URLs carry tickets, so they are returned and never logged."""
    if work is None:
        return [], []
    base, signer = server_base_url(get_http_request()), get_ticket_signer()
    files = [TickedFileEntry(
        path=file.path, content_hash=file.content_hash,
        upload_url=f"{base}{PROJECT_FILE_UPLOAD_PATH}/" + signer.sign_project_file_upload(
            ProjectFileUploadTicket(machine_id=caller.machine_id,
                                    token_prefix=caller.token_prefix,
                                    project_file_id=file.project_file_id)))
        for file in work.files]
    edits = [EditEntry(
        path=edit.path, base_hash=edit.base_hash, content_hash=edit.content_hash,
        note=edit.note,
        url=f"{base}{PROJECT_FILE_EDIT_PATH}/" + signer.sign_project_file_edit(
            ProjectFileEditTicket(machine_id=caller.machine_id,
                                  token_prefix=caller.token_prefix,
                                  project_file_edit_id=edit.project_file_edit_id)))
        for edit in work.edits]
    return files, edits


def _rule_entry(caller, action: rule_sync.RuleAction) -> RuleEntry:
    """One rule file's action, with the transfer URLs it may need: a download where the
    Library's text may be written, an upload where the file's text may be kept. The URLs
    carry tickets, so they are returned and never logged."""
    choices = {option.choice for option in action.options}
    base = server_base_url(get_http_request())
    download = upload = None
    if action.step in (Step.INSTALL, Step.UPDATE) or Choice.RESTORE in choices:
        ticket = get_ticket_signer().sign_rule_download(RuleDownloadTicket(
            machine_id=caller.machine_id, token_prefix=caller.token_prefix,
            rule_revision_id=action.rule_revision_id, agent=action.agent))
        download = f"{base}{RULE_DOWNLOAD_PATH}/{ticket}"
    if action.step is Step.BACKUP or Choice.PUSH in choices:
        ticket = get_ticket_signer().sign_rule_upload(RuleUploadTicket(
            machine_id=caller.machine_id, user_id=caller.user_id,
            token_prefix=caller.token_prefix, rule_name=action.name, agent=action.agent,
            project_id=action.project_id, backup=action.step is Step.BACKUP))
        upload = f"{base}{RULE_UPLOAD_PATH}/{ticket}"
    return RuleEntry(
        agent=action.agent.value,
        place=action.place,
        name=action.name,
        action=action.step.value,
        desired=None if action.desired is None else action.desired.value,
        local=action.local.value,
        revision=action.revision,
        local_revision=action.local_revision,
        edited_from=action.edited_from,
        pushed_by=action.pushed_by,
        options=[OptionEntry(choice=option.choice.value,
                             overwrites_local=option.overwrites_local,
                             loses_local_edits=option.loses_local_edits)
                 for option in action.options],
        removed_from_library=action.removed_from_library,
        download_url=download,
        upload_url=upload,
    )


def sync_result(report: sync_service.SyncReport, sync_skill_url: str | None) -> SyncResult:
    """The report as the tool returns it; local mode's sync returns the same shape."""
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
                edited_from=question.edited_from,
                latest_revision=question.latest_revision,
                pushed_by=question.pushed_by,
                options=[OptionEntry(choice=option.choice.value,
                                     overwrites_local=option.overwrites_local,
                                     loses_local_edits=option.loses_local_edits)
                         for option in question.options],
                removed_from_library=question.removed_from_library,
            )
            for question in report.ask
        ],
        backup=list(report.backup),
        cannot_back_up=[CannotBackUpEntry(name=entry.name, reason=entry.reason)
                        for entry in report.cannot_back_up],
        team_updates=[TeamUpdateEntry(name=entry.name, team=entry.team,
                                      from_revision=entry.from_revision,
                                      to_revision=entry.to_revision,
                                      pushed_by=entry.pushed_by,
                                      own_changes=entry.own_changes,
                                      different_skill=entry.different_skill)
                      for entry in report.team_updates],
        up_to_date=report.up_to_date,
        sync_skill_url=sync_skill_url,
        first_sync=report.first_sync,
        project=None if report.project is None else ProjectEntry(
            key=report.project.key, name=report.project.name, managed=report.project.managed),
        left_to_repository=list(report.left_to_repository),
        from_other_computers=list(report.from_other_computers),
    )
