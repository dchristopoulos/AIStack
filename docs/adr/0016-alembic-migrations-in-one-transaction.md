# Schema changes are Alembic migrations, applied at startup in one transaction

Status: accepted (replaces "the server creates missing tables at startup" in `docs/OPERATING.md`)

Until now the server called `create_all` at startup, which makes tables that are missing and never changes one that exists. Teams (ADR-0015) are the first change to an existing table, so the server needs a way to move a deployed database forward.

The schema is now defined by numbered Alembic migrations in `src/aistack/db/migrations/`, shipped inside the package so the image carries them. `migrate_schema(engine)` runs at startup, before the server accepts a request, and is the only thing that creates or alters a table. The models and the migrations must agree, and a test compares them on both databases.

## Decisions inside it

- **One transaction for the whole upgrade.** The caller opens it and Alembic runs inside it, so a release with three migrations applies all three or none. Both databases roll back DDL: PostgreSQL always, SQLite because the driver opens no transactions of its own and SQLAlchemy begins each one explicitly (ADR-0014). Alembic logs that it "will assume non-transactional DDL" on SQLite; that is its default guess about the driver, and the tests show a failed migration leaving no table behind.
- **A failed migration stops the server.** It refuses to start and says which step failed. A server running against a half-changed schema is worse than one that is down.
- **Databases from before migrations are adopted, not rebuilt.** One with tables and no version record is marked as being at the baseline, `0001`, which is the schema the MVP shipped, and upgraded from there. The baseline file is a record of that schema and is never edited.
- **Foreign keys are off during a SQLite upgrade, and checked before commit.** SQLite cannot alter a constraint, so Alembic's batch mode copies the table, drops the original, and renames the copy. With foreign keys on, SQLite treats that drop as deleting every row, and the delete cascades: rebuilding `skill_version` would empty `skill_file`. The pragma does nothing inside a transaction, so it is set on the driver connection before one begins, `PRAGMA foreign_key_check` runs before commit, and enforcement is restored after. A test rebuilds a referenced table with rows in it and fails without this.
- **Index predicates are expressions, never generated text.** The generated baseline spelled the single-admin predicate as `is_admin IS 1`, which is SQLite's rendering and a syntax error on PostgreSQL. Review generated migrations for dialect-specific text.
- **No downgrades.** A downgrade that has never been run is a guess. The way back from a bad upgrade is the backup taken before it.
- **No `alembic.ini` and no CLI workflow for operators.** The configuration is three lines of code, and an operator upgrades by starting the new image.

Rejected: a hand-rolled table of numbered SQL scripts (the SQLite table rebuild is the hard part, and Alembic's batch mode already does it); `create_all` plus ad hoc `ALTER` statements at startup (no record of what has run); running migrations as a separate step before the server starts (one more thing to forget, and the one-container deployment has nowhere to put it).
