# Test strategy

What large engineering teams do about testing, from their own published sources, and which parts apply to AIStack: one server process on SQLite or PostgreSQL, plus local mode, which is the same code over stdio on one computer with a Git repository as its Library. This is the reference for steps 6b to 6d of the October 2026 audit plan; it states no coverage target and asks for no test count.

## Sources

Primary sources only, read on 2026-10-17.

- Google, *Software Engineering at Google*, ch. 11 "Testing Overview" (abseil.io/resources/swe-book/html/ch11.html): test sizes, the 80/15/5 rough ratio, flakiness numbers, coverage as a misleading target, the Beyoncé Rule.
- Google Testing Blog, "Where do our flaky tests come from?" (2017): flakiness grows with test size; the common causes are randomness and timeouts in the tests themselves.
- Martin Fowler / Ham Vocke, "The Practical Test Pyramid" (martinfowler.com/articles/practical-test-pyramid.html), and Fowler, "ContractTest" (martinfowler.com/bliki/ContractTest.html).
- Hypothesis documentation: stateful testing (`RuleBasedStateMachine`) and the settings reference.
- mutmut documentation (mutmut.readthedocs.io).
- Jepsen analyses index (jepsen.io/analyses): method and the bug classes that recur.
- SQLite: "Transaction" (lang_transaction.html), "Write-Ahead Logging" (wal.html), "How To Corrupt An SQLite Database File" (howtocorrupt.html).
- PostgreSQL: "Transaction Isolation" (docs/current/transaction-iso.html).

## What the sources say

**Size before kind.** Google classifies tests by what they may touch, not by name. Small: one process, usually one thread, no sleep, no I/O, no database. Medium: one machine, several processes and threads, blocking calls, network to localhost only. Large: anything, including remote systems. The rough ratio is 80% narrow, 15% integration, 5% end to end by count, and flakiness rises with size. Fowler's pyramid says the same in other words: push each test as far down as it can go, and when a high-level test catches a bug that no low-level test does, add the low-level test.

**Flakiness is the cost that grows.** Google reports about 0.15% of its tests flaky and says tests lose their value as flakiness approaches 1%. Retrying a flaky test hides the cause; the causes found most often are randomness and timeouts in test code, and about one time in six a newly flaky test was a real production bug.

**Coverage is a floor at best.** Google calls holding coverage up as the standard "somewhat unfortunate": an 80% bar becomes a ceiling. Judge tests by which behaviours they pin and whether they are stable. Mutation testing answers the question coverage cannot: whether a test would notice the code being wrong.

**Delete what duplicates.** Fowler: remove high-level tests that duplicate lower-level ones, despite the sunk cost.

**Contract tests for every fake.** Where a test double stands in for an external service, a separate test checks the double against the real service, on the service's schedule (daily or weekly), outside the merge gate. A failure means "update the fake", not "the build is broken".

**Generate inputs and sequences.** Hypothesis generates inputs and, with `RuleBasedStateMachine`, sequences of operations, with `@invariant` checked after every step, and shrinks a failure to a short program. Its CI profile (`CI` set) turns on `derandomize` and turns off the per-example `deadline`, so a CI run is reproducible and a slow runner does not fail it.

**Histories, not single calls, find concurrency bugs.** Jepsen runs random concurrent operations against the real system under faults (partitions, crashes, clock skew) and checks the whole history against a model. The bugs that recur are data loss, stale reads, read skew, replica divergence, and lock conflicts.

**The databases' own fine print.**
- SQLite `DEFERRED` transactions start reading and upgrade to writing later; the upgrade fails with `SQLITE_BUSY` if another connection wrote meanwhile, and the busy timeout cannot help, because waiting does not make the old snapshot current. `IMMEDIATE` takes the write lock at `BEGIN`, where the timeout works. (AIStack already does this: ADR-0014.)
- In WAL mode, `synchronous=FULL` makes each commit survive power loss; `NORMAL` may roll back recent commits after a power failure. WAL needs the shared-memory index, so it does not work on a network filesystem. A checkpoint cannot finish while readers always overlap, and the WAL then grows without bound.
- Copying an SQLite file while it is open, or separating it from its `-wal` file, can corrupt it; `VACUUM INTO` or the backup API is safe.
- PostgreSQL Read Committed re-evaluates an `UPDATE`'s `WHERE` against the row a concurrent transaction just committed, so a conditional update ("still pending") is a correct guard. Repeatable Read and Serializable raise SQLSTATE 40001, deadlocks raise 40P01, and both mean "retry the whole transaction".

## What applies here, and what does not

AIStack is not a distributed database, so Jepsen's partition and clock-skew faults have no target. Its concurrency is a few writers on one database (SQLite's single write lock, or PostgreSQL rows), several agent sessions on one computer writing one skills folder, and computers converging through a Library log on GitHub. Each rule below names its test size.

