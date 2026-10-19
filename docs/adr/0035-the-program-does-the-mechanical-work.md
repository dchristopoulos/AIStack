# The program does the mechanical work

Status: accepted, 2026-10-19. Amends ADR-0003 and ADR-0019 for adding a computer, ADR-0012 and ADR-0021 for executing sync, and ADR-0027 for recording which computer added another. The reconciliation rules in ADR-0006 and ADR-0015 still apply.

On a server, the coding agent currently lists files, computes their digests, sends those digests to `sync`, then downloads, unpacks and moves each skill. Local mode already does that work in the program. Server mode should do it there too. The dashboard remains where a person manages their Library and computers; chat remains where they ask for something and answer questions.

It keeps the existing remote MCP connections, requires approval for a new computer by default, and measures sync before adding bulk downloads.

## Decisions

### Run sync on the computer

`aistack sync` reads the server address and bearer from the coding agent's existing AIStack configuration. It uses `fastmcp.Client` to call the existing tools and moves skill bytes through the existing signed transfer URLs. Agents keep their direct remote MCP connection. There is no sync API beside MCP and no local proxy for chat tools.

Extend `bootstrap/agent_config.py` to read remote connections as well as local ones. Respect `CODEX_HOME`, preserve unrelated settings, and never print credentials. When both agents have the same connection, use it once to sync every harness in use. If their server addresses or credentials disagree, stop with an instruction to choose or repair the connection. Do not guess which account to write to. A local-mode entry keeps its current meaning.

Reuse `services/local_skills.py` for observing, packing, validating and installing skills. The command does the following for each global skills folder in use, and for project folders inside the current managed project:

1. Observe file digests and call `sync` for that harness and project.
2. Carry out `install` and `update` through `get_skill` and its download URL. Validate the archive and recorded hash before installing through staging and rename.
3. Pack and upload names under `backup` through `push_skill`. Report validation failures without attempting to bypass them.
4. Return every question and team update for a person to decide. Never delete, enable an undecided skill, replace local edits or take a team update merely because the command ran.
5. Refresh the bundled sync skill from package data where the server requests its standard copy. Respect a person's own Library copy of that skill.

Keep the reconciliation table authoritative. Project discovery must preserve ADR-0026: do not start managing a new project, change its ignore rules, or read or replace a repository's skill without the existing explicit action. First-sync choices about other folders and offers from other computers remain questions unless setup already recorded that choice.

The program must recheck the local observation before replacing a skill. A file changed while the download ran becomes a question, rather than an edit lost to the earlier report. Serialize cooperating sync commands on the computer, and preserve a displaced copy when installation fails. No network or filesystem work belongs inside a database transaction. Tests must cover interrupted installs and two session-start hooks running together.

`get_skill` records the revision before the download completes today. A failed download must leave a retryable install, never cause an unknown local edit to be treated as safe to replace. The program reports the failure and observes the disk again on its next run.

### Run it at session start

Setup installs `aistack sync --hook` as the session-start hook, using the installed program's full path. It runs the same command as manual sync. It is not a daemon and needs no server-initiated messages, so ADR-0013 stands.

Manual sync reports what installed, what updated, the revisions and who pushed them. Hook output is empty when nothing needs the person's attention. When questions remain, it gives the agent the facts, the permitted choices and the tool calls that carry out an answer. Warnings about replacement or lost edits must survive this formatting. Successful automatic work stays available in manual output without filling every new chat.

An unavailable server produces a short failure notice and leaves installed skills usable. Bound network waits and polling; a hook must not hold a session indefinitely. Update the current hook timeout as needed, rather than leaving the existing ten-second reminder timeout in place for a full sync.

The bundled server sync skill first tells the agent to run `aistack sync` when installed, then act on its questions. Keep the existing shell steps for cloud sessions and computers without the program. A failed program sync is a reported failure, not permission to repeat writes through the fallback.

### Add a computer with a code

In Computers, Add a computer immediately makes a code and shows one command:

```text
uvx aistack-mcp join https://aistack.example.com K7QM-4TXP-9WNB
```

The person runs it on the new computer. A sentence to paste into their coding agent carries the same command as a fallback. The command carries no permanent machine token. Use the server's validated public address, quote shell arguments for the destination platform, and give installation help when `uv` is missing.

