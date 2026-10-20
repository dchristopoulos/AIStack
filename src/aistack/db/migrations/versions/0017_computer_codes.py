"""Account pairing records; older releases never see placeholder machines (ADR-0035).

Normal codes recheck the issuing machine token, including older clients’ removals
and rotations. Operator recovery uses the deployed server’s admin command, as
OPERATING requires: that command cancels its records on offboarding or forgetting.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0017"
down_revision = "0016"
older_releases_compatible = True


def upgrade() -> None:
    op.create_table(
        "computer_code",
        sa.Column("code_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("issuing_machine_id", sa.Uuid(), nullable=True),
        sa.Column("issuing_token_hash", sa.String(64), nullable=True),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=True),
        sa.Column("machine_id", sa.Uuid(), nullable=True),
        sa.Column("options", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=False),
        sa.Column("request", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=True),
        sa.Column("created_on", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_on", sa.DateTime(timezone=True), nullable=False),
        sa.Column("requested_on", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_on", sa.DateTime(timezone=True), nullable=True),
        sa.Column("denied_on", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_on", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_on", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("code_id", name="computer_code_pkey"),
        sa.ForeignKeyConstraint(["user_id"], ["user.user_id"], name="computer_code_user_id_fkey"),
        sa.UniqueConstraint("code_hash", name="computer_code_code_hash_key"),
        sa.UniqueConstraint("request_hash", name="computer_code_request_hash_key"),
    )
