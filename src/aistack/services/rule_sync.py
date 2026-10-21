"""Rules on a computer (ADR-0036): what sync does with each agent's rule files there, and the
two transfers that carry a rule's text.

A computer reports, for each agent it has that AIStack writes rules for, the digest of that
agent's file for every project and of each of the person's rule files in the project it syncs
in. It never reports a path: where each file lives follows from the agent, the place and the
rule's name through `services/agent_files.py`, on the computer. Each file is reconciled by
`reconciliation.reconcile_rule`. Rule text never crosses MCP: it moves through the transfer
routes, and is never logged.
"""

import logging
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from aistack.commons.exceptions import NotFound, ValidationError
from aistack.commons.text import loggable
from aistack.db.models.coding_agent import CodingAgent
from aistack.db.models.machine import Machine
from aistack.db.models.machine_project import MachineProject
from aistack.db.models.project import Project
from aistack.db.models.project_file import ProjectFile
from aistack.db.models.rule import MachineRule, Rule, RuleAgent, RuleRevision
from aistack.db.models.user import User
from aistack.db.models.value_set import known
from aistack.services import agent_files, library_log, rule_service, skill_service, visibility
from aistack.services.content_hash import text_hash
from aistack.services.reconciliation import (
    Choice,
    Desired,
    Observed,
    Option,
    Step,
    reconcile_rule,
)
from aistack.services.rule_validation import validated_rule_name
from aistack.services.transfer_ticket import RuleDownloadTicket, RuleUploadTicket

logger = logging.getLogger(__name__)

EVERY_PROJECT = "every_project"
PROJECT = "project"
PLACES = (EVERY_PROJECT, PROJECT)
# Far beyond the person's rules for one project, and a ceiling on what one call looks up.
MAX_RULE_FILES = 1000
_DIGEST_MAX_LENGTH = 128

# The name a hand-written file for every project is kept under when sync first backs it up.
BACKUP_NAMES = {
    CodingAgent.CLAUDE_CODE: "claude-md",
    CodingAgent.CODEX: "codex-agents-md",
}


@dataclass(frozen=True)
class ObservedFile:
    agent: CodingAgent
    place: str
    # The rule a project file belongs to, from its name on disk; None for an agent's file
    # for every project, which is the whole file whatever rule it holds.
    name: str | None
    # sha256 of the file's bytes, or None when it is not there.
    digest: str | None


@dataclass(frozen=True)
class RuleAction:
    agent: CodingAgent
    place: str
    name: str
    step: Step
    # What the Library wants in this file: None for a file with no rule, which is backed up.
    desired: Desired | None
    local: Observed
    # The rule's latest revision, and the one the file matches; None where there is none.
    revision: int | None
    local_revision: int | None
    # For a file that matches no revision: the one this computer last had, which it was
    # edited from. Older than `revision` means it was edited on the page too.
    edited_from: int | None
    pushed_by: str | None
    options: tuple[Option, ...]
    removed_from_library: bool
    # What a download URL serves: the latest revision.
    rule_revision_id: uuid.UUID | None
    project_id: uuid.UUID | None
    rule_id: uuid.UUID | None = None

    @property
    def may_write(self) -> bool:
        """Whether the Library's text may be written into this file: a download URL."""
        return self.step in (Step.INSTALL, Step.UPDATE) or Choice.RESTORE in {
            option.choice for option in self.options}

    @property
    def may_keep(self) -> bool:
        """Whether this file's text may be kept in the Library: an upload URL."""
        return self.step is Step.BACKUP or Choice.PUSH in {option.choice
                                                            for option in self.options}


@dataclass(frozen=True)
class RepositoryFile:
    """One of the repository's agent files, and whether the person turned it off for
    themselves."""

    path: str
    agent: CodingAgent
    turned_off: bool


@dataclass(frozen=True)
class RuleReport:
    actions: tuple[RuleAction, ...]
    repository_files: tuple[RepositoryFile, ...]


@dataclass(frozen=True)
class _Revision:
    rule_revision_id: uuid.UUID
    revision: int
    content_hash: str
    pushed_by: str


