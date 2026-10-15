"""Alembic's entry point. Run only through `aistack.db.schema`, never from an alembic.ini.

The connection and its transaction belong to the caller, so every migration in one upgrade
commits or rolls back together.
"""

from alembic import context

# No target_metadata: alembic would apply the models' naming convention to every operation,
# and a shipped migration would then name constraints differently from what it did when it
# shipped. The models are compared with the migrations in tests/db/test_schema.py instead.
context.configure(
    connection=context.config.attributes["connection"],
    # SQLite cannot alter a constraint in place; batch mode rebuilds the table instead.
    render_as_batch=True,
)
context.run_migrations()
