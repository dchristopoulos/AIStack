"""Bind optional computer fingerprints without excluding older callers (ADR-0035).

Older releases may omit the value and never maintain it; it is authoritative only
when a caller supplies a fingerprint, so their writes remain meaningful (ADR-0031).
"""

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
older_releases_compatible = True


def upgrade() -> None:
    op.add_column("machine", sa.Column("fingerprint_hash", sa.String(64), nullable=True))
