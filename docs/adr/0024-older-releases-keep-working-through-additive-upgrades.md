# Older releases keep working through additive upgrades

Status: accepted, 2026-10-15. Amends ADR-0016 and ADR-0020, where a release refuses any schema newer than it knows. Research: [docs/research/schema-upgrades-across-releases.md](../research/schema-upgrades-across-releases.md).

In local mode several computers share one database and update AIStack at different times. Today the first computer to update migrates the database, and every computer still on the older release then refuses to start, with a traceback its user never sees: the coding agent started the process, so the agent just reports a server that failed.

## Decision

**Every migration says whether older releases can still use the database after it.** A migration module sets `older_releases_compatible = True` when it only adds (a table, a nullable or defaulted column, an index), and `False` when it removes, renames, or reshapes. A breaking change is split expand-then-contract across releases, as is standard: the release that adds the new shape is compatible, and a later release removes the old one.

**The database records the oldest release revision that can use it,** in a one-row `schema_compatibility` table, along with the release that wrote it. `migrate_schema` updates it after upgrading: it is the newest applied migration that is not compatible.

**A release meeting a newer schema** reads that row. If it knows the recorded revision, it runs on the newer schema without migrating, as Flyway does with "future" migrations. If not, it refuses, and nothing is changed.

**A refusal says what to do, where the person will see it.**
- The server stops with one sentence: the schema, the release that wrote it, and "run that release or newer, or restore the backup from before the upgrade".
- Local mode still starts, and every tool answers with the same sentence, so the agent tells the user in chat: another computer updated the Library, and restarting the agent fetches the update. Setup already runs `uvx aistack-mcp@latest`, so a restart is the fix in nearly every case.
  - Amended (2026-10 audit, AUTO-07): setup now installs with `uv tool install`, so a restart alone no longer updates. Local mode starts `uv tool upgrade` at once when the Library needs a newer release, skipping the daily wait and the same-minor rule, and the sentence asks for a restart a minute later, with `uv tool upgrade aistack-mcp` by hand if the message comes back or updates are turned off (`AISTACK_AUTO_UPDATE=off`).

## Consequences

- A migration without `older_releases_compatible` fails a test, so the question is answered for every one.
- The migration that creates `schema_compatibility` is itself compatible. Releases from before this ADR still refuse any newer schema, as they do today.
- AGENTS.md gains the expand-and-contract rule for migrations.
