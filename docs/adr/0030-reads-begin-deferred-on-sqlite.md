# On SQLite, a request that only reads begins deferred

Status: proposed, 2026-10-15. Amends ADR-0014. Findings: SEC-04, STD-06, ENT-04, DB-01 in [docs/audits/2026-10](../audits/2026-10/README.md).

ADR-0014 makes every SQLite transaction take the write lock at BEGIN, so a second writer waits instead of failing. It also makes every reader wait: the bearer check, `/health`, the invite page and the dashboard's state. One slow write turns `/health` into `unavailable` and, past the five-second busy timeout, a valid bearer into a bare 500.

## Decision

**A second session factory begins transactions deferred and refuses writes.** The token verifier, `/health`, the invite page, `/setup` and `GET /api/state` use it. Every tool call and every route that changes something keeps `BEGIN IMMEDIATE`, unchanged. In WAL mode a deferred reader never blocks and is never blocked by the writer.

The read-only factory is in `db/`, beside the other, and the engine module still hides the dialect: on PostgreSQL both factories behave the same.

## Consequences

- A test proves the read-only factory refuses a write, so a route cannot quietly start writing through it.
- AGENTS.md's transaction rule names the two factories and when each applies.
