# A compatible migration also keeps older releases' data meaningful

Status: proposed, 2026-10-15. Amends ADR-0024. Findings: DB-04, DB-08, DB-09 in [docs/audits/2026-10](../audits/2026-10/README.md).

ADR-0024 calls a migration compatible when it only adds. Three kinds of change pass that test and still break a computer on an older release:

- A widened value set: a new harness, operating system or role is one more allowed value, and an older release that reads it fails.
- A column an older release writes past: an older computer installs a revision without updating `machine_skill.revision`, and the newer release then reads a stale value as true.
- A process that was already running when another computer migrated: it never checks again.

## Decisions

**A migration is compatible only if** its shape is additive, no newer code treats a value older releases do not maintain as authoritative, and every value an older release may meet is one it reads safely. Widening a value set is breaking unless the release before it already skips unknown values; so the release that tolerates a value ships before the release that writes it.

**A running process checks the schema before it writes**, cheaply, by the version row, and answers with ADR-0024's sentence when it no longer may.

## Consequences

- AGENTS.md's Migrations rule gains the three conditions.
- The services that read stored value sets skip unknown values now, before the next harness ships.
