# Invites are the way in: an invite link creates the account and joins the team

Status: accepted, 2026-10-14. Built under #64. Amends ADR-0003 and ADR-0015.

A new person needs two codes today: the server's invite code to get an account (ADR-0003), then a team's invite code to join a team (ADR-0015). And every account lands in `everyone`, a team nobody created or asked for. It feels like two sign-ups and a default chat room nobody uses.

## Decisions

**A team invite admits a new person.** `join` accepts a team's invite code as well as the server's. With a team code it creates the user, registers the computer, and makes them a member of that team, in one call and one transaction. The bootstrap principal (ADR-0003) gains a second kind: a bearer that resolves, by indexed lookup on its hash as today, to a team. It reaches the same onboarding tools and nothing else.

**An invite is a link.** `/invite/<code>` is a page on the server, like `/setup`: it says which team the invite is for and gives the one sentence to paste into Claude Code or Codex. The page reveals the team's name to whoever holds the link, which is the point of the link and nothing more. A wrong or replaced code shows the same page as no code at all.

**Sign-up is invite-only.** There is no open registration. The server's own invite code, from its configuration, stays: it is how the person running the server creates the first account, and how they admit someone directly.

**Admins invite, and can let others.** A team admin can mark a member "can invite". That member can create invite links and nothing else an admin can. It is a per-member flag like "sees all groups", not a role system; fuller roles wait until someone needs them.

**`everyone` is removed.** No new account joins it. On a server that has it, the migration turns it into an ordinary team, with the server's admin as its admin, so every skill in it stays where people can see it and anyone may leave. Code that branched on the server team's kind loses that branch.

## Unchanged

- A machine's token is still made by the server and returned once, and the agent stores it in its own MCP configuration as the `Authorization` header (ADR-0003). Claude Code and Codex on one computer share it (ADR-0018).
- Making a new invite code still stops the previous one working.
- Nothing about who sees what inside a team changes.

## Consequences

- A leaked team code can now create accounts, not only join a team. Replacing it stops that, as before; expiry and a maximum number of uses are the obvious next protections and are left until asked for.
- The README's setup sentence becomes "open this invite link" for most people. The server's own code is documented for whoever runs it.
- Tests: a team code used with `join` creates exactly one user, one machine and one membership; a replaced code admits nobody; the invite page answers a wrong code exactly as a missing one.
