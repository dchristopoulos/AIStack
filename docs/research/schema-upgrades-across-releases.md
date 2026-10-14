# Several releases on one database

Question: in local mode several computers share one database and may run different AIStack releases for a while. When one upgrades the schema, what should the others do, and what do established tools do? Researched 2026-10-15.

## What established tools do

- **One version table, one migrator at a time.** Every migration tool records applied migrations in a table in the database and takes a lock so concurrent starts migrate once. AIStack already does both: Alembic's `alembic_version`, and a PostgreSQL advisory lock in `migrate_schema` (ADR-0020, #80).
- **A newer schema than the release knows: two policies.**
  - *Tolerate it.* Flyway calls migrations a newer deployment applied "future" migrations, and by default ignores them rather than failing, so an older version can be redeployed after a newer one migrated the database ([Redgate Flyway: ignore migration patterns](https://documentation.red-gate.com/fd/flyway-ignore-migration-patterns-setting-277579002.html); Quarkus makes the opposite its default: [Quarkus Flyway guide](https://quarkus.io/version/2.16/guides/flyway/)).
  - *Refuse to start.* Gitea logs that a database "is for a newer Gitea" and stops, and says not to edit the version table ([Gitea forum](https://forum.gitea.com/t/solved-gitea-fails-to-start-migrations-trying-to-downgrade-database/4519), [Gitea upgrade docs](https://docs.gitea.com/installation/upgrade-from-gitea/)). Mattermost refuses with "Database schema version X is no longer supported" and offers a downgrade command run by the newer binary ([Mattermost: downgrading](https://docs.mattermost.com/administration-guide/upgrade/downgrading-mattermost-server.html)).
- **What makes tolerating safe: expand and contract.** A breaking change is split so the database supports every version that may be running: add the new structure beside the old one, move over, and remove the old one only once nothing uses it. Martin Fowler calls it parallel change, "a pattern to implement backward-incompatible changes to an interface in a safe manner" ([ParallelChange](https://martinfowler.com/bliki/ParallelChange.html)). Adding a nullable column is safe directly; renames, type changes and drops need the full sequence.

## What this means for AIStack

Tolerating every newer schema is wrong: an older release writing into a schema it does not know can lose data when a migration removed or renamed something. Refusing every newer schema is also wrong for local mode: the first computer to update would lock the others out until each one updates, with no server operator to fix it.

The two combine. A migration that only adds is safe for older releases; one that removes or reshapes is not. If each migration says which it is, and the database records the oldest release revision that can still use it, an older computer keeps working through additive upgrades and is refused, with a clear sentence, only after a breaking one. In local mode the refusal should reach the user through their agent, since the process is started by the agent and its startup log is out of sight.
