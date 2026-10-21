"""The text a repository file's edit started from, so the page can show what it changes.

One nullable column, so every release that knows 0019 keeps working. Older releases neither
read nor write it; an edit they save has none, and the page then shows no diff. It is display
data and nothing decides anything from it (ADR-0031).
"""

import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0019"
older_releases_compatible = True


def upgrade() -> None:
    op.add_column("project_file_edit", sa.Column("base_text", sa.Text(), nullable=True))
