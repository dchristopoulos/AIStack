"""Alembic's entry point. Run only through `aistack.db.schema`, never from an alembic.ini.

The connection and its transaction belong to the caller, so every migration in one upgrade
commits or rolls back together.
"""

from alembic import context

from aistack.db.models import Base

context.configure(
    connection=context.config.attributes["connection"],
    target_metadata=Base.metadata,
    # SQLite cannot alter a constraint in place; batch mode rebuilds the table instead.
    render_as_batch=True,
)
context.run_migrations()