1. **Most tests stay small or medium, as now.** Push validation, the content hash, reconciliation and visibility are pure or near pure: test them directly with rejection matrices (small). Everything else uses the real database in a temp file and the in-process server (medium). End-to-end stays at a few journeys: the browser tests per page, the container smoke, the real-GitHub run. Fowler's rule decides where a new test goes.

2. **Mutation testing on trust boundaries replaces any coverage goal.** Run mutmut on the modules where a missed bug is a security or data-loss bug: skill_archive, skill_validation, content_hash, reconciliation, sync_service, visibility, mcp/auth, the transfer routes, library_log, local_skills. A surviving mutant there is a missing test or dead code; either answer is worth having. Elsewhere, coverage is read only to find lines no test reaches. mutmut needs `fork`, so it runs on macOS or Linux, not on the Windows job, and it is a periodic measurement, not a merge gate.

3. **Properties where an invariant is easy to state and inputs are hard to enumerate.**
   - Content hash: the same files in any order and any archive layout give one digest; any one-byte change, rename, or mode change gives another.
   - Paths: every path push validation accepts stays inside the skill folder once joined, on POSIX and Windows rules alike; every path it rejects is rejected with a sentence naming it.
   - Reconciliation: over every (desired, observed) pair the table returns an action, and no action silently overwrites a local edit (ADR-0007's invariant, generated instead of listed).
   - Library log: a `RuleBasedStateMachine` doing back up, edit, install, remove and rename on two computers, with the invariant that replaying either log rebuilds the same Library. `tests/mcp/test_library_log.py` already does this with seeded `random`; Hypothesis adds shrinking, so a failure arrives as a short sequence instead of a seed.
   Use the `ci` profile in CI and keep the example database out of the repository.

4. **Races are pinned at the exact window, never hoped for.** A `threading.Barrier` (or a hook that blocks one thread at the statement in question) holds the first transaction inside the window, and the test fails when the guard is removed. The repository already has fifteen such tests (`tests/db/*_race_postgres.py`, `test_sqlite_write_lock.py`), and `tests/db/test_engine.py` and `test_sqlite_write_lock.py` already pin the busy timeout ending in `Busy` and a read session refusing to write. Candidates still open, to confirm in 6b:
   - `Busy` from a transfer or dashboard route answering 503 with the try-again sentence, end to end.
   - Two agent sessions installing one skill into one folder at once (`local_skills._swap_in`), held at the gap between its two renames.
   - A sync and a push of one skill from two computers of one person, held between the hash read and the revision insert.

5. **Crash mid-write is tested by killing a real process, not by mocking.** The data that must survive a crash: the database (SQLite's job, given `synchronous` stays at its default `FULL`; pin that with a test so nobody sets `NORMAL` for speed), the skills folder (the install stages and renames, so a crash leaves the old revision, the new one, or no folder, which sync reinstalls from desired state), and the Library repository (events not yet pushed stay in the database for the next push). A medium test runs the operation in a subprocess, kills it with `SIGKILL` at a chosen point, restarts, and checks the invariant. Power loss is out of scope for tests: the install writes files without `fsync`, so a power cut can leave a renamed folder with empty files on some filesystems; that is a design question for the plan, not a test.

6. **Slow and failing dependencies.** The two external dependencies are the database and GitHub. For the database: a statement that times out, a connection dropped mid-transaction, PostgreSQL restarting. For GitHub: a push rejected, a network error, a slow clone; each must leave the Library consistent and retry later. Fakes stand in for GitHub in the suite, so the existing real-GitHub test (`tests/e2e/test_real_github.py`) is the contract test for them: it belongs on the weekly schedule, not the merge gate.

7. **Flakiness is a bug, fixed at its cause.** No reruns. A test that sleeps or waits on wall-clock time is the usual cause; wait on the condition instead, as the browser tests already do against `/api/state`. Seeded randomness prints its seed on failure.

8. **Speed is a budget, measured, not guessed.** The merge gate is about seven minutes after the CI split. `pytest --durations=30` finds the tests that cost the most; a slow test is moved down a size, given a smaller fixture, or deleted under rule 9, never skipped.

9. **Deleting a test needs proof.** A test is deleted only when mutmut shows every mutant it kills is also killed by another test, it covers no line that no other test covers, and the full suite stays green on both databases; the commit lists that proof. A new test must fail without the code it protects, and the commit shows that negative check.

## Order of work

6b measures (coverage per module, the thirty slowest tests, surviving mutants on the trust-boundary modules). 6c turns the measurements into plan steps in this order: surviving mutants on trust boundaries, then the rare failures in rules 4 to 6, then the properties in rule 3, then speed. 6d executes them one at a time under rule 9.
