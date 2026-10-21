"""The names of the skills a project's repository holds, per computer and folder (ADR-0038).

One nullable column, so every release that knows 0018 keeps working. Older releases neither
read nor write it; it is display data for the page's Start an agent dialog, refreshed by each
project folder's sync, and nothing decides anything from it (ADR-0031).
"""

import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"
older_releases_compatible = True


def upgrade() -> None:
    op.add_column("machine_project", sa.Column("repository_skills", sa.Text(), nullable=True))
