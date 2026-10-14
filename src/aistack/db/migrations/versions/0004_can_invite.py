"""A team admin can let a member invite (ADR-0019).

Every existing member starts without it: until now only admins could make an invite code.
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"


def upgrade() -> None:
    op.add_column("team_member", sa.Column("can_invite", sa.Boolean(), nullable=False,
                                           server_default=sa.false()))
