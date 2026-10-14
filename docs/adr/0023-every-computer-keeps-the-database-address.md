# In local mode every computer keeps the database's own address

Status: accepted, 2026-10-15. Amends ADR-0020, which gave each computer its own database login, handed out by pairing.

ADR-0020 had the owner's connection string pasted once and used to create a login role per computer, so that a lost laptop is one `DROP ROLE`. Those roles cannot change the schema or create the next computer's role; only the owner can. So the owner's credential would either be stored on one computer, which then alone adds computers and upgrades, or pasted again for every new computer and every schema change. Each version adds a feature, a failure mode, and a step someone must remember, to protect one person's skills from that same person's lost laptop.

## Decision

In local mode each computer keeps the database's own connection string, the one Neon or Supabase shows, as `AISTACK_DATABASE_URL` in its agent's MCP configuration, where server mode keeps a machine token. There are no per-computer roles and no pairing. Any computer migrates on upgrade, as ADR-0020 already says, because it holds the credential that can.

A lost computer means resetting the database password at the provider and pasting the new address on the computers that remain. For one person with two or three computers that is a couple of minutes, and it is said plainly where setup offers the choice.

Teams are unchanged. They run in server mode, where an invite admits a person once and each computer holds its own revocable token (ADR-0003, ADR-0022).

## Consequences

- Step 4 of #79 (pairing) is dropped, and with it the need to check `CREATE ROLE` on each provider.
- Setup asks for the address once per computer and writes it into the MCP configuration. On Supabase it is the shared pooler's session-mode address, which works over IPv4 on every plan.
- Every computer holds a credential that can drop the Library's tables. That is no worse than deleting every row, which any login able to write the Library could do, and the provider's backups are the recovery for both.
