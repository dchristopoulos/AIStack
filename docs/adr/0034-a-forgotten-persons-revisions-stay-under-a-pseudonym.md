# A forgotten person's revisions stay, under a pseudonym

Status: proposed, 2026-10-16. Amends ADR-0015 (every revision names who pushed it). Finding: the erasure half of STD-15 in [docs/audits/2026-10](../audits/2026-10/README.md).

A person who leaves a server can ask to be forgotten, and today the operator cannot do it. OPERATING forbids deleting a user, because `pushed_by` is a required reference from every skill and revision they pushed: deleting them either fails or takes those rows with it. Some of those rows are other people's. A skill shared into a team is the team's copy, and a teammate who took it holds a copy of their own, both still naming the person who shared it. ADR-0015 rules out a change to one person's account taking anything off anybody else's computer.

## Decisions

**`aistack admin forget USERNAME` erases the person and keeps the rows.** It runs `offboard` first, so every team they were in keeps an admin (a team they ran alone goes to the successor the operator names, as `offboard` takes it) and every computer of theirs goes, with its token, sessions and transfer links. Then, in the same transaction:

- their username becomes `former-` and 8 random hex characters, with their personal team renamed to match, as `rename_user` does;
- their `full_name` is cleared;
- every skill in their own Library is deleted with its revisions and files: nobody else reads a person's Library, and nothing on anybody's computer installs from it.

**What other people hold stays, and names the pseudonym.** A revision they shared into a team, and every copy a teammate took from it, keeps its row, and its `pushed_by` now reads `former-3f9a1c2e`. The pseudonym is random, not derived from the old name, so it cannot be turned back into one; it is stable, so a team can still tell that two revisions came from the same person.

**A forgotten person cannot be forgotten twice.** `forget` refuses a username that starts with `former-`, with a sentence, so a mistyped second run changes nothing.

## Not doing

- Deleting the revisions they shared. That removes skills from teammates' Libraries and computers, which ADR-0015 rules out; a team admin can still remove a team's copy as for any skill.
- A self-service "delete my account" on the dashboard. Erasure is the operator's act, after they check who is asking.
- Rewriting the server log. Its lines name a user by id, and the id stays the user row's id, which now reads as the pseudonym. An operator who must also purge old log files does that with their own log retention.

## Consequences

- `operator_service.forget` and `aistack admin forget USERNAME [--successor TEAM=USERNAME]`, tested on both databases: member lists and revisions show `former-…`, `full_name` is null, the person's computers and own skills are gone, a teammate's copy is untouched, and a second `forget` is refused.
- CONTEXT.md's "Pushed by" says a forgotten person shows as their pseudonym; OPERATING gets "Forget a person".
- This is a trust-boundary change: it deletes, and it changes what provenance shows.
