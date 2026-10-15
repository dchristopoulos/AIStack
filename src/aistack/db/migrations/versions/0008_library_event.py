"""Record each change to a local mode Library as an event (ADR-0025).

A new table that only local mode writes, so every release that knows 0007 keeps working.
"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"

older_releases_compatible = True


def upgrade() -> None:
    op.create_table(
        "library_event",
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("sort_key", sa.String(length=128), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("published", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_index("ix_library_event_sort_key", "library_event", ["sort_key"], unique=True)
