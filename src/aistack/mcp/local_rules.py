"""Rules in local mode (ADR-0036, ADR-0039): what `aistack sync` does with them on a server,
done here against the Library this process opened.

The program's own code reads and writes every file (`server_sync.observed_rules` and
`apply_rules`), so each agent's file for every project, the person's rules in each project this
computer added, Codex's override and the files turned off follow exactly the rules they do in
server mode. The two transfers it makes over HTTP there are served here in-process, each in a
transaction of its own as a transfer route serves one, and a file kept in the Library is
recorded as the log events that replay it. Files are read before each transaction and written
after it commits.
"""

import asyncio
import subprocess
from dataclasses import asdict
from pathlib import Path

from aistack.bootstrap.context.application_context import (
    get_local_principal,
    get_read_session_factory,
    get_session_factory,
    library_after_write,
)
from aistack.bootstrap.sync_lock import locked
from aistack.commons.exceptions import AIStackError
from aistack.mcp.tools.sync import rule_entry
from aistack.services import library_log, repository_work, rule_sync, server_sync, visibility
from aistack.services.reconciliation import Step
from aistack.services.rule_validation import validated_rule_text
from aistack.services.skill_service import require_registered_machine


def sync_rules(home: Path, choices: dict[str, str]) -> list[dict]:
    """Bring this computer's rule files in line with the Library, carrying out `choices`, the
    person's answers by question key. Returns the program's rule reports: what was done, what
    failed, and the questions left, keyed `<project>:<key>` for a project's files."""
    with locked(home):
        reports = asyncio.run(_sync(home, choices))
    if any(report["completed"] for report in reports):
        library_after_write()
    return reports


def needs_attention(reports: list[dict]) -> bool:
    return any(report["rule_questions"] or report["failures"] for report in reports)


async def _sync(home: Path, choices: dict[str, str]) -> list[dict]:
    caller = get_local_principal()
    transfers = _Transfers(caller)
    with get_read_session_factory().begin() as session:
        listed = library_log.listed_here(session, caller.machine_id)
    reports = [await _pass(transfers, home, None, None, choices)]
    for key, folder in sorted(listed.items()):
        try:
            top = repository_work.working_copy(folder, key, caller.machine_id, home)
        except (OSError, subprocess.SubprocessError, AIStackError):
            # Moved or gone: the page shows the project's files unread until it is added again.
            continue
        done = await _pass(transfers, home, key, top, server_sync.choices_for(choices, key))
        # A question's key names its project: the same rule name can be in two.
        for question in done["rule_questions"]:
            question["key"] = f"{key}:{question['key']}"
        reports.append(done | {"project_group": str(top)})
    return reports


async def _pass(transfers: "_Transfers", home: Path, key: str | None, top: Path | None,
                choices: dict[str, str]) -> dict:
    """The files for every project, or with `key` this computer's files for that project."""
    rules = server_sync.observed_rules(home, top)
    observed = rule_sync.validated_observation(rules.observation)
    caller = transfers.caller
    with get_session_factory().begin() as session:
        project = None if key is None else visibility.my_project(session, caller.user_id, key)
        report = rule_sync.reconcile(session, caller.machine_id, caller.user_id, observed,
                                     project)
    if key is not None and project is None:
        return {"completed": [], "failures": [], "diagnostics": [], "rule_questions": [],
                "rules": True, "folder": "rules", "harness": "rules"}
    rules.entries = [
        rule_entry(action, transfers.url(action, key) if action.may_write else None,
                   transfers.url(action, key) if action.may_keep else None)
        for action in report.actions if (action.place == rule_sync.PROJECT) == (key is not None)]
    rules.repository_files = [{"path": file.path, "agent": file.agent.value,
                               "turned_off": file.turned_off}
                              for file in report.repository_files]
    rules.top = top
    return await server_sync.apply_rules(transfers, rules, choices)


class _Response:
    def __init__(self, content: bytes = b"", body: dict | None = None):
        self.content, self.body = content, body

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self.body


class _Transfers:
    """The rule download and upload `apply_rules` makes over HTTP on a server, served here.
    A URL is an index into this sync's own actions, never anything a caller chose."""

    def __init__(self, caller):
        self.caller = caller
        self.actions: dict[str, tuple[rule_sync.RuleAction, str | None]] = {}

    def url(self, action: rule_sync.RuleAction, key: str | None) -> str:
        url = f"aistack-local:{len(self.actions)}"
        self.actions[url] = (action, key)
        return url

    async def get(self, url: str) -> _Response:
        action, _ = self.actions[url]
        with get_session_factory().begin() as session:
            _, text = rule_sync.revision_text(session, self._machine(session),
                                              action.rule_revision_id, action.agent)
        return _Response(text.encode("utf-8"))

    async def put(self, url: str, content: bytes) -> _Response:
        action, key = self.actions[url]
        try:
            text = validated_rule_text(content.decode("utf-8"))
        except UnicodeDecodeError:
            return _Response(body={"error": "The file is not UTF-8 text, so it was not stored. "
                                            "Save it as UTF-8 and sync again."})
        except AIStackError as error:
            return _Response(body={"error": error.message})
        try:
            with get_session_factory().begin() as session:
                library_log.refuse_when_moved(session)
                machine = self._machine(session)
                project = None if key is None else visibility.required_my_project(
                    session, machine.user_id, key)

                def log(kind: str, **data) -> None:
                    library_log.record(session, library_log.new_event(
                        session, machine.machine_id, kind, **data))

                saved = rule_sync.keep(session, machine, project, action.name, action.agent,
                                       action.step is Step.BACKUP, text, log)
        except AIStackError as error:
            return _Response(body={"error": error.message})
        return _Response(body=asdict(saved))

    def _machine(self, session):
        return require_registered_machine(session, self.caller.machine_id, self.caller.user_id,
                                          None)
