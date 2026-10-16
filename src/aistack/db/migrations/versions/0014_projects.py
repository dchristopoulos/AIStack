"""Skills folders inside a project (ADR-0026).

Three new tables, so every release that knows 0013 keeps working: none of them reads these,
and `machine_skill` is untouched. Every foreign key cascades, because an older release that
rebuilds a GitHub Library's copy (ADR-0025) empties the tables it knows and cannot know these.
"""

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"

older_releases_compatible = True

# The values as this migration knows them. A later harness widens the constraint in its own
# migration; this file never follows the model.
_HARNESSES = ("claude_code", "agents")


def upgrade() -> None:
    op.create_table(
        "project",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("created_on", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("project_id"),
        sa.UniqueConstraint("user_id", "key", name="uq_project_user_key"),
    )
    op.create_table(
        "machine_project",
        sa.Column("machine_project_id", sa.Uuid(), nullable=False),
        sa.Column("machine_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("harness", sa.Enum(*_HARNESSES, name="ck_machine_project_harness",
                                     native_enum=False, create_constraint=True, length=16),
                  nullable=False),
        sa.Column("path", sa.String(length=1024), nullable=True),
        sa.Column("created_on", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_synced_on", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["machine_id"], ["machine.machine_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["project.project_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("machine_project_id"),
        sa.UniqueConstraint("machine_id", "project_id", "harness",
                            name="uq_machine_project_machine_project_harness"),
    )
    op.create_index("ix_machine_project_project_id", "machine_project", ["project_id"])
    op.create_table(
        "machine_project_skill",
        sa.Column("machine_project_skill_id", sa.Uuid(), nullable=False),
        sa.Column("machine_project_id", sa.Uuid(), nullable=False),
        sa.Column("skill_id", sa.Uuid(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=True),
        sa.Column("created_on", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_on", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["machine_project_id"], ["machine_project.machine_project_id"],
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["skill_id"], ["skill.skill_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("machine_project_skill_id"),
        sa.UniqueConstraint("machine_project_id", "skill_id",
                            name="uq_machine_project_skill_folder_skill"),
    )