def validated_observation(raw: object) -> list[ObservedFile]:
    """The rule files a computer reported. Pure; called before the transaction."""
    if not isinstance(raw, list):
        raise ValidationError("rules is a list of files, each with agent, place, name and "
                              "digest.")
    if len(raw) > MAX_RULE_FILES:
        raise ValidationError(f"sync received {len(raw)} rule files, and the limit is "
                              f"{MAX_RULE_FILES}.")
    writable = agent_files.agents_writing_rules()
    files: list[ObservedFile] = []
    seen: set[tuple] = set()
    for entry in raw:
        if not isinstance(entry, dict):
            raise ValidationError("Each rule file is an object with agent, place, name and "
                                  "digest.")
        agent, place = entry.get("agent"), entry.get("place")
        name, digest = entry.get("name"), entry.get("digest")
        if agent not in {member.value for member in writable}:
            raise ValidationError("A rule file's agent is one of "
                                  f"{', '.join(member.value for member in writable)}. "
                                  f"Received: '{loggable(agent)}'.")
        if place not in PLACES:
            raise ValidationError(f"A rule file's place is {' or '.join(PLACES)}. Received: "
                                  f"'{loggable(place)}'.")
        if place == EVERY_PROJECT:
            if name is not None:
                raise ValidationError("An agent's file for every project is the whole file, "
                                      "so it has no name. Send null.")
        else:
            name = validated_rule_name(name)
        if digest is not None:
            if not isinstance(digest, str) or len(digest) > _DIGEST_MAX_LENGTH:
                raise ValidationError("A rule file's digest is the sha256 of its bytes, in "
                                      "hex, or null when it is not there.")
            # Unrecognized digests match no revision, which is the safe answer: a question.
            digest = digest.strip().lower()
        key = (agent, place, name)
        if key in seen:
            raise ValidationError(f"rules lists {agent}'s {place.replace('_', ' ')} file "
                                  f"'{name or ''}' twice.")
        seen.add(key)
        files.append(ObservedFile(CodingAgent(agent), place, name, digest))
    return files


def reconcile(session: Session, machine_id: uuid.UUID, user_id: uuid.UUID,
              observed: Sequence[ObservedFile], project: Project | None) -> RuleReport:
    """One action per rule file on this computer.

    The agents here are the ones whose file for every project was reported, present or not.
    `project` is the project the computer syncs in, when it manages it, and one
    `visibility.my_project` returned; project files are ignored without it. The one thing
    this writes is which revision a file that already matches the latest one holds.
    """
    every = {entry.agent: entry.digest for entry in observed if entry.place == EVERY_PROJECT}
    if not every:
        return RuleReport((), ())
    agents_here = [agent for agent in agent_files.agents_writing_rules() if agent in every]
    in_project = {(entry.agent, entry.name): entry.digest for entry in observed
                  if entry.place == PROJECT and entry.agent in every} if project else {}

    where = Rule.project_id.is_(None)
    if project is not None:
        where = where | (Rule.project_id == project.project_id)
    rules = list(session.scalars(visibility.my_rules(user_id).where(where)
                                 .order_by(Rule.name)))
    ids = [rule.rule_id for rule in rules]
    used_for: dict[uuid.UUID, set[CodingAgent]] = {}
    for rule_id, agent in session.execute(select(RuleAgent.rule_id, RuleAgent.agent).where(
            RuleAgent.rule_id.in_(ids), known(RuleAgent.agent))):
        used_for.setdefault(rule_id, set()).add(agent)
    history: dict[uuid.UUID, list[_Revision]] = {}
    for row in session.execute(
            select(RuleRevision.rule_id, RuleRevision.rule_revision_id, RuleRevision.revision,
                   RuleRevision.content_hash, User.username)
            .join(User, User.user_id == RuleRevision.pushed_by)
            .where(RuleRevision.rule_id.in_(ids)).order_by(RuleRevision.revision)):
        history.setdefault(row.rule_id, []).append(
            _Revision(row.rule_revision_id, row.revision, row.content_hash, row.username))
    had = {(rule_id, agent): revision for rule_id, agent, revision in session.execute(
        select(MachineRule.rule_id, MachineRule.agent, MachineRule.revision).where(
            MachineRule.machine_id == machine_id, MachineRule.rule_id.in_(ids),
            known(MachineRule.agent)))}

    def wanted(rule: Rule, agent: CodingAgent) -> bool:
        return not rule.archived and agent in used_for.get(rule.rule_id, set())

    actions: list[RuleAction] = []
    everywhere = [rule for rule in rules if rule.project_id is None]
    for agent in agents_here:
        digest = every[agent]
        # Each agent takes at most one rule for every project (rule_service._use_for). Without
        # one, the rule this computer last had there says the file is no longer wanted.
        rule = next((rule for rule in everywhere if wanted(rule, agent)), None) or next(
            (rule for rule in everywhere if (rule.rule_id, agent) in had), None)
        if rule is None:
            if digest is not None:
                actions.append(_new(agent, EVERY_PROJECT, BACKUP_NAMES[agent], None))
            continue
        actions.extend(_reconciled(rule, agent, EVERY_PROJECT, wanted(rule, agent), digest,
                                   history, had))

    if project is not None:
        by_name = {rule.name: rule for rule in rules if rule.project_id == project.project_id}
        for agent in agents_here:
            if agent_files.AGENT_FILES[agent].personal_project_rule is None:
                continue
            names = {name for name, rule in by_name.items() if wanted(rule, agent)}
            names |= {name for listed, name in in_project if listed is agent}
            for name in sorted(names):
                rule, digest = by_name.get(name), in_project.get((agent, name))
                if rule is None:
                    if digest is not None:
                        actions.append(_new(agent, PROJECT, name, project.project_id))
                    continue
                actions.extend(_reconciled(rule, agent, PROJECT, wanted(rule, agent), digest,
                                           history, had))

    for action in actions:
        if action.local is Observed.CURRENT and had.get(
                (action.rule_id, action.agent)) != action.revision:
            _record(session, machine_id, action.rule_id, action.agent, action.revision)

    repository = () if project is None else tuple(
        RepositoryFile(path, agent, turned_off) for path, agent, turned_off in session.execute(
            select(ProjectFile.path, ProjectFile.agent, ProjectFile.turned_off)
            .where(ProjectFile.project_id == project.project_id,
                   ProjectFile.agent.is_not(None), known(ProjectFile.agent))
            .order_by(ProjectFile.path)))
    return RuleReport(tuple(actions), repository)


