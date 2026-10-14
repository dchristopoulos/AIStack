"""An invite is a record: one use, pending until accepted, and it expires (ADR-0022).

A team had one invite code, and a new one replaced it. Codes made before this stop working;
no server had any users then.
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"


def upgrade() -> None:
    op.create_table(
        "invite",
        sa.Column("invite_id", sa.Uuid(), nullable=False),
        sa.Column("team_id", sa.Uuid(), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_on", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_on", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_by", sa.Uuid(), nullable=True),
        sa.Column("used_on", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_on", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["team_id"], ["team.team_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["user.user_id"]),
        sa.ForeignKeyConstraint(["used_by"], ["user.user_id"]),
        sa.PrimaryKeyConstraint("invite_id"),
        sa.UniqueConstraint("code_hash"),
    )

    # On SQLite this rebuilds the table, which migrate_schema runs with foreign keys off.
    with op.batch_alter_table("team") as batch:
        batch.drop_column("invite_hash")
