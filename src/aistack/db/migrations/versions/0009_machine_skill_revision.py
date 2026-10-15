"""Remember which revision each folder last installed or pushed, so sync can tell an edit of
an older revision from an edit of the latest.

A nullable column, so every release that knows 0008 keeps working.
"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"

older_releases_compatible = True


def upgrade() -> None:
    op.add_column("machine_skill", sa.Column("revision", sa.Integer(), nullable=True))
