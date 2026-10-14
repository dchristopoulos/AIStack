"""Record which releases can still use this database (ADR-0024).

Adds a table that only migrate_schema reads and writes, so every release that knows 0006 keeps
working, though none of those reads it: they refuse any newer schema, as they always have.
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"

older_releases_compatible = True


def upgrade() -> None:
    op.create_table(
        "schema_compatibility",
        sa.Column("row_id", sa.Integer(), nullable=False),
        sa.Column("oldest_compatible_revision", sa.String(length=32), nullable=False),
        sa.Column("written_by_release", sa.String(length=64), nullable=False),
        sa.Column("updated_on", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("row_id"),
    )