def _new(agent: CodingAgent, place: str, name: str, project_id: uuid.UUID | None) -> RuleAction:
    """A file with no rule in the Library: backed up without asking, because that space is
    private."""
    return RuleAction(agent, place, name, Step.BACKUP, None, Observed.UNKNOWN, None, None, None,
                      None, (), False, None, project_id)


def _reconciled(rule: Rule, agent: CodingAgent, place: str, wanted: bool, digest: str | None,
                history: dict[uuid.UUID, list[_Revision]],
                had: dict[tuple[uuid.UUID, CodingAgent], int | None]) -> list[RuleAction]:
    revisions = history.get(rule.rule_id)
    if not revisions:
        return []
    latest = revisions[-1]
    local_revision = edited_from = None
    if digest is None:
        observed = Observed.ABSENT
    elif digest == latest.content_hash:
        observed, local_revision = Observed.CURRENT, latest.revision
    else:
        older = next((revision for revision in reversed(revisions[:-1])
                      if revision.content_hash == digest), None)
        if older is not None:
            observed, local_revision = Observed.STALE, older.revision
        else:
            edited_from = had.get((rule.rule_id, agent))
            observed = Observed.EDITED if edited_from == latest.revision else Observed.UNKNOWN
    desired = Desired.ENABLED if wanted else Desired.DISABLED
    verdict = reconcile_rule(desired, observed)
    if not wanted and observed is Observed.ABSENT:
        # Not wanted and not there: there is no file to report.
        return []
    return [RuleAction(agent, place, rule.name, verdict.step, desired, observed,
                       latest.revision, local_revision, edited_from, latest.pushed_by,
                       verdict.options, removed_from_library=rule.archived,
                       rule_revision_id=latest.rule_revision_id,
                       project_id=rule.project_id, rule_id=rule.rule_id)]


def _record(session: Session, machine_id: uuid.UUID, rule_id: uuid.UUID, agent: CodingAgent,
            revision: int | None) -> None:
    """Remember the revision this computer's file for this agent now holds."""
    statement = select(MachineRule).where(MachineRule.machine_id == machine_id,
                                          MachineRule.rule_id == rule_id,
                                          MachineRule.agent == agent)
    row = session.scalar(statement)
    if row is None:
        try:
            # A savepoint, so two syncs at once cost a re-read and not the report.
            with session.begin_nested():
                session.add(MachineRule(machine_id=machine_id, rule_id=rule_id, agent=agent,
                                        revision=revision))
            return
        except IntegrityError:
            row = session.scalar(statement)
    row.revision = revision


