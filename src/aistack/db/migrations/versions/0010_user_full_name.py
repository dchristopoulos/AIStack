"""Let a person give the name their teammates read beside their username.

A nullable column, so every release that knows 0009 keeps working.
"""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"

older_releases_compatible = True


def upgrade() -> None:
    op.add_column("user", sa.Column("full_name", sa.String(100), nullable=True))
