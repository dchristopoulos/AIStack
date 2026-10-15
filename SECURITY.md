# Security policy

AIStack moves instructions onto people's coding agents, so a flaw in it can put text in front of an agent that its owner never chose. Reports are welcome and taken seriously.

## Reporting a vulnerability

Report privately through GitHub: open the repository's **Security** tab and choose **Report a vulnerability**. Please do not open a public issue, discussion, or pull request for a vulnerability until a fix has been released.

A useful report says:

- the release (`uv tool list` shows it in local mode; on a server, the image tag) or the commit;
- how AIStack was run: a server or local mode, and SQLite, PostgreSQL, or a GitHub Library;
- the steps that reproduce it, ideally as a script or a failing test against a fresh server filled with `scripts/demo_seed.py`;
- what an attacker gains, and what they must already hold (an invite code, a machine token, a dashboard session, write access to a Library's repository).

Use demo data only. Never send a real machine token, invite code, sign-in link, or database address.

## What happens next

AIStack is maintained by one person, so these are intentions rather than guarantees:

- an acknowledgement within a week;
- an assessment, and a fix or a mitigation, as fast as the severity calls for;
- a release with the fix, then a published GitHub security advisory that credits you, unless you prefer otherwise.

Please allow a fix to be released before you disclose.

## Supported versions

Only the latest release is supported: the newest `aistack-mcp` on PyPI and the newest `ghcr.io/dchristopoulos/aistack` image. A fix ships as a new patch release. Releases before 1.0 are not maintained in parallel.

## Scope

In scope is anything that breaks a promise the design makes. The promises are written down in [docs/DESIGN.md](docs/DESIGN.md) (Security posture, Push validation, The sync contract) and in [AGENTS.md](AGENTS.md) (Authorization, Secrets and logs, HTTP routes). For example:

- reading or changing another person's Library, computers, or placements;
- telling a team, group, or skill you may not see apart from one that does not exist;
- acting as a team admin, or sharing into a group, without that right;
- a machine token, an invite code, a transfer ticket, or a sign-in link reaching a log, an error, or a tool result;
- an archive that passes push validation and should not, or an install that writes outside its skills folder;
- a cross-site request that changes anything on the dashboard;
- in local mode, reading or writing outside `AISTACK_HOME` and the skills folders, or a Library's repository putting files or commands anywhere else.

Out of scope, because they are the design rather than a flaw in it:

- A teammate sharing a new revision of a team's skill. It reaches nobody until they accept it, and it carries the sharer's name.
- Someone doing what a credential they hold allows: a machine token, the server's invite code, a team's invite code, the database address in local mode, or write access to a GitHub Library's repository.
- Anything that needs control of the person's own computer or coding agent.

Known weaknesses already being worked on are listed in [docs/audits/2026-10](docs/audits/2026-10/README.md). A report that finds one of them exploitable in a way the audit missed is still welcome.

## For whoever runs a server

- Serve it over HTTPS and set `AISTACK_PUBLIC_URL` to that address. Behind a proxy that ends TLS, that setting is what makes every address the server hands out an `https://` one and marks the dashboard's cookie secure.
- Keep the server's invite code out of group chats, and rotate it when someone leaves ([docs/OPERATING.md](docs/OPERATING.md)).
- Keep the image current, and back the database up before upgrading.