The dialog says that the code works once, gives its actual expiry, offers Copy and Cancel code, and puts configuration under Options:

| Option | Default | Other choices |
|---|---|---|
| Name for the new computer | Its hostname | A name supplied here |
| Expires in | 24 hours | 1 hour, 7 days |
| Coding agents | Find them | Claude Code, Codex |
| Skills | Add my Library's skills | Start empty, choose later |
| Sync at every session start | On | Off |
| Ask me before it connects | On | Connect without asking me |

Changes to an unused code update its options without changing the command. Once a computer claims it, freeze the options shown for approval. To change them, cancel and make another code. Shortening or extending expiry must not revive an expired code or extend it beyond seven days from creation.

Pending codes appear under Computers with expiry and Cancel. Poll `/api/state` while the dialog is open to show a waiting request, Approve and Deny, and the connection result. Name and operating system describe what the new computer reported; they do not prove its identity. Show when the request arrived. A connected computer and completed setup are separate states: report agents found and skills installed only after the program confirms those steps.

The new computer does not need a username. The code already names the account. It adds a machine to that account and never creates a user or joins a team. Duplicate computer names are refused without echoing a credential.

### Store and redeem codes as credentials

Each code has its own record with the account, issuing computer, creation and expiry times, options and state. Store only the sha256 of its normalized value, under a unique index. Use a cryptographic random generator. A user may have at most five live codes, counting requests waiting for approval. Enforce that limit under concurrent creation on both databases.

Use twelve characters from `23456789ABCDEFGHJKMNPQRSTUVWXYZ`, displayed in three groups of four. Accept ASCII letters in either case, with or without the two grouping dashes. Reject other spellings without reflecting them. This alphabet has 31 characters after excluding `0`, `O`, `1`, `I` and `L`, giving about 59.4 bits of entropy. Do not call it a 32-character alphabet or claim exactly 60 bits.

Unknown, expired, cancelled, denied and already claimed codes give the same refusal. Count refused attempts through the existing failure limiter, including a code that passed bearer verification but lost a redemption race. Resolve hashes by indexed lookup; do not compare every stored code in Python. Rate limiting is per client address and in memory today. It limits online guessing from one address, not a distributed attacker or an operator who restarts the service.

The code belongs to its issuing account and computer. Removal or token rotation of that computer invalidates its uncompleted codes and requests, as does offboarding or forgetting the person. Bind issuance to the current token as tickets do in ADR-0027; retaining only a nullable provenance reference is insufficient. Check this again during redemption and approval, inside the transaction that changes state.

The operator's `aistack admin register-machine` can issue a recovery code when no working computer remains. It records operator issuance instead of inventing a computer as its maker. This deliberate recovery path cannot require approval on the missing computer. The operator checks who is asking, and the terminal identifies that the code connects without approval.

Codes are bearers, never tool arguments, URL paths or query parameters. Only creation returns the plaintext code or the command containing it; later dashboard state returns status and expiry. Do not store the command in browser persistence. Sanitize names in output, keep protocol payload logging suppressed, and never log codes, request credentials, permanent tokens or signed transfer URLs. A command pasted into a terminal can remain in shell history; expiry and one use limit that exposure.

Joining and syncing across computers use HTTPS with certificate verification. Plain HTTP is accepted for a server on the person's own network: a loopback or private address (the RFC 1918 and RFC 4193 ranges, and 100.64.0.0/10, which VPNs such as Tailscale use), or a name that resolves only to such addresses. The command then prints one line saying the connection is not encrypted. A server at a public address over plain HTTP is refused unless the person passes `--allow-http`, and the command then says that anyone on the network path can read the computer's key. Do not forward credentials across an origin-changing redirect or attach the permanent bearer to transfer requests; those URLs carry their own scoped tickets. Approval cannot protect a token sent over an unencrypted connection, so `docs/OPERATING.md` shows how to serve AIStack over HTTPS with a reverse proxy or a VPN.

### Bind approval to one waiting request

Approval is on by default. Someone who steals an unused code can otherwise register a computer with full access to the person's Library. They could push instructions that the person's other computers then install as their own update. One use and expiry alone do not stop that.

The protocol must distinguish the short code from the credential that collects an approval:

