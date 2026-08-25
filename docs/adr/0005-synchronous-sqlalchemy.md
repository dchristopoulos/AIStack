# Synchronous SQLAlchemy, not async

Status: accepted (reverses the async convention committed 2026-08-24 in CLAUDE.md, same day, after external review and measurement)

Services and models use synchronous SQLAlchemy: plain `sqlite3` driver for SQLite, `psycopg` for Postgres. Tools are plain `def` functions.

Why: the case for async rested on a false premise — that blocking drivers under FastMCP's async server would freeze the event loop. FastMCP threadpools `def` tools by default, so concurrent calls proceed without any async discipline. aiosqlite is itself a thread wrapper, so "async SQLite" is async syntax over threads with none of the benefit. Measured: five concurrent 20-file pushes drain in 5.8 ms (WAL) with worst reader latency 0.26 ms. Async would add greenlet, separate drivers, no-lazy-loading discipline, and async test fixtures — cost with no measured payoff at this write volume (ADR-0002).

The real trap is the opposite one: an `async def` tool calling a blocking driver serializes every caller. Plain `def` is the safe default here.

Revisit only if measurement ever shows blocking database work is material.
