# SQLite transactions take the write lock at BEGIN

Status: accepted (replaces the transaction-control mechanism in ADR-0008; the single-admin index it describes is unchanged)

On SQLite, the driver opens no transactions of its own (`isolation_level = None`), and SQLAlchemy opens each one explicitly with `BEGIN IMMEDIATE`. A transaction holds the database's write lock from its first statement, not from its first write.

Why: with a deferred `BEGIN`, eight users pushing eight different skills at once got two successes and six HTTP 500s. A deferred transaction reads under a snapshot and asks for the write lock only when it first writes. If another connection committed in between, the snapshot is stale and SQLite refuses the upgrade at once with "database is locked". The 5-second busy timeout does not apply, because no amount of waiting makes a stale snapshot current. Every write path in AIStack reads before it writes (look up the machine, find the skill, read the latest revision), so every concurrent write was exposed, and the failure reached the caller as an unexpected error rather than a retry.

PostgreSQL never did this: its writers wait for each other. ADR-0002 makes "runs identically on both" an invariant, and the backend that broke was the default one.

`BEGIN IMMEDIATE` asks for the lock up front, where the busy timeout does apply. A second writer waits its turn for the few milliseconds a transaction lasts.

**This also settles savepoints, which is what ADR-0008 changed the driver mode for.** ADR-0008 passed `connect_args={"autocommit": False}` so that a savepoint opened before any write would still be inside a transaction. With the driver emitting nothing and SQLAlchemy emitting `BEGIN IMMEDIATE` first, every savepoint is inside an explicit transaction by construction. The test that pins it, rolling back a savepoint while the outer transaction survives, passes unchanged. The connect hook no longer has to flip autocommit on and off around the pragmas, because the connection is not in a transaction when it runs.

**The cost is on readers.** A read-only transaction now takes the write lock too, so a read waits behind a write in progress, where WAL alone would have let it through. That is accepted: AIStack's transactions are a handful of indexed statements, the archive is parsed and validated before the first one is issued, and the measured write volume is tiny (ADR-0002). If read latency under write load ever matters, the fix is to mark read-only sessions and begin those deferred, which this mechanism allows and does not yet need.

Three tests hold the behavior, and all three fail against the previous configuration: one asserts directly that a second transaction waits for the first, and two push eight skills at once.

Rejected: retrying on `OperationalError` (it turns a lock-ordering problem into latency and a retry budget, and every write path would need it); a process-wide write mutex (it would not survive a second process, and SQLite already has the lock); making PostgreSQL the default (one container is the product).
