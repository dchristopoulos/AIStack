# One admin, enforced by a partial unique index

Status: accepted (amends the `is_admin` schema comment in `docs/DESIGN.md` §4)

`USER.is_admin` is enforced by one thing: a unique partial index on `is_admin` where true, spelled per dialect (`sqlite_where` and `postgresql_where`, since SQLAlchemy has no portable kwarg for it).

Three supporting pieces, none of which enforce anything:

- The guarded `UPDATE ... AND NOT EXISTS (SELECT 1 FROM user WHERE is_admin)` is the fast path. It keeps every join after the first from raising a routine constraint error.
- `session.begin_nested()` around that update lets the outer transaction survive the rare race. The savepoint rolls back, the join returns a non-admin user, the inserted user and machine stay.
- SQLite engines pass `connect_args={"autocommit": False}` (Python 3.12+ PEP 249 transaction control) so savepoints participate in the outer transaction. This fixes SQLite transaction semantics generally; it is not specific to this invariant. The connect hook flips autocommit on temporarily to apply the pragmas, which are no-ops inside an open transaction.

Why: the guarded update alone is safe on SQLite and wrong on Postgres. Under READ COMMITTED two concurrent joins each evaluate the subquery against committed rows, neither sees the other's uncommitted write, and both become admin. SQLite hides it because WAL serializes writers, so a test written against the default database passes and proves nothing — the exact "runs identically on both" failure this project keeps guarding against. On Postgres a unique violation aborts the whole transaction, so catching `IntegrityError` without a savepoint would lose the user and machine inserted before it.

Deferred-cost prepayment, stated plainly: no MVP tool reads `is_admin`, so nothing in the MVP can observe two admins. It is worth building now because first-user intent cannot be reconstructed later. After two admins exist in a real deployment, the fix is a migration plus deciding which human loses access.

Cost: `autocommit=False` takes over transaction control for the whole SQLite engine, not just the admin path, and may hold read transactions longer. WAL and the 5s busy timeout are the mitigation. Two tests carry this — a SQLite test that a savepoint rollback preserves the outer transaction, and a Postgres concurrency test (the only one that can reproduce the race) gated on `TEST_DATABASE_URL`, with Postgres supplied by a Compose service.

Rejected: `SERIALIZABLE` on that transaction (correctness depending on an isolation level nobody remembers to set); the legacy `isolation_level = None` plus manual `BEGIN` listeners (the pre-3.12 compatibility recipe, unnecessary at this Python floor — it stays the fallback if the savepoint test ever fails); a `dialect == "sqlite"` branch around `begin_nested` (every future savepoint has to remember to copy it); `testcontainers` (a dependency plus a Docker requirement on every test run, to avoid setting one env var).
