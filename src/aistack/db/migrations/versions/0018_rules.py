"""Rules in the Library, and the Markdown files of a project (ADR-0036).

Six new tables, so every release that knows 0017 keeps working: none of them reads these, and
no existing table changes. Every foreign key cascades or sets null, because an older release
that rebuilds a GitHub Library's copy (ADR-0025) empties the tables it knows and cannot know
these.
"""

import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"

older_releases_compatible = True

# The values as this migration knows them. A later agent widens the constraints in its own
# migration; this file never follows the model.
_AGENTS = ("claude_code", "codex", "gemini_cli", "cursor", "copilot_cli", "opencode")


def _agent(constraint_name: str, nullable: bool = False) -> sa.Column:
    return sa.Column("agent", sa.Enum(*_AGENTS, name=constraint_name, native_enum=False,
                                      create_constraint=True, length=16),
                     nullable=nullable)


def upgrade() -> None:
    op.create_table(
        "rule",
        sa.Column("rule_id", sa.Uuid(), nullable=False),
        sa.Column("team_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("created_on", sa.DateTime(timezone=True), nullable=False),
        sa.Column("pushed_by", sa.Uuid(), nullable=False),
        sa.Column("archived", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["team_id"], ["team.team_id"], name="rule_team_id_fkey",
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["project.project_id"],
                                name="rule_project_id_fkey", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["pushed_by"], ["user.user_id"], name="rule_pushed_by_fkey",
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("rule_id", name="rule_pkey"),
        sa.UniqueConstraint("team_id", "project_id", "name", name="uq_rule_team_project_name"),
    )
    every_project = sa.column("project_id").is_(None)
    op.create_index("ux_rule_team_name_every_project", "rule", ["team_id", "name"],
                    unique=True, sqlite_where=every_project, postgresql_where=every_project)
    op.create_index("ix_rule_project_id", "rule", ["project_id"])

    op.create_table(
        "rule_revision",
        sa.Column("rule_revision_id", sa.Uuid(), nullable=False),
        sa.Column("rule_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("created_on", sa.DateTime(timezone=True), nullable=False),
        sa.Column("pushed_by", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["rule_id"], ["rule.rule_id"], name="rule_revision_rule_id_fkey",
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["pushed_by"], ["user.user_id"],
                                name="rule_revision_pushed_by_fkey", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("rule_revision_id", name="rule_revision_pkey"),
        sa.UniqueConstraint("rule_id", "revision", name="uq_rule_revision_rule_revision"),
    )

    op.create_table(
        "rule_agent",
        sa.Column("rule_agent_id", sa.Uuid(), nullable=False),
        sa.Column("rule_id", sa.Uuid(), nullable=False),
        _agent("ck_rule_agent_agent"),
        sa.ForeignKeyConstraint(["rule_id"], ["rule.rule_id"], name="rule_agent_rule_id_fkey",
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("rule_agent_id", name="rule_agent_pkey"),
        sa.UniqueConstraint("rule_id", "agent", name="uq_rule_agent_rule_agent"),
    )

    op.create_table(
        "machine_rule",
        sa.Column("machine_rule_id", sa.Uuid(), nullable=False),
        sa.Column("machine_id", sa.Uuid(), nullable=False),
        sa.Column("rule_id", sa.Uuid(), nullable=False),
        _agent("ck_machine_rule_agent"),
        sa.Column("revision", sa.Integer(), nullable=True),
        sa.Column("created_on", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_on", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["machine_id"], ["machine.machine_id"],
                                name="machine_rule_machine_id_fkey", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["rule_id"], ["rule.rule_id"], name="machine_rule_rule_id_fkey",
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("machine_rule_id", name="machine_rule_pkey"),
        sa.UniqueConstraint("machine_id", "rule_id", "agent",
                            name="uq_machine_rule_machine_rule_agent"),
    )
    op.create_index("ix_machine_rule_rule_id", "machine_rule", ["rule_id"])

    op.create_table(
        "project_file",
        sa.Column("project_file_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("path", sa.String(length=1024), nullable=False),
        _agent("ck_project_file_agent", nullable=True),
        sa.Column("ticked", sa.Boolean(), nullable=False),
        sa.Column("turned_off", sa.Boolean(), nullable=False),
        sa.Column("size", sa.Integer(), nullable=True),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("snapshot_machine_id", sa.Uuid(), nullable=True),
        sa.Column("snapshot_on", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_on", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["project.project_id"],
                                name="project_file_project_id_fkey", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["snapshot_machine_id"], ["machine.machine_id"],
                                name="project_file_snapshot_machine_id_fkey",
                                ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("project_file_id", name="project_file_pkey"),
        sa.UniqueConstraint("project_id", "path", name="uq_project_file_project_path"),
    )
    op.create_index("ix_project_file_snapshot_machine_id", "project_file",
                    ["snapshot_machine_id"])

    op.create_table(
        "project_file_edit",
        sa.Column("project_file_edit_id", sa.Uuid(), nullable=False),
        sa.Column("project_file_id", sa.Uuid(), nullable=False),
        sa.Column("machine_id", sa.Uuid(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("base_hash", sa.String(length=64), nullable=False),
        sa.Column("note", sa.String(length=4096), nullable=True),
        sa.Column("pull_request_url", sa.String(length=2048), nullable=True),
        sa.Column("created_on", sa.DateTime(timezone=True), nullable=False),
        sa.Column("written_on", sa.DateTime(timezone=True), nullable=True),
        sa.Column("shared_on", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_on", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_file_id"], ["project_file.project_file_id"],
                                name="project_file_edit_project_file_id_fkey",
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["machine_id"], ["machine.machine_id"],
                                name="project_file_edit_machine_id_fkey", ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("project_file_edit_id", name="project_file_edit_pkey"),
    )
    op.create_index("ix_project_file_edit_project_file_id", "project_file_edit",
                    ["project_file_id"])
    op.create_index("ix_project_file_edit_machine_id", "project_file_edit", ["machine_id"])
