"""Rules kept in the Library (ADR-0036): the person's rules for every project and their rules
for one project, each with immutable revisions and the agents it is used for.

Every function takes the caller's `user_id` and reaches a rule only through `visibility`, so
another person's rule, or one in another person's project, reads as one that does not exist.
Text is never logged.
"""

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Select, delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from aistack.commons.exceptions import Conflict
from aistack.db.models.coding_agent import CodingAgent
from aistack.db.models.project import Project
from aistack.db.models.rule import Rule, RuleAgent, RuleRevision
from aistack.db.models.team import Team
from aistack.db.models.timestamps import as_utc
from aistack.db.models.user import User
from aistack.db.models.value_set import known
from aistack.db.ordering import bytewise
from aistack.services import agent_files, projects, visibility
from aistack.services.content_hash import text_hash
from aistack.services.rule_validation import (
    credential_lines,
    validated_agents,
    validated_rule_name,
    validated_rule_text,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Saved:
    name: str
    # False when the text looks like it holds a credential and the caller did not confirm:
    # nothing was stored, and `credential_lines` says which lines to look at.
    saved: bool
    credential_lines: list[int]
    revision: int | None = None
    # True when the text was the latest revision's already, so no revision was added.
    unchanged: bool = False


def create(session: Session, user_id: uuid.UUID, name: str, text: str,
           project: str | None = None, agents: list[str] | None = None,
           confirmed: bool = False) -> Saved:
    """Keep a new rule in the Library, for every project or for one of the user's projects.

    A rule of that name the user removed comes back with this text as its newest revision.
    """
    name, text = validated_rule_name(name), validated_rule_text(text)
    chosen = validated_agents([] if agents is None else agents)
    project = None if project is None else projects.validated_key(project)
    lines = credential_lines(text)
    if lines and not confirmed:
        return Saved(name, saved=False, credential_lines=lines)

    found = None if project is None else visibility.required_my_project(session, user_id,
                                                                        project)
    rule = visibility.my_rule(session, user_id, name, found)
    if rule is not None and not rule.archived:
        raise Conflict(f"You already have a rule named '{name}' {_where(found)}. Edit it, or "
                       "pick another name.")
    if rule is None:
        rule = Rule(team_id=visibility.personal_team(session, user_id).team_id,
                    project_id=None if found is None else found.project_id, name=name,
                    pushed_by=user_id)
        try:
            with session.begin_nested():
                session.add(rule)
        except IntegrityError:
            raise Conflict(f"You already have a rule named '{name}' {_where(found)}. Edit "
                           "it, or pick another name.") from None
    else:
        rule.archived = False
        session.execute(delete(RuleAgent).where(RuleAgent.rule_id == rule.rule_id))
    _use_for(session, user_id, rule, chosen)
    revision, _ = _new_revision(session, user_id, rule, text)
    logger.info(f"Rule saved. Rule: '{name}'. For a project: '{found is not None}'. "
                f"Revision: '{revision}'. User: '{user_id}'.")
    return Saved(name, saved=True, credential_lines=lines, revision=revision)


def edit(session: Session, user_id: uuid.UUID, name: str, text: str,
         project: str | None = None, confirmed: bool = False) -> Saved:
    """Save new text for one of the user's rules as a new revision. Every computer that has
    it writes it at its next sync."""
    text = validated_rule_text(text)
    project = None if project is None else projects.validated_key(project)
    lines = credential_lines(text)
    if lines and not confirmed:
        return Saved(validated_rule_name(name), saved=False, credential_lines=lines)
    rule, _ = visibility.required_my_rule(session, user_id, name, project)
    revision, added = _new_revision(session, user_id, rule, text)
    if added:
        logger.info(f"Rule edited. Rule: '{rule.name}'. Revision: '{revision}'. "
                    f"User: '{user_id}'.")
    return Saved(rule.name, saved=True, credential_lines=lines, revision=revision,
                 unchanged=not added)


def rename(session: Session, user_id: uuid.UUID, name: str, new_name: str,
           project: str | None = None) -> str:
    """Give one of the user's rules a new name, unique among their rules in the same place."""
    new_name = validated_rule_name(new_name)
    project = None if project is None else projects.validated_key(project)
    rule, found = visibility.required_my_rule(session, user_id, name, project)
    if new_name == rule.name:
        return new_name
    taken = visibility.my_rule(session, user_id, new_name, found)
    if taken is not None:
        removed = " that you removed" if taken.archived else ""
        raise Conflict(f"You already have a rule named '{new_name}'{removed} {_where(found)}. "
                       "Pick another name.")
    try:
        with session.begin_nested():
            rule.name = new_name
    except IntegrityError:
        raise Conflict(f"You already have a rule named '{new_name}' {_where(found)}. Pick "
                       "another name.") from None
    logger.info(f"Rule renamed. Rule: '{new_name}'. User: '{user_id}'.")
    return new_name


def archive(session: Session, user_id: uuid.UUID, name: str, project: str | None = None) -> str:
    """Remove one of the user's rules from the Library. The row stays, so sync does not back
    the file on a computer up again as a new rule; the files on disk are left as they are."""
    project = None if project is None else projects.validated_key(project)
    rule, _ = visibility.required_my_rule(session, user_id, name, project)
    rule.archived = True
    logger.info(f"Rule removed. Rule: '{rule.name}'. User: '{user_id}'.")
    return rule.name


def set_agents(session: Session, user_id: uuid.UUID, name: str, agents: list[str],
               project: str | None = None) -> list[str]:
    """Choose the agents one of the user's rules is used for, replacing the choice before."""
    chosen = validated_agents(agents)
    project = None if project is None else projects.validated_key(project)
    rule, _ = visibility.required_my_rule(session, user_id, name, project)
    session.execute(delete(RuleAgent).where(RuleAgent.rule_id == rule.rule_id))
    _use_for(session, user_id, rule, chosen)
    logger.info(f"Rule's agents set. Rule: '{rule.name}'. Agents: "
                f"'{','.join(agent.value for agent in chosen)}'. User: '{user_id}'.")
    return [agent.value for agent in chosen]


def text_of(session: Session, user_id: uuid.UUID, name: str,
            project: str | None = None) -> dict[str, Any]:
    """The latest text of one of the user's rules, with the lines that look like a
    credential."""
    project = None if project is None else projects.validated_key(project)
    rule, found = visibility.required_my_rule(session, user_id, name, project)
    revision, text = session.execute(
        select(RuleRevision.revision, RuleRevision.text)
        .where(RuleRevision.rule_id == rule.rule_id)
        .order_by(RuleRevision.revision.desc()).limit(1)).one()
    return {"name": rule.name, "project": None if found is None else found.key,
            "revision": revision, "text": text, "credential_lines": credential_lines(text)}


def rules(session: Session, user_id: uuid.UUID, project: str | None = None) -> list[dict]:
    """The user's rules for every project, or, with `project`, their rules for that one."""
    if project is None:
        return _listed(session, user_id, Rule.project_id.is_(None))
    found = visibility.required_my_project(session, user_id, projects.validated_key(project))
    return _listed(session, user_id, Rule.project_id == found.project_id)


def all_rules(session: Session, user_id: uuid.UUID) -> list[dict]:
    """Both kinds at once, for the page: every project's first, then by project and name."""
    return _listed(session, user_id, None)


def _listed(session: Session, user_id: uuid.UUID, where: Any) -> list[dict]:
    mine = visibility.my_rules(user_id).where(Rule.archived.is_(False))
    if where is not None:
        mine = mine.where(where)
    mine = mine.subquery()
    newest = _newest(select(mine.c.rule_id))
    rows = session.execute(
        select(mine.c.rule_id, mine.c.name, Project.key, newest.c.revision,
               newest.c.pushed_by, newest.c.created_on)
        .join(newest, newest.c.rule_id == mine.c.rule_id)
        .outerjoin(Project, Project.project_id == mine.c.project_id)
        # Rules for every project first: PostgreSQL sorts a NULL last and SQLite first.
        .order_by(mine.c.project_id.is_not(None), bytewise(Project.key), bytewise(mine.c.name))
    ).all()
    agents: dict[uuid.UUID, list[str]] = {}
    for rule_id, agent in session.execute(
            select(RuleAgent.rule_id, RuleAgent.agent)
            .where(RuleAgent.rule_id.in_([row.rule_id for row in rows]),
                   known(RuleAgent.agent))).all():
        agents.setdefault(rule_id, []).append(agent)
    order = list(CodingAgent)
    return [{"name": name, "project": key,
             "agents": [agent.value for agent in sorted(agents.get(rule_id, []),
                                                        key=order.index)],
             "revision": revision, "pushed_by": pushed_by,
             "updated_on": as_utc(updated_on).isoformat()}
            for rule_id, name, key, revision, pushed_by, updated_on in rows]


def _newest(rule_ids: Select) -> Any:
    """The latest revision of each chosen rule, with who pushed it and when."""
    latest = (select(RuleRevision.rule_id, func.max(RuleRevision.revision).label("revision"))
              .where(RuleRevision.rule_id.in_(rule_ids))
              .group_by(RuleRevision.rule_id).subquery())
    return (
        select(RuleRevision.rule_id, RuleRevision.revision, User.username.label("pushed_by"),
               RuleRevision.created_on)
        .join(latest, (latest.c.rule_id == RuleRevision.rule_id)
              & (latest.c.revision == RuleRevision.revision))
        .join(User, User.user_id == RuleRevision.pushed_by)
        .subquery()
    )


def _new_revision(session: Session, user_id: uuid.UUID, rule: Rule,
                  text: str) -> tuple[int, bool]:
    """Store `text` as the rule's next revision, unless it is the latest already. Returns the
    revision and whether it is new."""
    # Two saves of one rule at once take turns here, so both cannot claim the same number.
    session.refresh(rule, with_for_update=True)
    latest = session.execute(
        select(RuleRevision.revision, RuleRevision.content_hash)
        .where(RuleRevision.rule_id == rule.rule_id)
        .order_by(RuleRevision.revision.desc()).limit(1)).first()
    content_hash = text_hash(text)
    if latest is not None and latest.content_hash == content_hash:
        return latest.revision, False
    revision = 1 if latest is None else latest.revision + 1
    session.add(RuleRevision(rule_id=rule.rule_id, revision=revision, text=text,
                             content_hash=content_hash, pushed_by=user_id))
    session.flush()
    return revision, True


def _use_for(session: Session, user_id: uuid.UUID, rule: Rule,
             agents: list[CodingAgent]) -> None:
    """Record the agents a rule is used for. A rule for every project is that agent's whole
    file for every project (`~/.claude/CLAUDE.md`), so each agent takes at most one."""
    if rule.project_id is None and agents:
        # Two choices at once take turns on the Library, so both cannot claim one agent.
        session.execute(select(Team.team_id).where(Team.team_id == rule.team_id)
                        .with_for_update())
        for other, agent in session.execute(
                visibility.my_rules(user_id)
                .with_only_columns(Rule.name, RuleAgent.agent)
                .join(RuleAgent, RuleAgent.rule_id == Rule.rule_id)
                .where(Rule.project_id.is_(None), Rule.archived.is_(False),
                       Rule.rule_id != rule.rule_id, RuleAgent.agent.in_(agents))).all():
            files = agent_files.AGENT_FILES[agent]
            raise Conflict(f"Your rule '{other}' is already {files.display_name}'s file for "
                           f"every project ({files.every_project}). Take "
                           f"{files.display_name} off '{other}' first, or make this a rule for "
                           "a project.")
    session.add_all([RuleAgent(rule_id=rule.rule_id, agent=agent) for agent in agents])
    session.flush()


def _where(project: Project | None) -> str:
    return "for every project" if project is None else f"for project '{project.key}'"
