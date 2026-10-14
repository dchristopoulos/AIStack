# An invite is a record: one use, pending until accepted, and it expires

Status: accepted, 2026-10-14. Amends ADR-0019 and ADR-0015, which gave a team one invite code that each new code replaced.

With one code per team, making a new invite cancelled every link already sent, and once members could invite (ADR-0019) one person's new link silently broke another's. Nothing could be cancelled on its own, and nothing expired, so a link in a proxy log or an old chat stayed good forever.

GitHub, Slack and Discord all do the same thing instead: every invite is its own record, with who made it and when, it expires, and it can be cancelled on its own.

## Decisions

**Each invite is a row.** `invite` holds the team, the sha256 of the code (resolved by indexed lookup, as before), who made it, when, when it expires, and, once used, who used it and when, or when it was cancelled. Anyone who may invite makes as many as they like; they never replace each other.

**One use.** An invite is pending until somebody uses it, with `join` or `join_team`, and then it is accepted, by that person. The update that marks it used is conditional on it still being pending, so of two people using one code at once exactly one gets in.

**Seven days.** An invite expires seven days after it is made, as GitHub's do. Expiry is read, not swept: a pending invite past its date is expired, and nothing deletes it.

**Cancel.** Whoever made a pending invite, or an admin of its team, can cancel it. A used, cancelled or expired invite answers exactly like a code that never existed.

**Who sees the list.** An admin sees every invite of the team in the dashboard; a member who may invite sees their own. Cancelling is a dashboard action, not a tool.

## Consequences

- Migration 0006 creates `invite` and drops `team.invite_hash`. Codes made before it stop working, which costs nothing: no server had any users.
- `invite_to_team` makes a new invite and no longer cancels anything.
- The invite link is still the way in (ADR-0019). Expiry is what limits a link that ends up in a proxy's log.