1. An initial `join` authenticated by a computer code atomically reserves that code for one request. It allocates the future machine id and returns a separate, random request bearer with 256 bits of entropy, once. Store only its hash. It expires with the code and reaches only its own onboarding status and completion flow.
2. The program polls with that request bearer. The short code cannot poll, change the request or collect a token after reservation. No machine token exists while approval is pending.
3. The signed-in owner approves or denies that request in the dashboard. Scope every action to the session's user and issuing computer, require `X-AIStack-Request`, and recheck expiry and revocation. Denial and cancellation end the request.
4. After approval, one poll atomically consumes the request, creates the machine and its hashed permanent token, and returns that token to that request bearer only. With approval disabled, the same request completes without waiting for a dashboard click. Two redeemers or two completion polls cannot both win.

Reuse `join` with additive, explicitly selected pairing inputs and result variants. Existing server and team invite calls keep their arguments and results. Both the computer code and request bearer are bootstrap credentials. `AuthMiddleware` still denies them every machine-scope tool. Within `join`, each credential kind reaches only its own operation; a computer code cannot create an account, and an invite cannot complete a computer request. Recheck credentials in the tool transaction rather than trusting the verifier's earlier read.

Each poll is one short request and transaction. Waiting happens in the client between requests, never while holding a database lock. The server need not keep a connection open or retain an in-memory approval queue. A restart does not approve a request; the person can reopen a signed-in dashboard to inspect it.

A request bearer is a temporary secret, held only by the joining program. Keep an interrupted request's bearer in a restricted local recovery file until it completes or expires. It is not a second permanent token store. If the initial response is lost before that bearer is saved, cancel the code and issue another. If the token response is lost after the server commits, the hash cannot recover it. Show recovery instructions to remove the incomplete computer and issue another code. Do not silently mint another machine or keep recoverable plaintext tokens on the server.

Approval reduces the risk of a leaked computer code. It is not a second factor against an already stolen machine token or dashboard session, both of which already grant account access. A leaked code can also be reserved to deny its owner use; cancellation and a new code recover from that without granting access. Approve only a request the person just initiated, not an unfamiliar name in an open dialog.

### Finish setup on the new computer

Before redemption, check that configuration files are parseable, selected agents can be configured and the program can be installed. After approval:

1. Install the program with `uv tool install aistack-mcp`, reusing local setup. Hooks use its full path and start without fetching a package. Initial installation and server sync still need the network.
2. Write the remote MCP entry and the token into the selected agents' existing configuration files, preserving unrelated content. Apply the tool approvals setup already uses. Keep credentials out of subprocess arguments and error output; write config files with restricted permissions and replace them whole.
3. Install the bundled server sync skill and the hook when selected. Preserve other hooks. Keep the existing agent hook trust step where required.
4. Apply the explicit initial-skills choice through existing placement services and `get_skill`, then sync. Add my Library's skills means active Library skills in each selected harness, excluding archived skills, team offers and project placements. Never replace a different local skill under the same name without a question. Start empty leaves Library placements undecided; it does not suppress backup of local skills, which remains private.
5. Print a short result naming the agents connected, skills installed and anything still needing a decision. Ask the person to restart the coding agent once.

The permanent token lives only in agent configuration after setup. A protected temporary file may bridge a partial configuration failure; remove it when setup succeeds. Rerunning on an already connected computer resumes local setup from that configuration without redeeming the used code again. Only a successful authenticated check of that existing connection warrants saying it is already connected. Every other used-code refusal stays generic.

### Detect an accidentally copied connection

Reuse `bootstrap/hardware.py` to read the operating system's computer id. Send `sha256(machine_id + hardware_id)` as an optional `fingerprint` on `sync`. Define the byte encoding once and test it across platforms. Never store, send or log the raw hardware id.

Add a nullable `machine.fingerprint_hash`. The first supplied fingerprint binds it atomically; later supplied values must match. The program obtains its authenticated machine id from an additive sync result field before computing the fingerprint. An initial call to discover that id performs no disk actions; the fingerprint-bearing call must succeed before the program downloads or pushes anything. During computer pairing, return the reserved machine id before completion so the joining program can bind the fingerprint when the machine is created.

A mismatch refuses the sync with a sentence such as:

> This looks like a different computer using macbook's key, for example after restoring a backup. Add it as its own computer from the dashboard with Add a computer, and remove macbook if it is gone.

