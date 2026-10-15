# A GitHub Library's log is ordered by a hybrid logical clock

Status: proposed, 2026-10-15. Amends ADR-0025. Findings: ENT-03, ENT-06 in [docs/audits/2026-10](../audits/2026-10/README.md).

ADR-0025 orders a Library's events by each computer's wall clock. A computer whose clock runs ahead, which happens after sleep in WSL2 and VMs and on dual-boot machines, sorts its events after newer ones from other computers, so copies disagree until a rebuild, and the rebuild silently keeps the older edit.

## Decisions

**An event's time is a hybrid logical clock**: the larger of the wall clock and one past the newest event this computer has applied, so an event always sorts after everything its computer had seen when it was made. The fixed-width text form is unchanged, so the sort key, the file names and older releases' parsing all hold. The one-day limit on future times stays.

**A rebuild happens beside the copy, not in it**: replay into a new database file, then swap it in, so other sessions on the computer keep reading the old copy instead of waiting on one long transaction.

## Consequences

- `library_log.new_event` takes the newest applied time.
- A test with two computers an hour apart converges on the newer edit by causality.
