"""Mark a team revision that a share put over a different skill of the same name (UX-06).

A nullable column, so every release that knows 0014 keeps working. An older release that
shares over a namesake leaves it unset, and the offer it causes is then an ordinary one: the
mark is a hint to the people who took the old skill, never what a decision rests on.
"""

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"

older_releases_compatible = True


def upgrade() -> None:
    op.add_column("skill_version", sa.Column("shared_over_unrelated", sa.Boolean(),
                                             nullable=True))