Do not auto-register a replacement or reset the stored fingerprint. If an operating system reinstall changes the id, the same recovery applies. Where no hardware id can be read, omit the fingerprint and state the limit in the command's diagnostic output.

This detects accidental copies when the ids differ. It does not attest hardware or prevent token theft. An older client may omit the argument, a modified client may lie, and a full system clone may preserve the operating system id. Old clients remain accepted. When first binding an existing connection, whichever computer supplies a fingerprint first wins; there is no evidence to recover the original id. Users revoke a stolen token by removing the computer, as today.

### Keep older clients working

Add tables and nullable columns through compatible migrations only after checking all three conditions in ADR-0031. Keep pairing state in its new records until a machine is ready, so older code never sees an unauthenticated placeholder machine. Absence of a fingerprint remains permitted and never claims protection for an older caller.

Changing `add_machine` from token-bearing setup to a computer code is not compatible merely because `command` and `codex_config` still exist. A join command is not a TOML configuration block. Introduce an explicit opt-in code flow and additive results while preserving legacy calls and their documented fields. New dashboard and program setup use codes. Make codes the default for legacy callers, and remove the old fields, only in an owner-approved minor release. Until then, disclose that legacy `add_machine` can still issue a token directly. Do not return a permanent token alongside a new computer code.

The program checks the server's advertised tool schema before using new inputs. An older server must produce a clear upgrade instruction, not a failed pairing attempt or a silently weaker approval flow. Existing remote agents and the old sync skill continue to work. No release or package publication is part of accepting this ADR.

### Measure before adding bundles

Start with one `get_skill` and one download per install. It preserves the single path that records the installed revision and issues a scoped transfer URL. Do not assume a network round trip costs milliseconds.

Measure a fifty-skill first sync and a no-change sync against a server. Record archive sizes, environment, network latency, request counts and elapsed time in the implementation PR. Include hook startup time. A no-change run should transfer no archives, mint no revisions and change no placements; existing last-synced timestamps may still advance. It is not a promise of zero database writes.

The target is session-start sync in seconds. If measurements miss that target, propose a bundle download with equivalent visibility, revision recording, validation and failure recovery. Do not add it in advance or claim the target met without measurements.

## Alternatives considered

- Keep the agent doing filesystem work. This avoids a new client command but leaves routine sync slow and dependent on many generated shell commands.
- Start the program over stdio in server mode and forward every chat tool. This centralizes the connection but makes every session depend on a local installation, including cloud sessions. It also adds a proxy to calls that already work directly.
- Add separate HTTP sync and onboarding APIs. Existing MCP tools and signed transfer routes already provide the operations. Polling `join` keeps the authorization policy in the same place.
- Connect on a code alone by default. It removes an approval click but turns a leaked unused code into account access. Offer it explicitly per code, including operator recovery.
- Require fingerprints on every call. Older clients and computers without readable ids would stop working, while a client-controlled id still would not prove hardware identity.
- Bundle every skill download now. Measure the program first; archives and a second install route are unnecessary until the measurements justify them.

## Consequences and acceptance checks

The first implementation change is server-mode sync, followed by the copied-computer check, computer codes and dashboard approval, joining from the terminal, and user documentation. Measure before calling the work complete. Each change has its own pull request.

Use real HTTP tests to drive the program through install, update, backup, questions and recovery with a temporary home. Cover credential selection, unchanged configuration, preserved local edits, project exclusions, offline failures and quiet hook output. Run the SQLite suite for every PR and PostgreSQL for queries, migrations and concurrency. Browser tests exercise the dialog by its words and confirm changes through `/api/state`.

Computer codes, approval, fingerprints and automatic filesystem writes change trust boundaries. Review their diffs and watch enforcement tests fail with the checks removed. Use barriers at the exact race window for reservation, completion, cancellation, expiry and the pending-code limit. Verify bootstrap credentials cannot reach machine tools, another account cannot see or approve a request, and a code cannot retrieve an approved request's token. Verify removal and rotation invalidate requests, and secrets never reach output or logs.

On acceptance, update the affected sections of `docs/DESIGN.md` before implementation; this proposed ADR does not override that plan. Add this rule under MCP tools in `AGENTS.md`: "The program does mechanical work; the agent handles what the person asks and decides." Add Computer code to `CONTEXT.md` and update the README, setup instructions and operator recovery guide with the shipped behavior. Keep proposed behavior out of current setup instructions until it works.
