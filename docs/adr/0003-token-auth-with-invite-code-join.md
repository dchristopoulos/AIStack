# Personal API tokens with invite-code join, no login system

Status: accepted (amended by ADR-0004: tokens are per-machine, not per-user; amended 2026-08-24: the invite code is a bootstrap bearer principal authorized for `join` only — never a tool argument, so it stays out of transcripts — and machine tokens are authorized for everything except `join`, enforced centrally before tool dispatch)

MCP connections authenticate with a permanent API token. A new user redeems the server's team invite code via the `join` MCP tool (connection authenticates with the invite code just long enough to call `join`), receives the token for their first machine, and embeds it once in that harness's MCP config. Additional machines get their own tokens via `add_machine`. No passwords, no OAuth, no email verification.

Why: the team case needs self-service onboarding (an admin hand-minting tokens doesn't scale) and per-user attribution, but full signup/login machinery buys nothing until a dashboard exists. Tokens are the permanent identity mechanism — dashboard-era login later sits on top without replacing them. Rejected: open registration (reachable = member is unsafe for internet-exposed servers) and admin-created tokens (onboarding bottleneck).
