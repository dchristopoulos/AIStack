import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from aistack.db.models.base import Base
from aistack.db.models.coding_agent import CodingAgent, coding_agent_type
from aistack.db.models.skill_version import CONTENT_HASH_LENGTH
from aistack.db.models.timestamps import utc_now

RULE_NAME_MAX_LENGTH = 64
# Bytes of UTF-8, enforced in `services/rule_validation.py` (ADR-0036).
RULE_TEXT_MAX_BYTES = 64 * 1024

# Every foreign key in the rule and project file tables cascades or sets null: a release from
# before them rebuilds a GitHub Library's copy by deleting only the tables it knows (ADR-0025).


class Rule(Base):
    """A rule kept in the Library (ADR-0036): the person's rules for every project, or, with
    `project_id`, their rules for that project. Its text lives in RuleRevision rows."""

    __tablename__ = "rule"

    rule_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # The personal team whose Library holds it, as for a skill (ADR-0015).
    team_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("team.team_id", ondelete="CASCADE"),
        nullable=False,
    )
    # Null for a rule for every project.
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("project.project_id", ondelete="CASCADE"),
        nullable=True,
    )
    name: Mapped[str] = mapped_column(String(RULE_NAME_MAX_LENGTH), nullable=False)
    created_on: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                 default=utc_now)
    # Who first saved it. Provenance, never authorship, as for a skill.
    pushed_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    # Removed from the Library. The row stays so that sync does not mistake the file still on
    # a computer for a new rule and back it up again, as for a skill.
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        # A name is unique among a person's rules for one project. NULLs are distinct on both
        # databases, so this leaves the rules for every project to the index below.
        UniqueConstraint("team_id", "project_id", "name", name="uq_rule_team_project_name"),
        Index("ux_rule_team_name_every_project", "team_id", "name", unique=True,
              sqlite_where=(project_id.is_(None)),
              postgresql_where=(project_id.is_(None))),
        # Deleting a project cascades here, and PostgreSQL indexes no foreign key on its own.
        Index("ix_rule_project_id", "project_id"),
    )


class RuleRevision(Base):
    """One immutable revision of a rule's text. A change is a new row, never an update."""

    __tablename__ = "rule_revision"

    rule_revision_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True,
                                                        default=uuid.uuid4)
    rule_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("rule.rule_id", ondelete="CASCADE"),
        nullable=False,
    )
    # Server-assigned 1, 2, 3…
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    # Verbatim, at most RULE_TEXT_MAX_BYTES of UTF-8.
    text: Mapped[str] = mapped_column(Text, nullable=False)
    # `content_hash.text_hash(text)`: the same whichever agent's file holds the text.
    content_hash: Mapped[str] = mapped_column(String(CONTENT_HASH_LENGTH), nullable=False)
    created_on: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                 default=utc_now)
    pushed_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user.user_id", ondelete="CASCADE"),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("rule_id", "revision", name="uq_rule_revision_rule_revision"),
    )


class RuleAgent(Base):
    """An agent a rule is used for. The program writes the rule's text to that agent's own
    file on every computer that has the agent and, for a project rule, the project."""

    __tablename__ = "rule_agent"

    rule_agent_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    rule_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("rule.rule_id", ondelete="CASCADE"),
        nullable=False,
    )
    agent: Mapped[CodingAgent] = mapped_column(coding_agent_type("ck_rule_agent_agent"),
                                               nullable=False)

    __table_args__ = (
        UniqueConstraint("rule_id", "agent", name="uq_rule_agent_rule_agent"),
    )


class MachineRule(Base):
    """What one computer last had of one rule in one agent's file: what sync compares the file
    on disk against, as `machine_skill.revision` is for a skill.

    There is no `enabled`: a rule follows the person, never one computer (ADR-0036).
    """

    __tablename__ = "machine_rule"

    machine_rule_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True,
                                                       default=uuid.uuid4)
    machine_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("machine.machine_id", ondelete="CASCADE"),
        nullable=False,
    )
    rule_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("rule.rule_id", ondelete="CASCADE"),
        nullable=False,
    )
    agent: Mapped[CodingAgent] = mapped_column(coding_agent_type("ck_machine_rule_agent"),
                                               nullable=False)
    # The revision last written or backed up here: what a file that matches no revision was
    # edited from. Null until one of the two happens.
    revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_on: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                 default=utc_now)
    updated_on: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                 default=utc_now, onupdate=utc_now)

    __table_args__ = (
        UniqueConstraint("machine_id", "rule_id", "agent",
                         name="uq_machine_rule_machine_rule_agent"),
        Index("ix_machine_rule_rule_id", "rule_id"),
    )