def text_of(session: Session, ticket: RuleDownloadTicket) -> tuple[str, str]:
    """The rule name and text of the revision a download URL names, recorded as what this
    computer's file for that agent holds from now on, as `get_skill` records an install."""
    machine = skill_service.require_registered_machine(session, ticket.machine_id, None,
                                                       ticket.token_prefix)
    return revision_text(session, machine, ticket.rule_revision_id, ticket.agent)


def revision_text(session: Session, machine: Machine, rule_revision_id: uuid.UUID,
                  agent: CodingAgent) -> tuple[str, str]:
    """`text_of` for a computer already checked: local mode's sync calls it directly."""
    row = session.execute(
        select(RuleRevision.rule_id, RuleRevision.revision, RuleRevision.text)
        .where(RuleRevision.rule_revision_id == rule_revision_id)).one_or_none()
    rule = None if row is None else session.scalar(
        visibility.my_rules(machine.user_id).where(Rule.rule_id == row.rule_id))
    # A computer writes only its own person's rules, so a ticket for anything else is not one
    # this server issued to it.
    if rule is None:
        raise NotFound("The rule revision this transfer URL points at no longer exists. Run "
                       "aistack sync again.")
    _record(session, machine.machine_id, rule.rule_id, agent, row.revision)
    return rule.name, row.text


def store(session: Session, ticket: RuleUploadTicket, text: str) -> rule_service.Saved:
    """Keep the text of a file on a computer as a rule's next revision, or as a new rule.

    A text that looks like it holds a credential is not stored (`saved` false), as on the
    page: the person saves it there once they have looked.
    """
    machine = skill_service.require_registered_machine(session, ticket.machine_id,
                                                       ticket.user_id, ticket.token_prefix)
    project = None
    if ticket.project_id is not None:
        project = session.get(Project, ticket.project_id)
        # Checked again here: the URL outlives the sync that minted it.
        managed = project is not None and project.user_id == machine.user_id and session.scalar(
            select(MachineProject.machine_project_id).where(
                MachineProject.machine_id == machine.machine_id,
                MachineProject.project_id == project.project_id).limit(1)) is not None
        if not managed:
            raise NotFound("This project is no longer managed on this computer, so nothing "
                           "was stored.")
    return keep(session, machine, project, ticket.rule_name, ticket.agent, ticket.backup, text)


def keep(session: Session, machine: Machine, project: Project | None, name: str,
         agent: CodingAgent, backup: bool, text: str,
         log: Callable[..., None] | None = None) -> rule_service.Saved:
    """`store` for a computer and project already checked. `log(kind, **data)` hears each
    change as the Library log event that replays it, for local mode (ADR-0039)."""
    user_id = machine.user_id
    key = None if project is None else project.key
    rule = visibility.my_rule(session, user_id, name, project)
    if rule is None and project is None and backup:
        # The same text as a rule for every project already in the Library, as when one file
        # links to the other: the rule is used for this agent too, not kept twice.
        rule = _same_text(session, user_id, text)
    if rule is None or rule.archived:
        saved = rule_service.create(session, user_id, name, text, project=key,
                                    agents=[agent.value])
        if saved.saved and log:
            log(library_log.RULE_CREATED, name=saved.name, project=key, text=text,
                agents=[agent.value])
        rule = visibility.my_rule(session, user_id, name, project)
    else:
        saved = rule_service.edit(session, user_id, rule.name, text, project=key)
        if saved.saved and not saved.unchanged and log:
            log(library_log.RULE_EDITED, name=rule.name, project=key, text=text)
        agents = set(session.scalars(select(RuleAgent.agent).where(
            RuleAgent.rule_id == rule.rule_id, known(RuleAgent.agent))))
        if saved.saved and backup and agent not in agents:
            agents = rule_service.set_agents(session, user_id, rule.name,
                                             [each.value for each in agents | {agent}],
                                             project=key)
            if log:
                log(library_log.RULE_AGENTS_SET, name=rule.name, project=key, agents=agents)
    if saved.saved:
        _record(session, machine.machine_id, rule.rule_id, agent, saved.revision)
    return saved


def _same_text(session: Session, user_id: uuid.UUID, text: str) -> Rule | None:
    content_hash = text_hash(text)
    for rule in session.scalars(visibility.my_rules(user_id).where(
            Rule.project_id.is_(None), Rule.archived.is_(False)).order_by(Rule.name)):
        latest = session.scalar(select(RuleRevision.content_hash)
                                .where(RuleRevision.rule_id == rule.rule_id)
                                .order_by(RuleRevision.revision.desc()).limit(1))
        if latest == content_hash:
            return rule
    return None
