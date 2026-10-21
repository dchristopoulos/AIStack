"""When a shared repository file's edit settled: the working copy's commit had the shared text.

One nullable column, so every release that knows 0020 keeps working. Older releases neither
read nor write it, so they read a settled edit as still shared and show it so, which is safe:
nothing is written or shared again for an edit already shared. `cancelled_on` keeps meaning a
cancellation only (ADR-0031).
"""

import sqlalchemy as sa
from alembic import op

revision = "0021"
down_revision = "0020"
older_releases_compatible = True


def upgrade() -> None:
    op.add_column("project_file_edit",
                  sa.Column("settled_on", sa.DateTime(timezone=True), nullable=True))
