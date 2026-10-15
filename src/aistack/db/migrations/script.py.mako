"""${message}

Revision: ${up_revision}
Follows: ${down_revision | comma,n}
"""

import sqlalchemy as sa
from alembic import op
${imports if imports else ""}

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}

# True only if (ADR-0024, ADR-0031): the shape only adds; no newer code trusts a value older
# releases write without maintaining; and every value an older release may read, it reads
# safely. Otherwise False, and split expand-then-contract across releases.
older_releases_compatible = False


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}
