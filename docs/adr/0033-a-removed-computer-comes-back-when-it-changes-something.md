# A removed computer comes back when it changes something

Status: accepted, 2026-10-16. Amends ADR-0025. Findings: AUTO-02, AUTO-20 in [the October 2026 audit](https://github.com/dchristopoulos/AIStack/blob/v0.1.1/docs/audits/2026-10/README.md).

Local mode records every change as an event in the Library's log, and every computer replays the log in one order (ADR-0025, ADR-0032). Removing a computer is a change like any other, but the computer removed may be offline and still in use: its later changes reach the log after the removal. Replay refused a change from a computer it did not know, which would stop every other computer's Library.

## Decisions

**A change from a removed computer brings it back.** Replay adds it again, with the id it had and the name and operating system its removal recorded, plus a suffix when another computer took the name meanwhile. What it held before the removal stays gone; what it does after is kept. Dropping its changes instead would lose the person's work, and a later change on another computer that built on one of them would then stop replay.

**Removal in local mode tidies the list; it does not cut a computer off.** Anyone who can write to the Library's repository can append events as any computer, so no rule in replay could keep a lost computer out. Cutting one off means revoking its access to the repository, which the documentation says. On a server, removal does cut a computer off (ADR-0027).

**Replay never stops on a removal or a rename.** A removal of a computer already gone, or of the last one left, changes nothing; two computers that removed each other while offline keep the one whose change sorts later, since that change brought it back. A rename to a name another computer took meanwhile gets a suffix, as a new computer's name does. A rename of, or a placement on, a removed computer changes nothing. A change from a computer that was never added is still refused: no AIStack release writes one.

**Read first, record later (ADR-0024).** The release that replays `machine_removed` and `machine_renamed` records neither; a later release records them and offers the dashboard's remove and rename actions in local mode.

## Consequences

- `machine_removed` carries the computer's name and operating system, so replay can bring it back without the events before it.
- A computer that restarts after it was removed is added again by its own startup, under the same id.
