"""A skill is placed per computer and harness (ADR-0018).

Before this, a machine had one decision per skill, and it meant Claude Code's folder. After
it, each decision names its harness, and every existing one is Claude Code's: that is the
only folder AIStack ever installed into. `machine_harness` starts empty and is filled in by
each machine's next sync.
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"

# The values as this migration knows them. A later harness widens the constraints in its own
# migration; this file never follows the model.
_HARNESSES = ("claude_code", "agents")
_CLAUDE_CODE = "claude_code"

_machine_skill = sa.table("machine_skill", sa.column("harness", sa.String()))


def _harness(constraint_name: str) -> sa.Enum:
    return sa.Enum(*_HARNESSES, name=constraint_name, native_enum=False,
                   create_constraint=True, length=16)


def upgrade() -> None:
    # Nullable while the existing rows are filled in, then required.
    op.add_column("machine_skill", sa.Column("harness", sa.String(length=16), nullable=True))
    op.execute(_machine_skill.update().values(harness=_CLAUDE_CODE))

    # On SQLite this rebuilds the table, which migrate_schema runs with foreign keys off.
    with op.batch_alter_table("machine_skill") as batch:
        batch.alter_column("harness", existing_type=sa.String(length=16), nullable=False)
        batch.create_check_constraint("ck_machine_skill_harness",
                                      sa.column("harness").in_(_HARNESSES))
        batch.drop_constraint("uq_machine_skill_machine_skill", type_="unique")
        batch.create_unique_constraint("uq_machine_skill_machine_harness_skill",
                                       ["machine_id", "harness", "skill_id"])

    op.create_table(
        "machine_harness",
        sa.Column("machine_harness_id", sa.Uuid(), nullable=False),
        sa.Column("machine_id", sa.Uuid(), nullable=False),
        sa.Column("harness", _harness("ck_machine_harness_harness"), nullable=False),
        sa.Column("created_on", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_synced_on", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["machine_id"], ["machine.machine_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("machine_harness_id"),
        sa.UniqueConstraint("machine_id", "harness", name="uq_machine_harness_machine_harness"),
    )
