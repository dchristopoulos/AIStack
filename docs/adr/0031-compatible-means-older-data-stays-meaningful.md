# A compatible migration also keeps older releases' data meaningful

Status: accepted, 2026-10-15. Amends ADR-0024. Findings: DB-04, DB-08, DB-09 in [docs/audits/2026-10](../audits/2026-10/README.md).

ADR-0024 calls a migration compatible when it only adds. Three kinds of change pass that test and still break a computer on an older release:

- A widened value set: a new harness, operating system or role is one more allowed value, and an older release that reads it fails.
- A column an older release writes past: an older computer installs a revision without updating `machine_skill.revision`, and the newer release then reads a stale value as true.
- A process that was already running when another computer migrated: it never checks again.

## Decisions

**A migration is compatible only if** its shape is additive, no newer code treats a value older releases do not maintain as authoritative, and every value an older release may meet is one it reads safely. Widening a value set is breaking unless the release before it already skips unknown values; so the release that tolerates a value ships before the release that writes it.

**Stored value sets read unknown values as nothing.** Harness, operating system, team kind and member role are `ValueSet` columns (`db/models/value_set.py`): a value this release does not know reads as None instead of raising, and the services list only rows whose value they know (`known()`). A role this release does not know grants nothing. From this release on, adding a value to one of these sets is compatible.

**A running process checks the schema before it writes**, cheaply, by the version row: `guard_schema` reads it as each transaction begins, remembers a newer schema it may still run on, and refuses the transaction before its first statement otherwise, with ADR-0024's sentence. In local mode the refusal also sticks, as it does at start.

## Consequences

- AGENTS.md's Migrations rule and the migration template carry the three conditions.
- Every transaction costs one more primary-key read.
- A server whose database was upgraded under it answers each call with a sentence naming the release that did it, until it is restarted on that release.
- `machine_skill.revision` (0009) is trusted as it is. No published release predates it: `v0.1.0` already carries it.
