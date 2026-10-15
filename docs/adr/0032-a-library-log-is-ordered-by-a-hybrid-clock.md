# A GitHub Library's log is ordered by a hybrid logical clock

Status: accepted, 2026-10-15. Amends ADR-0025. Findings: ENT-03, ENT-06 in [docs/audits/2026-10](../audits/2026-10/README.md).

ADR-0025 orders a Library's events by each computer's wall clock. A computer whose clock runs ahead, which happens after sleep in WSL2 and VMs and on dual-boot machines, sorts its events after newer ones from other computers, so copies disagree until a rebuild, and the rebuild silently keeps the older edit.

## Decisions

**An event's time is a hybrid logical clock**: the larger of the wall clock and one microsecond past the newest event this copy holds, so an event always sorts after everything its computer had seen when it was made. The fixed-width text form is unchanged, so the sort key, the file names and older releases' parsing all hold. The one-day limit on future times stays.

**A rebuild happens beside the copy, not in it**: the whole log is replayed into a new SQLite file next to the copy, with no lock on the copy, and its rows are then copied in by SQL in one short transaction. Other sessions on the computer keep reading the old copy meanwhile instead of waiting on a transaction as long as the replay. The rows are copied rather than the file renamed over the copy, because another process's open connections would keep writing to the renamed-away file and lose those changes. A change recorded on this computer while the rebuild ran makes the copy refuse it, and the rebuild starts over; after three tries it rebuilds in place.

**Archives are read before the transaction**: a push's archive is decoded and validated before the copy's transaction opens, so replay holds SQLite's write lock only for the writes (AGENTS.md: nothing slow inside a transaction).

## Consequences

- `library_log.new_event` takes the session, to read the newest time this copy holds.
- An edit made on a computer whose clock is behind, after it read another computer's change, keeps the newer content on every copy and on one rebuilt from the log (`tests/mcp/test_library_github.py`).
- Two computers that both changed a skill while offline are still ordered by their clocks: neither saw the other, so neither edit is newer by causality, and every copy agrees on the same order.
