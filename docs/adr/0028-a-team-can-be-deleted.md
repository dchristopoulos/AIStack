# A team can be deleted, and nobody is kept in one

Status: proposed, 2026-10-15. Amends ADR-0015 (a team always keeps an admin, and nothing deletes a team). Findings: AUTHZ-05, AUTHZ-V01, PH-04, PH-05, DB-07, AUTO-13, UX-03 in [docs/audits/2026-10](../audits/2026-10/README.md).

A team made by mistake can never go away: its only member cannot leave, because a team keeps an admin, and nothing deletes a team. A team whose only admin was taken off the server has an admin nobody can reach, and no script names another. Its name stays taken, and team names share a namespace with usernames.

## Decisions

**An admin can delete a team.** The confirmation names what goes: the team's copies of its skills, its groups and its invites. What stays is said too: every copy a member took is theirs, in their Library and on their computers (ADR-0015's rule that a machine installs only from the Library makes this safe).

**The last member leaving deletes the team.** The guard that a team keeps an admin applies only while someone else is in it.

**An operator can name a new admin**, through a documented command that goes through the services, for a team whose admins are all gone.

## Not doing

- Renaming a team or a group. A name is in every member's addresses and in what `sync` reports, and a rename is a separate piece of work.
- Transferring a team's skills to a member on deletion: they can take what they want first.

## Consequences

- `team_service.delete_team`, a dashboard action, and one service test per rule above; deleting is a trust-boundary change.
- Deleting runs under the same team row lock as the admin rules (ENT-01).
