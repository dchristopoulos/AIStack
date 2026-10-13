"""${message}

Revision: ${up_revision}
Follows: ${down_revision | comma,n}
"""

import sqlalchemy as sa
from alembic import op
${imports if imports else ""}

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}
