"""Remember which computer added each computer, so a person can spot one a thief added
(ADR-0027).

A nullable column, so every release that knows 0011 keeps working.
"""

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"

older_releases_compatible = True


def upgrade() -> None:
    op.add_column("machine", sa.Column("added_by_machine_id", sa.Uuid(), nullable=True))
