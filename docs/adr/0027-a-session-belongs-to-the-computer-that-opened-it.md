# A dashboard session belongs to the computer that opened it, and its owner can remove that computer

Status: accepted, 2026-10-15. Amends ADR-0017 (a session ended only with its user's last machine) and ADR-0003 (revocation was an operator's database edit). Findings: SEC-01, SEC-05, STD-03, AUTO-02, STD-04 in [the October 2026 audit](https://github.com/dchristopoulos/AIStack/blob/v0.1.1/docs/audits/2026-10/README.md).

A lost laptop's token is the person's whole account. Today the operator's documented rotation leaves the thief every computer they added with `add_machine`, every dashboard session they opened, for eight hours, and every upload URL they minted. Signing out deletes a cookie and ends nothing. And the owner cannot act at all: only the operator can revoke a computer.

## Decisions

**A ticket names the computer and the token that minted it.** Sign-in links, sessions and upload and download tickets carry the machine's id and a short prefix of its token hash. Each use checks that the machine still exists and still has that token. Rotating or removing a computer ends everything it opened, at once.

**Signing out ends the session.** A session has an id. Signing out records it as ended until its expiry, in memory beside the used sign-in links. A restart already ends every session, so nothing needs to persist.

**A person removes and renames their own computers.** The dashboard's computer page has Remove this computer and Rename. Removing deletes the machine, which cascades its placements and ends its token, sessions and tickets. The last computer cannot be removed from the dashboard: the person would be locked out, and the operator's recovery remains for that. A computer's page says when each folder last synced, which `machine_harness.last_synced_on` already records.

**Each computer records which computer added it**, so the person and the operator can see a computer a thief added.

## Not doing

- Passwords or a second factor for the dashboard (ADR-0017 stands).
- Removing a computer through MCP: a stolen token must not be able to remove its owner's other computers from chat. The dashboard needs a session, which needs a link from a computer the person holds.

## Consequences

- A compatible migration adds `machine.added_by_machine_id`.
- In local mode, removing or renaming a computer is a new log event, replayed one release before it is recorded (ADR-0025 and ADR-0026's rule). Until then both are server-only.
- docs/OPERATING.md's lost-laptop runbook becomes: remove it on the dashboard; the operator's script is for a person who lost their only computer.
