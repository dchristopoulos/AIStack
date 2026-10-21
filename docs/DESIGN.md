# AIStack design

Scope, architecture, and schema for the MVP, settled 2026-08-21, revised 2026-08-24 after two external design reviews, 2026-10-13 after research into what the client can carry (ADR-0010 to ADR-0012), 2026-10-14 for the personal space, teams, groups, migrations, and the dashboard (ADR-0015 to ADR-0017), 2026-10-16 to match the code after the October audit, and 2026-10-20 for program sync and computer codes (ADR-0035). Vocabulary lives in `CONTEXT.md`. Decisions and their reasoning live in `docs/adr/`. This document is the current plan, so where anything else disagrees with it, this wins.

## 1. What AIStack is

A self-hosted, open-source control plane for AI development configuration. A team, or a solo developer with several machines, runs one AIStack server. It holds the canonical copies of their skills, and later their rules, agents, hooks, and MCP server definitions. Each person has a private space, the Library, that mirrors their machines and is the only place those machines install from. They share skills with teams, and with groups inside a team, and take what others shared. The web dashboard is where they see and manage all of it; MCP connects their coding agent to their account, so the everyday actions are also a sentence in chat.

Core promise:

> Configure once. Keep your AI stack in sync across developers, projects, machines, and harnesses.

Two use cases drive the design:

- **Small team**: skills shared with a team or a group in it. Every member sees what was shared and by whom, and takes what they want with one sentence in chat or one click.
- **Solo dev**: same tools on every machine (desktop, MacBook, work laptop) and eventually every harness (Claude Code, Codex, ...).

The design bar is maximum UX: AIStack exists to make configuration simpler, so any feature that makes chat interactions more complicated than the problem it solves is out. When in doubt, do the smart thing silently where no data can be lost, and ask one clear question where it can.

Not a hosted SaaS. Whoever wants AIStack deploys it themselves: a company on its server, a solo dev on a VPS or home server. The project ships a one-container deploy and documents patterns (VPS, Tailscale); it does not solve hosting for you (no LAN discovery, no peer sync).

## 2. Stack

Settled:

```text
Python
Poetry
SQLAlchemy       synchronous; FastMCP threadpools plain `def` tools, so sync drivers
                 never block the event loop (see ADR-0005)
FastMCP          the MCP endpoint, and the Starlette application every other route is
                 registered on: transfer, setup, health, and the dashboard (ADR-0017)
SQLite           default; DATABASE_URL switches to Postgres via psycopg (ADR-0002)
Alembic          schema migrations, applied at startup in one transaction (ADR-0016)
```

SQLite connections set `PRAGMA journal_mode=WAL`, an explicit 5-second busy timeout (the Python default, kept explicit because it is policy, not accident), and `PRAGMA foreign_keys=ON`, because SQLite ignores `ON DELETE CASCADE` without it.

No FastAPI and no frontend framework: the dashboard is one HTML file with its own CSS and JavaScript, shipped as package data, with no build step (ADR-0017).

## 3. Decisions (ADRs)

- **ADR-0001: Full local sync, runtime proxy dead.** Skills are fully materialized on disk (body + bundled files) and run natively with zero runtime dependency on AIStack. The MCP is only the install/sync channel.
- **ADR-0002: SQLite by default, Postgres via `DATABASE_URL`.** One container beats two. Write volume is tiny (measured: five concurrent 20-file pushes drain in under 25 ms).
- **ADR-0003: API tokens, invite-code join, no login system.** Users self-onboard with the server's invite code; machine tokens are the permanent identity mechanism. Mechanism amended 2026-08-24: FastMCP auth guards the endpoint before tool dispatch, so the invite code is presented as a bootstrap bearer token, not a tool argument. See §4 Auth.
- **ADR-0004: Server holds desired state per machine.** `machines` and `machine_skills` live server-side; sync reconciles desired vs actual, never resolving conflicts silently.
- **ADR-0005: Synchronous SQLAlchemy.** Reverses the earlier async convention. FastMCP threadpools sync tools by default; aiosqlite is itself a thread wrapper; the measured workload never justifies async discipline.
- **ADR-0006: Explicit disable; sync never deletes.** Local deletion is never inferred as intent. Sync acts silently only where no data can be lost, and only `disable_skill` may cause a local file deletion.
- **ADR-0007: Skill-specific tables; the generic resource model is deferred.** A single `RESOURCE` family serving skills, rules, hooks, agents, and MCP definitions was designed and rejected for now: those types don't share a materialization lifecycle, and generic tools would make chat carry architecture vocabulary for no user benefit. Trigger conditions for revisiting it are named in the ADR.
- **ADR-0008: One admin, enforced by a partial unique index.** Amends the `is_admin` schema comment: the guarded UPDATE is safe on SQLite and wrong on Postgres, so the index is the enforcer, the update is the fast path, and a savepoint absorbs the loser.
- **ADR-0014: SQLite transactions take the write lock at BEGIN.** `BEGIN IMMEDIATE`, issued by SQLAlchemy with the driver's own transaction handling off. Without it concurrent writers fail outright on a stale snapshot instead of waiting; with it savepoints are also always inside an explicit transaction.
- **ADR-0009: Length-prefixed canonical content hash.** Reverses the JSON canonicalization above before implementation: the bytes that are hashed must be unambiguous, and that cannot rest on two JSON serializers matching. Length-prefixed framing needs no library.
- **ADR-0010: Skill bytes travel over signed transfer URLs.** `push_skill` and `get_skill` return a short-lived signed URL; the agent moves a gzipped tar with `curl` and `tar`. File content never passes through the model, which is slow, inexact, and capped by the client.
- **ADR-0011: The server alone computes the content hash.** `sync` receives a sha256 per local file and the server applies the ADR-0009 framing. No hashing script ships to any machine.
- **ADR-0013: The MCP endpoint is stateless.** No session is kept, so a restart strands no client and a new machine can call `join` with one HTTP request, which is what makes setup a single paste.
- **ADR-0012: Sync returns its questions as data.** Claude Code supports elicitation, and sync does not use it: returned data works in every harness, and the agent asks better questions in chat than a form does.
- **ADR-0015: A personal space per user, teams to share into, and groups inside a team.** A machine installs only from its user's own skills. Sharing copies a skill into a team; taking copies it back out. A teammate's change is an offer, never applied by sync.
- **ADR-0016: Schema changes are Alembic migrations, applied at startup in one transaction.** All pending migrations land or none do, a failed one stops the server, and there are no downgrades.
- **ADR-0017: The dashboard is served by the server, and a link from chat signs you in.** Same process, same services, no second framework, no build step, no passwords.
- **ADR-0018: One account for every coding agent on a computer, Codex first.** A harness is a named skills folder: `claude_code` (`~/.claude/skills`) or `agents` (`~/.agents/skills`, read by Codex, Gemini CLI, Kimi Code, Cursor, Copilot CLI, opencode and Amp). A skill is placed per computer and harness, each placement its own decision, so the reconciliation table is unchanged and applies per folder. One token per computer. Setup offers a session-start hook that tells the agent to sync. Projects, tools without `SKILL.md`, and a generic resource model are left out.
- **ADR-0019: Invites are the way in.** A team invite link creates the account, registers the computer and joins the team in one paste. Sign-up is invite-only; the server's own code is for the person running it. An admin can let chosen members invite. The `everyone` team is removed; existing ones become ordinary teams.
- **ADR-0020: AIStack runs on your own computers, and you choose where your Library lives.** Server mode as today, the only mode for teams; and a local mode where each computer runs AIStack over stdio and shares only the storage. A person picks a computer that stays on, a free PostgreSQL (Neon or Supabase), or a private GitHub repository, and setup does the work wherever a tool already can. Google Drive and a SQLite file in a synced folder are rejected.
- **ADR-0021: One connected agent syncs every skills folder on its computer.** The server tracks folders, not callers. The `sync-aistack` skill finds the folders the computer's agents read and syncs each, so Codex on a computer where Claude Code is connected needs no connection of its own. A folder's first sync is reported, and the agent asks once whether both folders should hold the same skills. Setup runs from Claude Code or Codex.
- **ADR-0022: An invite is a record.** Each invite is its own row: one use, pending until accepted, seven days, and cancellable by its maker or an admin. Making another cancels nothing.
- **ADR-0023: In local mode every computer keeps the database's own address.** No per-computer logins and no pairing: each computer's MCP configuration holds the provider's connection string, any computer migrates, and a lost laptop means resetting the database password and pasting the new one on the others. Teams stay on server mode with revocable machine tokens.
- **ADR-0024: Older releases keep working through additive upgrades.** Each migration says whether releases before it still work. The database records the oldest schema that can use it, so an older computer keeps running on a schema that only grew, and is refused with one clear sentence (in local mode, through its agent) after a breaking change.
- **ADR-0025: A Library on GitHub is a log each computer replays.** Each computer keeps its own SQLite copy; the private repository holds one file per change, in a folder per computer, so git never conflicts. Replay goes through the same service calls, in a fixed order, and a copy that disagrees is rebuilt from the whole log.
- **ADR-0026: Skills folders inside a project.** A project is a git repository known by its normalised remote, and its two skills folders at the top level are harnesses one level down, placed per computer in tables of their own. AIStack writes only skill folders git ignores there, hiding each from git through the clone's `.git/info/exclude`, and leaves the repository's own skills alone. On a server, projects are built end to end; local mode replays project events, and its project actions are tracked in [#190](https://github.com/dchristopoulos/AIStack/issues/190).
- **ADR-0027: A dashboard session belongs to the computer that opened it, and its owner can remove that computer.** Removing a computer, or giving it a new token, ends its token, its sessions and its transfer URLs at once.
- **ADR-0028: A team can be deleted, and nobody is kept in one.** The last member leaving deletes the team; an admin can delete it. Members' Library copies stay.
- **ADR-0029: Sharing over a group's skill takes being able to share into the group.**
- **ADR-0030: On SQLite, a request that only reads begins deferred.** Read sessions refuse to write and neither wait for the writer nor make it wait.
- **ADR-0031: A compatible migration also keeps older releases' data meaningful.** Additive shape alone is not enough: older releases must still write and read every value safely.
- **ADR-0032: A GitHub Library's log is ordered by a hybrid logical clock.** An event's time is the later of the wall clock and just after the newest event its copy holds, so a computer whose clock runs ahead cannot sort its older edit after a newer one. A rebuild replays into a new file beside the copy and swaps the rows in, so other sessions keep reading meanwhile.
- **ADR-0033: A removed computer comes back when it changes something.** In local mode, removal tidies the list: a later change from the removed computer adds it again, so replay never stops and nothing is lost. Cutting a computer off there means revoking its access to the repository.
- **[ADR-0035: The program does the mechanical work](adr/0035-the-program-does-the-mechanical-work.md).** The installed program executes server sync and session-start hooks through the existing MCP tools and transfer URLs. Computer codes connect another computer, with approval on by default; an optional fingerprint detects accidental copied connections. Keep legacy clients working through additive inputs, results and compatible migrations.

## 4. Product plan

One Docker container. One volume (SQLite file + config). FastMCP served over streamable HTTP, plus plain HTTP routes on the same port: two that carry skill archives (ADR-0010), setup, health, and the dashboard with its JSON API (ADR-0017). The same package is also local mode (ADR-0020): `aistack` over stdio, started by the agent, with a few terminal commands beside it (§4 Local mode). Nothing syncs in the background; the only background work is local mode's daily check for a newer release. The installed program syncs both skills folders on its computer through the existing remote MCP connection: Claude Code's and the shared agents folder that Codex and others read (ADR-0018, ADR-0021).

### State model (ADR-0004)

The server holds **desired** state: which of a user's own skills are enabled per machine and harness. The local disk is **actual** state. Sync reconciles the two. Each machine belongs to one user and authenticates with its own permanent token: one lookup identifies both user and machine.

### Auth

Two MCP principals, one centralized authorization rule enforced before any tool logic runs:

- **Bootstrap principal**: an invite code, computer code or pairing request bearer. Invites create accounts as before (ADR-0019); computer codes only add a computer to the issuing account. Each credential reaches only its own `join` operation and no machine tools. Recheck it inside the tool transaction (ADR-0035).
- **Machine principal**: a machine token (sha256-hashed at rest). May call everything except `join`.

The dashboard has its own credential and reaches no MCP tool: a session cookie holding a signed ticket for one user, set by opening the link `open_dashboard` returns (ADR-0017). `/app` and `/api/*` refuse without it, and a request that changes state must also carry a header a cross-site form cannot send.

`join` creates the user and their first machine and returns the permanent machine token. The agent writes it into the MCP config; from then on it authenticates every connection silently. The first user to join is marked the server's admin (`is_admin`), but no code reads that mark today, so it grants no power: server-level operations are `aistack admin` commands (`docs/OPERATING.md`).

**Secrets rule.** Tokens appear exactly once: in the `join` / `add_machine` result (and therefore in the local Claude Code transcript, accepted for the MVP), or in what legacy operator commands print to the terminal. Computer-code setup keeps the permanent token in restricted agent configuration and never prints it; recovery can issue a code instead. They never appear in server logs, HTTP logs, error messages, or any other tool result. The invite code is never emitted in logs, errors, tool arguments, or tool results; it exists only as the bootstrap `Authorization` bearer and as operator-supplied config. A team's invite code is made by the server, stored only as a hash, and appears once, in the answer to the admin who asked for it. A dashboard link is a credential for five minutes and is never logged.

**Revocation** (lost or stolen machine): the user removes the computer on the dashboard, which ends its token, its dashboard sessions and its transfer URLs at once (ADR-0027); the user's last computer cannot be removed there. The operator can also remove the computer with `aistack admin remove-machine`. If that was the user's only machine, recovery is `aistack admin register-machine` or `aistack admin rotate` for that same user. Never delete the user: `pushed_by` is a non-null FK from `SKILL` and `SKILL_VERSION`, so deleting a contributor either fails or destroys provenance.

### Tools (all thirteen, nothing else)

```text
join(username?, machine_name?, os?, full_name?, pairing?, fingerprint?, setup?)
                              → creates user + first machine; returns the machine token
                                (bootstrap principal only; first user becomes admin.
                                `os` is required: MACHINE.os is NOT NULL and MCP cannot
                                reveal the client's platform; `full_name` is what
                                teammates read beside the username)
add_machine(name?, os?, computer_code?, options?)
                              → registers another machine for this user; returns a
                                paste-ready Claude Code command and Codex config
                                block, each with that machine's token (legacy). Explicit
                                computer_code opt-in returns a one-use code instead;
                                join pairing reserves, polls and completes that request
list_skills(team?, query?)    → the caller's own skills, then every team skill they may
                                see (this is also the search, and the only discovery
                                mechanism, sync is not); team keeps one team's, query
                                those whose name or description holds the words
get_skill(name, team?, harness?, replace?, project?)
                              → with a team, first takes that team's latest revision into
                                the caller's own skills; a skill of theirs of that name
                                that was not taken from it is refused unless replace is
                                true, because the user must agree first. Then enables the skill in that
                                harness of the calling machine and returns the
                                latest revision's metadata, its file list, the folder to
                                install into, and a signed download URL for the archive.
                                The one "enable + give me the files" verb: install,
                                restore, re-enable, adopt all resolve to it. With a
                                project, the folder is that project's, relative to its
                                top level
push_skill(name | names, origin?, harness?, project?)
                              → returns a signed upload URL for that skill name, or with
                                names one per valid name and the rest refused, so a
                                whole backup list is one call (local mode: one push to
                                a GitHub Library). The
                                upload creates the revision in the caller's own skills
                                (existing name = new revision) and enables the skill in
                                that harness of the calling machine, or in that
                                project's folder, which the upload checks it still
                                manages. It shares nothing
share_skill(name, team, group?)
                              → copies the latest revision of one of the caller's own
                                skills into a team or one of its groups
list_teams, create_team(name), invite_to_team(team), join_team(code)
                              → the teams the caller is in; make one; get its invite
                                code (admins); join one with a code
open_dashboard                → a short-lived link that signs a browser in (ADR-0017)
sync(local: {name: {path: sha256}}, harness?, here?, project?, repository?, fingerprint?, identify?, rules?)
                              → reconcile desired vs actual for one harness; see the sync
                                contract. `here` names the session's repository, and
                                `project` syncs that project's folder instead (ADR-0026).
                                `rules` reconciles rule files too (ADR-0036)
disable_skill(name, harness?, project?)
                              → enabled = false in that harness of this machine, or in
                                that project's folder; the agent then deletes the folder
```

`harness` is `claude_code` (`~/.claude/skills`) or `agents` (`~/.agents/skills`), listed in the tool schema; the registry is `services/harnesses.py`, with each folder spelled per operating system. Omitted, it means `claude_code`, so a computer set up before harnesses existed keeps working with the skill file it already has (ADR-0018). An upload URL carries the harness it was issued for.

There is no `delete_skill` tool. Removal is a dashboard action, in two forms. Removing a skill from the Library keeps its row as a marker (`archived`) and disables it on every machine, so each machine's next sync asks whether to delete the folder and does not back it up again. A team admin removing a skill from a team deletes the team's copy and its history; copies members already took are theirs and are untouched. Deleting a single revision is not offered: a fresh install after deleting the latest would silently receive an older one, and a safe version needs preview-confirm plus tombstones.

### Local mode (ADR-0020)

Local mode is the same package run by each computer for one person, with no server. `aistack` with no command serves the Library over stdio to the coding agent that started it (`mcp/local.py`). Over stdio the caller is whoever could start the process, so it has no authentication and registers only tools about that person's own Library: no team tool and no onboarding tool. The Library lives in a SQLite file on this computer, a PostgreSQL database every computer reaches (ADR-0023), or a private GitHub repository each computer replays as a log (ADR-0025, ADR-0032). Every change is also recorded as a `library_event` in the same transaction.

Its tools do the disk work themselves, so no transfer URL is involved: each reads a skills folder before its transaction and writes one after it commits.

```text
sync(harness?)                → reads the folder itself and reports as the server's sync does,
                                plus `folders` (every skills folder this computer has an
                                agent for), `harness` (the one this call synced),
                                `library_reachable` and `library_problem` (a GitHub Library
                                that could not be reached), and `new_computer`. It keeps the
                                sync-aistack skill current; `team_updates` is always empty
list_skills                   → the skills in the Library, with `library_reachable` and
                                `library_problem`
get_skill(name, harness?)     → installs the latest revision into that folder, after
                                checking the files against their stored hash; returns the
                                skill, its revision, and the `folder`
push_skill(name, origin?, harness?)
                              → backs the folder up to the Library and enables it there;
                                returns `revision`, `created`, `unchanged`, and `shared`
                                (false when a GitHub Library could not be reached, so the
                                revision waits on this computer)
disable_skill(name, harness?) → disables the skill in that folder and deletes the folder
open_dashboard                → starts the dashboard on 127.0.0.1 inside this process and
                                returns a sign-in link
```

The `aistack` command (`bootstrap/__main__.py`) also takes these terminal commands: `serve` runs the server; `dashboard` serves the Library's dashboard on 127.0.0.1 and opens it; `setup` prints local mode's setup steps and `sync-skill` its sync skill (there is no server to fetch them from); `check` sets up this computer's side of the Library once and says whether it works; `github` signs in to GitHub and finds or creates the private repository a Library lives in; `export` writes every skill in the Library to a folder; `sync` executes server sync and `join <server> <code>` connects another computer (ADR-0035); `status --hook` is local mode's session-start hook, which writes the person's rule files and reminds the agent to sync only when a dry run of the skills sync, rolled back, has something to do or a rule question is left; `move github`, `move postgresql` or `move here` moves the Library with its history; `connect claude-code` or `connect codex` connects an agent to it. When local mode runs from a uv tool install, `bootstrap/self_update.py` checks for a newer release once a day in a background thread and installs it for the next start.

### Flows

**Onboarding (admin)**: set `AISTACK_INVITE_CODE` in env, run the container, share the code with the team over something private. The admin already knows the code because they set it; it is never printed. Startup logs confirm an invite code is configured without echoing its value. The admin joins first and becomes admin.

**Onboarding (user)**: paste one sentence into Claude Code: "Set up AIStack: fetch `<server>/setup` and follow it. Invite code: …". The server serves those instructions itself, with its own address filled in, because they cannot come from the vault they set up. The agent creates the skills directory if missing, fetches the `sync-aistack` skill from the server, calls `join` with one HTTP request carrying the invite code as its bearer (ADR-0013), writes the returned machine token into the MCP config at user scope, and tells the user to restart Claude Code once. After that restart, installed skills load live, mid-session, no further restarts (Claude Code watches the skills directory, verified against its docs; the one exception is a directory created after session start, which this flow handles by creating it first).

**Adding a computer** (ADR-0035): Computers → Add a computer immediately creates a one-use code and shows `uvx aistack-mcp join <server> <code>`, Copy, Cancel code and the actual expiry. Options default to hostname, 24 hours (also 1 hour or 7 days), find coding agents (also Claude Code or Codex), add active Library skills (also start empty), session-start sync on, and approval on. Updating an unused code keeps the command; reservation freezes its options. Expiry never exceeds seven days from creation and an expired code cannot be revived. At most five live codes, including approval requests, may exist per account under concurrent creation.

The program preflights configuration and installation, reserves the code through `join`, and saves a separate random request bearer in a restricted recovery file. The dialog polls `/api/state` to show the reported name, OS, request arrival time, Approve and Deny; those details do not prove identity. No permanent token exists until approval. A single completion poll consumes the request, creates the machine and returns its token only to the request bearer. The code cannot poll or collect that token. With approval off, the same flow completes without a click. Setup completion is separate from connection: agents and installed skills are reported only after the program confirms them.

`aistack join <server> <code>` installs the program through `uv tool install aistack-mcp`, preserves unrelated agent configuration and hooks, writes the remote token with restricted permissions, installs the bundled skill and optional hook using the program's full path, applies the selected initial placements and syncs. It never prints a permanent credential. Start empty leaves placements undecided and still backs up private local skills. Existing local conflicts remain questions. The program is installed before the code is reserved. Reruns resume from saved state; on an authenticated existing connection they set up the agents and hook the join recorded in `.aistack/setup.json` again, which holds no credential. A lost token response requires removing the incomplete computer and issuing another code; the server stores no recoverable plaintext token. Restart the coding agent once.

Legacy `add_machine(name, os)` retains its token-bearing command and TOML fields until a separately approved minor release. New clients explicitly opt into additive computer-code results; no permanent token accompanies a code. Check advertised tool schemas before new inputs and explain when the server needs upgrading. Existing account and team-invite onboarding stays available.

**Back up** (push): "push my wizard skill to aistack", or a name sync listed under `backup`: the agent calls `push_skill` with the skill's name and gets back a signed upload URL, then sends a gzipped tar of the skill directory to it with `tar` and `curl`, as the tool's description spells out. The server validates the archive, stores the revision in the caller's own skills, and answers the upload with the result the agent reports; a rejection comes back as the same kind of sentence a tool error would carry. Uploading content identical to the latest revision creates nothing and says so, so repeating "push all my skills" does not mint a revision per skill per run. Pushing a name the user already has adds a revision. Push records an optional `origin` URL (GitHub repo, marketplace page) the first time, when the agent knows it. Push enables the skill for the calling machine and shares nothing.

**Share**: "share wizard with backend": `share_skill` copies the latest revision of the caller's own skill into a team, or a group in it. No bytes move through the client. The team's copy has its own history, and every revision in it names who shared it (`pushed_by` means exactly that, AIStack never claims authorship). Any member may share over a team's skill at team level, and over one in a group if they may share into that group (ADR-0029). When the team already had that name and the sharer's copy was never taken from it, the result says so (`possibly_unrelated`), because it may be an unrelated skill that shares the name. When the sharer's copy was taken from an older revision than the team's latest, the result names the revision it went over (`overwrote_revision`), because that revision's changes are no longer in the team's latest.

**Take**: "install wizard from backend": `get_skill` with a team copies that team's latest revision into the caller's own skills, remembers the source and its revision, and then installs as below. The copy stays theirs if they leave the team. When the caller already has a different skill of that name that was never taken from this team, the call is refused with a sentence naming their revision and the computers it is on, until it is repeated with `replace` true: taking replaces it everywhere, and it may be an unrelated skill that only shares the name. A copy follows one team for updates; sharing it into another team leaves it following the first (`updates_from` in the share result).

**Gathering rules**: `tar` archives a symlink as a symlink, not as its target, so a link to `~/.ssh/id_rsa` inside a skill folder arrives as a link entry and the server rejects the push by naming it. The same goes for sockets, devices, FIFOs, and hard links. The push prompt tells the agent to set `COPYFILE_DISABLE=1` on macOS so `tar` does not synthesize `._*` AppleDouble entries, and to leave `.git` out. The server enforces all of it regardless (§4 Push validation); the prompt only makes the first attempt succeed.

**Bulk import** ("move to AIStack"): not a tool. The first sync lists every local skill under `backup` and the agent pushes each one.

**Install**: "install wizard": `get_skill` marks one of the caller's own skills enabled for this machine and returns a signed download URL. The agent downloads and extracts the archive under `<skills>/.aistack-staging/`, then renames it into the global skills directory, so a failed download never leaves half a skill where Claude Code is watching. Install = enable + materialize; "remove wizard" = `disable_skill` + the agent deletes the local folder. After install the skill is a plain native skill, usable immediately in the same session. On a server, a project's skills folders are synced the same way once the person adds the project: the `sync-aistack` skill sorts their folders with git, and installs only where it has made git ignore the folder (ADR-0026).

### The sync contract

The installed program runs `aistack sync` manually or `aistack sync --hook` at session start (ADR-0035). It reads remote connections from agent configuration, respecting `CODEX_HOME`. Equal connections are used once for every harness in use; conflicting addresses or credentials stop with repair instructions. Local-mode entries keep their meaning. The connection remains direct remote MCP, with no proxy or separate sync API. Nothing runs as a daemon; the server never polls upstream. Sync is not discovery: it reconciles what this machine manages, `list_skills` finds what it doesn't. A manual `aistack sync` also syncs every other managed project whose folder `~/.aistack/projects.json` recorded, with the same checks, after asking without `project` whether the server still manages it, so a project the person stopped managing is not registered again; its rule questions are keyed `<project key>:<key>`, and a folder that is gone is reported once and forgotten. The hook syncs only the agents' folders and the project the session is in. `aistack link` registers the `aistack://` link and `aistack link remove` undoes exactly what registration wrote.

**Per harness.** One sync call covers one harness's folder. The server reads only that harness's decisions for the machine, so every table below applies per folder, unchanged (ADR-0018): a skill enabled in Claude Code and never decided in the agents folder is undecided there. A skill backed up from a folder is placed in that folder only. Sync records that the harness synced, and when, in `machine_harness`; it may also bind the first optional fingerprint (ADR-0035), but never changes desired state. The report's `first_sync` says whether this call created that row, which is when the agent asks once whether both folders should hold the same skills (ADR-0021).

One rule: **sync acts silently only on skills enabled for this machine, and only when the local copy is absent or matches a revision the server knows. Everything else is reported, and the user decides.**

Enabled for this machine:

| local state | sync does |
|---|---|
| absent | install, silently |
| matches an older revision | update, silently, reporting what changed and who pushed it |
| matches the latest revision | nothing |
| matches no revision (locally modified) | ask: restore / push / skip (skip re-reports next sync); `edited_from` below `latest_revision` says another computer pushed since |

Not enabled for this machine, but present on disk:

| server state | local hash | sync does |
|---|---|---|
| explicitly disabled here (`enabled = false` row) | matches latest | report: re-enable (no rewrite) or remove |
| explicitly disabled here | matches an older revision | report: re-enable **and update** (states that files will be replaced) or remove |
| explicitly disabled here | matches no revision | report: push / re-enable-and-replace (**states this discards local edits**) / remove / skip |
| in the Library, no decision here (no row) | matches latest | report: adopt (no rewrite) |
| in the Library, no decision here | matches an older revision | report: adopt **and update** (states that files will be replaced) |
| in the Library, no decision here | matches no revision | report: push / adopt-and-replace (**states this discards local edits**) / skip |
| not among the user's own skills | any | list under `backup`; the program backs it up to the Library **without asking**. That space is private, so nothing is shared and nobody else sees the user as the pusher of something they only downloaded (this replaces "never auto-push", which guarded a vault everyone shared) |

A prompt that leads to overwriting local content must say so. "Adopt?" on its own is not informed consent when the local copy matches no revision.

**Hash precedence** (identical content can legitimately be pushed as two revisions, so a hash can match both): if the local hash equals the latest revision's, the copy is current. Otherwise, if it equals any revision's, it is stale. Otherwise it is unknown.

**No-op states**, stated so the contract covers the full product rather than relying on inference: absent + disabled, absent + no row, and absent + not in the Library all mean nothing to do and are never reported.

Every answer maps to an existing tool: restore / re-enable / adopt → `get_skill` (on the wire, `restore` for a skill already enabled here and `enable` for the other two); push → `push_skill`; remove → the flag is already false, the agent just deletes the folder; skip → nothing. No hidden verbs.

**Wire contract**: the program (or the retained manual fallback) sends, for every skill folder in the harness's skills folder, each file's relative path and the sha256 of its bytes. The server derives the canonical hash from those (ADR-0011) and returns *action metadata only*: skills to install, skills to update, questions, the names to back up, and team updates on offer. For each entry that is the skill name, the target revision, and who pushed it; a question also carries the state that was found, the options the user may choose, and for each option whether it replaces local files and whether it discards local edits (ADR-0012). It never returns file content. The program calls `get_skill` per install or update, and `push_skill` per name to back up, moving bytes through scoped transfer URLs without attaching the permanent bearer. This keeps a sync of fifty skills small, and makes `get_skill` the single materialization path rather than a second one hiding inside sync.

Two folders are never reported: `synced`, which Claude Code reserves for skills it downloads from claude.ai, and anything starting with a dot. The `sync-aistack` skill leaves them out of what it sends, along with `.DS_Store` files. The `sync-aistack` folder itself is never listed under `backup`: setup wrote it from the server, so it needs no backing up. Instead the server compares it with the copy it ships, and when the machine's is missing or different the report carries `sync_skill_url`, which the program refreshes from bundled package data without asking, preserving a person's own Library copy. In the agents folder that happens only where the skill already is, because setup put it there for a connected Codex, or on a computer whose Claude Code never synced: there the agent syncing that folder is the one connected to AIStack, as on a Codex-only computer added with `add_machine`. Anywhere else it would tell an unconnected agent to sync (ADR-0021). That is how the skill follows a server upgrade, and how a machine connected with `add_machine`, which never ran setup, gets it at all; the download uses `curl --create-dirs`, because such a machine has no `sync-aistack` folder yet. If the user pushes their own copy of the skill, it is reconciled like any other and the field stays null.

Three invariants:

1. **Sync never deletes a local file.** Only `disable_skill` leads to local deletion, and only because the user asked.
2. **Sync never flips `enabled` silently.** Adoption and re-enable are always questions, because both mean later revisions will overwrite that folder: something the user must agree to once.
3. **Sync never applies a teammate's change.** A newer revision in a team is listed under `team_updates` and reaches a machine only when the user accepts it, each time (ADR-0015).

Known, accepted quirks: a renamed local folder shows up as one missing skill plus one new one to back up (self-explaining, not destructive); a computer with the session-start hook off receives updates only when sync runs manually.

### Executing server sync (ADR-0035)

Reuse local observation, packing, validation and staged installation. For global folders and folders in the current managed project, observe and call `sync`, install/update through `get_skill`, and upload `backup` through `push_skill`. Preserve project discovery and git exclusions: never start managing a project, change ignore rules or replace repository skills without the existing explicit action.

Serialize cooperating commands (a second sync waits up to 20 seconds for the first, so both fit the hook's timeout), use independent staging, recheck the observation before replacement, and preserve a displaced copy on installation failure. Local changes during download become questions. A failed download after `get_skill` records its revision remains retryable without making unknown edits safe to replace. Keep network and filesystem work outside database transactions. The manual fallback uses independent staging too; a failed program run is no permission to repeat writes through the fallback.

Manual output reports installs, updates, revisions and who pushed them. Hook output is empty after successful automatic work when nothing needs attention; questions include facts, permitted choices, tool calls and all replacement warnings. A team update that several folders list is one question. Bound network waits and polling, with a hook timeout sufficient for sync. Offline failures produce a short notice and leave installed skills usable. The bundled skill runs the program first and retains shell steps for computers without it and cloud sessions.

An additive `sync` result identifies the authenticated machine. `identify=true` returns identity without consuming first-sync choices or reconciling files. The program discovers that id without disk actions, then submits an optional fingerprint computed as sha256 of a single documented byte encoding of machine id and OS hardware id. Never send, store or log the raw hardware id. Atomically bind the first supplied fingerprint in nullable `machine.fingerprint_hash`; refuse later mismatches before disk actions with instructions to add the computer separately. Pairing reserves the machine id so the program can supply its fingerprint on creation. Missing hardware ids omit the fingerprint and produce a diagnostic in manual output. Older clients may omit it; modified clients may lie; full clones may retain the OS id; the first binding wins. This detects accidental copies, not hardware identity or token theft. Never reset or automatically replace a binding.

Measure a fifty-skill first sync and a no-change sync before adding bundles. Record environment, latency, archive sizes, request counts, elapsed time and hook startup. No-change transfers no archives, creates no revisions and changes no placements; last-synced timestamps may advance. The target is session-start sync in seconds; propose bundles only if measured results justify them.

### Syncing rules (ADR-0036)

`aistack sync` sends `rules` with its first folder's call, to a server whose `sync` takes it: a list of `{agent, place, name, digest}`, `agent` one AIStack writes rules for (`claude_code`, `codex`), `place` `every_project` (the agent's whole file, `~/.claude/CLAUDE.md` or `$CODEX_HOME/AGENTS.md`, `name` null, `digest` null when absent) or `project` (one of the person's rules for the project `here` names, by rule name). An agent counts as on the computer when its file for every project is listed. The server never takes a path: each file's place follows from `services/agent_files.py`. Project files count only where the computer manages the project. The result gains `rules`, one entry per file (`agent`, `place`, `name`, `action` of `install`, `update`, `backup`, `ask` or `nothing`, `desired`, `local`, `revision`, `local_revision`, `edited_from`, `pushed_by`, `options`, `removed_from_library`, and a `download_url` or `upload_url` where the text may move), and `repository_files` (`path`, `agent`, `turned_off`) for the project's agent files. A caller that sends no `rules` gets neither field. Text moves only through `/transfer/rule-download/<ticket>` and `/transfer/rule-upload/<ticket>`, whose tickets have audiences of their own; a download records the revision as what that file holds (`machine_rule`), as `get_skill` does, and an upload stores the text as the rule's next revision, rechecking that the computer still manages the project.

Decisions come from `reconciliation.reconcile_rule`. A rule follows the person, so nothing is undecided: a file is wanted while its rule is in the Library and used for that agent. Two rows differ from a skill's: a file edited only here (it matches no revision, and this computer last had the latest) is backed up without asking, and a rule no longer wanted asks only whether to remove the file. A file edited here and on the page is a question. A file with no rule is backed up: the hand-written `~/.claude/CLAUDE.md` as `claude-md`, Codex's as `codex-agents-md` (or, with the same text as a rule for every project already there, as that rule used for Codex too), a project file under its own name. Text that looks like it holds a credential is not backed up; the person saves it on the page.

In a project the program writes only `.claude/rules/aistack-<name>.md` and Codex's `AGENTS.override.md`, adding each to `.git/info/exclude` first, and never a file git tracks or one reached through a link. The override is a first line saying AIStack made it, the repository's `AGENTS.md`, then each rule under `<!-- aistack:rule <name> -->`, sorted by name; sync reads those sections back as the observation and rewrites the file whenever any part changed. An `AGENTS.override.md` without that first line is someone else's and is left alone. A repository file turned off is listed by absolute path in `claudeMdExcludes` of the project's `.claude/settings.local.json` (excluded from git, other keys kept) and left out of the override; turned on again, its entry is taken back. Every write rechecks that the file still holds what was observed. A question prints its key, and `aistack sync --rule-choice <key>=<choice>` carries out an offered answer.

Local mode runs the same code (`mcp/local_rules.py`) against the Library it opened: its `sync` tool, `status --hook` at session start, and `aistack sync` on a computer whose agents start AIStack locally each write the files for every project and the person's rules in every project this computer added (the folder from its own `project_files_listed` event, checked to be that project's repository). The download and upload are served in-process, each in a transaction of its own, and a file kept in the Library is recorded as the `rule_created`, `rule_edited` or `rule_agents_set` events that replay it. Rule questions come back in the tool's `rule_questions`, keyed `<project>:<key>` for a project's file, and are answered by calling `sync` again with `rule_choices`; the hook writes what needs no question and reminds the agent only when a question or a failure is left.

### A project's own files (ADR-0036, ADR-0038)

`aistack project add <folder>` is the explicit action that starts managing a project on a computer. It lists the agent files `services/agent_files.py` knows and every other `.md` git tracks, by path and size and never by text, prints the list, and waits for Enter. It then syncs as `aistack sync` does, first syncing each harness's skills folder in the project with `project` (which records the project, ADR-0026) and, on the first of those calls, `project_files`: a list of `{path, size}`. The server keeps the list in `project_file`, an agent's file ticked and any other unticked; a tick the person changed stays, and a file no longer listed goes with its edits. `aistack://project-add?folder=<folder>` runs the same command.

Every call that sends `rules`, for a project the computer manages, also returns `ticked_files` (`path`, `content_hash` of the text the page holds, and an `upload_url`) and `edits` waiting for this computer (`path`, `base_hash`, `content_hash`, `note`, and a `url`), and `shared_edits` it shared that the page still shows as shared (the same fields). A caller that sends no `rules` gets none of them. The program checks each path against what git tracks there and refuses one that leaves the top level or is a link, then:

- An edit with no `note` is written into the working copy only while the file hashes to `base_hash`. Otherwise it is a question, keyed `repository:<path>`, and `aistack sync --rule-choice repository:<path>=write` writes it anyway, `=cancel` drops it. This is the one tracked file AIStack ever writes, because the person asked for it on the page.
- An edit with a `note` was committed on the page. The program builds a commit holding only that file on a temporary index (`GIT_INDEX_FILE`), from the commit the current branch tracks upstream (or `HEAD` when it tracks none), with the note as message (its first line the subject), and pushes it as a new branch `aistack/<file>-<hash>` without force. No local ref moves, and the working tree and index are untouched, so nothing is committed to the person's branch and their other work never goes with it. With `gh` installed and signed in it opens the pull request against the upstream branch; otherwise it prints the address that opens one.
- A shared edit is settled once the file has its text and differs in nothing from the commit checked out, so the person's own git has it (merged and pulled, or committed): the page then shows the file as before the edit.
- A ticked file whose hash differs from `content_hash` is uploaded, at most 64 KiB of UTF-8. Text that looks like it holds a credential is not kept.

On the page, "A folder on this computer…" under Projects' + opens Add a project. On a server it shows `aistack project add <folder>` to copy and, on the computer the page is on, the `aistack://project-add` link, then the checklist once that command's list arrives in `/api/state`; the ticks are saved with `POST /api/projects/files/tick`. The localhost dashboard looks inside at once through `POST /api/projects/look-inside` (`folder`), registered in `LOCAL_ROUTES` only, which answers the project's `key`, `name`, `top`, `files` (each `path`, `size`, `agents`) and the `skills` its repository holds; files inside a skills folder belong to the skill and are not listed. The side panel of a repository's file offers Edit (a pending edit for a computer that has the project, this one by default), Commit… once that computer wrote it, and "Turn this file off for me", unavailable with its reason for an agent AIStack cannot turn a file off for. Start an agent offers the repository's own skills from `repository_skills`.

The `url` serves the edit's text on `GET` and takes what became of it on `POST` (`{"outcome": "written" | "shared" | "cancelled" | "settled", "pull_request_url"}`); the upload goes to `/transfer/project-file-upload/<ticket>`. Both tickets have audiences of their own, and both recheck that the computer is still registered and manages the project. git and gh run without a shell, and their output is never shown: a push's error can carry a remote's credentials.

### Versions

Every push creates a `skill_version` with a server-side auto-incrementing `revision` (always present, orders history) and the author's optional frontmatter `version` string (preserved, displayed when present, never invented). Sync compares content hashes, not version numbers.

**Canonical content hash.** Only the server computes this (ADR-0011): at push from the bytes it received, at sync from the per-file digests the agent sent. Both feed the same function, so the procedure is exact:

1. **Path form.** Relative and `/`-separated; convert `\` to `/` and strip a leading `./` before validation. NFC-normalize once, before validation, storage, sorting, and hashing. Push rejects paths that fail §4 Push validation; sync hashes whatever it was sent, because an unrecognized path can only make the result "unknown", which is the safe answer.
2. **Order.** Sort by the unsigned UTF-8 *bytes* of the normalized path. Never a locale-aware sort.
3. **Content digest.** sha256 of the file's exact bytes, never text mode, never CRLF translation, never BOM stripping, never Unicode normalization of content.
4. **Framing.** For each file in order, feed the outer sha256: the path's byte length as an unsigned 8-byte big-endian integer, then the path's UTF-8 bytes, then the raw 32-byte content digest.
5. **`content_hash`** is the lowercase hex of the outer digest.

Length-prefixed framing rather than JSON (ADR-0009): what must match is the bytes, not the data structure, and two conforming JSON serializers can legitimately differ in escaping and representation. Length prefixing needs no library, no separator, and no escaping: a field cannot be misread as part of the next one.

**The executable bit is deliberately NOT hashed.** It is stored per file and applied on materialization, but excluded from the hash: Windows filesystems cannot carry it, so a Windows machine would recompute a different bit than the vault holds and see a permanent phantom conflict on every sync of every skill with a script. The cost is that a chmod-only revision is invisible to sync and needs a content change to propagate. Measured against the real corpus that costs nothing: zero of 75 files across 26 installed skills are executable, including `wizard`'s own `template.sh`, because skills invoke scripts as `bash template.sh`. Git avoids the same problem with an index; an index is not worth building for a bit that is currently always false.

### Push validation

Push is the trust boundary: everything below is enforced by the server on the uploaded archive, before any row is written, and every rejection says what to fix and what was received. Limits are sized against the reference corpus (25 skills, 75 files, largest skill 19 KB) with two orders of magnitude of headroom.

**Archive.** A gzipped tar, at most 1 MiB compressed, counted while the request body streams so an oversized upload is cut off rather than buffered. Members are read in memory and never extracted to disk. A directory entry is skipped. A regular file is taken. Any other member type (symlink, hard link, device, FIFO) rejects the whole push, naming the member. `._*` AppleDouble entries and `.DS_Store` are skipped: the first is an artifact of macOS `tar` that never existed on disk, the second is never part of a skill. Before `tarfile` parses anything, the header blocks are walked directly: a damaged header rejects the archive (it would otherwise be silently truncated), a pax or long-name header above a few kilobytes is rejected (it is parsed in full, in memory), and so is a pax record that redefines a member's size or marks it sparse.

**Size.** At most 100 files, 256 KiB per file, 1 MiB in total uncompressed. The per-file and total limits are applied as each member is read, so a decompression bomb stops at the limit and not at the end.

**Name.** `^[a-z0-9]+(-[a-z0-9]+)*$`, at most 64 characters. This is the Agent Skills specification's rule, so a valid name here is a valid directory name in every harness.

**Paths**, after the normalization in §4 Versions:

- relative, at most 255 characters and 8 segments deep, with no single name over 255 bytes
- no empty, `.`, or `..` segment, and no leading `/`
- no control characters, and none of `< > : " | ? *` (Windows cannot create them)
- no segment ending in a dot or a space, and no segment whose stem is a Windows device name (`CON`, `PRN`, `AUX`, `NUL`, `CONIN$`, `CONOUT$`, `COM1`–`COM9`, `LPT1`–`LPT9`, in any case, with superscript digits and spaces before the dot counted)
- no `.git`, `.hg`, or `.svn` folder
- no two paths equal after uppercasing and case folding, and no path that is also a directory prefix of another (macOS and Windows would silently merge them)

**Content.** Valid UTF-8 with no NUL character. Bytes are stored and returned exactly; nothing is normalized, so CRLF and a BOM survive the round trip.

**`SKILL.md`.** Must exist at the archive root with exactly that name. Its frontmatter must be a YAML mapping between `---` lines (lines end at a line feed and nothing else), parsed with every scalar kept as a string so a `version: 1.10` is stored as `1.10` and not as the number `1.1`. A key may appear once, every string must be valid Unicode, and nesting and size are bounded. `name` must equal the pushed name. `description` is required, stored as one printable line, and at most 1024 characters. `version` is optional and at most 32. Unknown fields are kept.

**Reserved names.** A skill may not be named `synced` (Claude Code's folder for claude.ai skills, which an install would replace) or after a Windows device (`con`, `nul`, `com1`, …): the name is a folder on every machine.

**Environment files.** `.env` and `.env.*` are refused anywhere in a skill, because that is where secrets are kept and a skill can be shared. The templates `.env.example`, `.env.sample`, and `.env.template` are kept.

**`origin`.** Optional, at most 255 characters, no control characters, and an `http://` or `https://` URL: it will be rendered as a link.

**Usernames.** A lowercase handle: letters and digits joined by single `.`, `-`, or `_`. A username is the `pushed_by` teammates read before a skill changes on their machine, so no two may differ only in case or alphabet. A username is also the name of the user's personal team, so usernames and team names share one namespace. Machine names are seen only by their owner and may be any printable text. A user may also give a full name, up to 100 printable characters, in the dashboard's Settings on a server: teammates read it beside the username in a team's member list. It is not an identity, so two people may share one; `pushed_by` stays the username.

### Personal space, teams, and groups (ADR-0015)

Three places hold skills, and they nest in that order of privacy.

| Place | Who sees it | How a skill gets there | What installs from it |
|---|---|---|---|
| **Library** (a personal team per user) | Only that user | Backed up from their computers by sync, without asking | Their machines, and nothing else |
| **A team** (one a user created) | Its members | A member shares one of their own skills | Nothing directly: a member takes a copy into the Library |
| **A group** in a team (`backend`, `backend/aistack`) | Open: whoever sees the group above. Private: the people added to it | A member of it, or of a group above it, shares into it | As a team |

**The four verbs.** *Back up* (`push_skill`): a local skill goes into the Library. *Share* (`share_skill`, or a tick on the dashboard): the team gets a copy of the latest revision. *Take* (`get_skill` with a team): the team's latest revision is copied into the Library and installed. *Remove*: from one computer (`disable_skill`), from the Library on every computer (dashboard), or from a team (its admin).

**Updates from a team are offers.** A personal skill remembers its team source and that source's revision. When the team's copy is newer, sync lists it under `team_updates` and the user answers each time; yes is *take*. Each offer says whether the user changed their copy since taking it (`own_changes`), because taking replaces those changes on every computer, and whether a share since put a different skill of the same name in the team (`different_skill`, from `skill_version.shared_over_unrelated`). The dashboard shows the offer's changes as a diff before anything is taken. A user who unsubscribes from a group is not offered its updates.

**What leaving a team changes:** what the user can list and take. Nothing they already took is touched, because their machines never ran the team's copy.

**Roles.** Admin and member. An admin manages the invite code, members and their roles, groups and their members, and where a team's skill sits. A team keeps at least one admin while anyone is in it: the last member leaving deletes the team, and an admin can delete it, which removes the team's copies of its skills, its groups and its invites and leaves every member's Library copy (ADR-0028). An admin can mark a member "can invite" (`team_member.can_invite`, migration 0004): that member may make the team's invite link and nothing else an admin can (ADR-0019).

**Where the rule lives.** `services/visibility.py` decides who sees what; `services/team_service.py` is team administration. A team, group, or skill the caller may not see answers exactly like one that does not exist.

### The dashboard (ADR-0017)

The web application is the product; MCP connects an agent to the account. The dashboard is one page served at `/app`, signed into by the link `open_dashboard` returns, backed by JSON routes under `/api` that call the same services as the tools.

| View | What a user does there |
|---|---|
| Library | See every skill and which of their computers has it; add it to a computer or take it off one; share it with a team or group; take an offered update; remove it |
| A computer | See what its coding agent has; add skills from the Library; copy what another computer has; take one off; rename or remove the computer (server only) |
| A team | Browse its skills by group, with who pushed each; take one; unsubscribe from a group |
| Team admin | Invite code; members, roles, and sight of every group; create groups and nest them; make one private; add people; move or remove a skill |
| Teams | Create a team; join one with a code; leave one |

**Two columns are the map.** A rail on the left holds the user's spaces, the way a chat application lists servers: *Personal* on top, then each team, then one *+* that creates a team or joins one with a code. The column beside it lists what is in the chosen space, and the account bar with sign-out runs under both at the bottom. For Personal that is the Library, with a blue dot and a count when updates are waiting, then the places a person thinks in (ADR-0037): Every project (`#/every`), each project by name (`#/p/<key>`), assembled in the page from every computer's `projects`, and each computer (`#/c/<machine id>`). A project's page and Every project show one table of skills with a column per coding agent and a tick where that agent gets the skill; a computer's page lists its agents and projects with their folders. A *+* on a heading or an item opens what can be added there. The *+* beside the Computers heading makes a one-use computer code (ADR-0035); a code still in use is listed under the computers with its expiry and Cancel code. A computer's agents are the `harnesses` `/api/state` lists for it, and a skill is placed in one of them, not on the computer as a whole. For a team it is All skills, the team's groups nested a step in per level, then Members and Settings. A private group has a lock, every group shows how many skills are in it and below it, and a blue dot marks one with an update waiting for a skill the user took. Choosing a group opens the team's skills narrowed to that group and the groups under it, at `#/t/<team>/skills/<group path>`, an address that can be reloaded or sent to a teammate. The tree is built from the groups `/api/state` sends, so a private group the user is not in is absent from it, and its address opens the whole team exactly as an unknown one does.

**Placing a skill is three gestures over one route.** A tag per computer on a Library row, with a cross to take it off; Add to… on the row, a box per computer; and on a computer's page, Add skills and Copy from…, which adds what another computer has and removes nothing. Each is a series of `POST /api/skills/{name}/machines/{machine_id}` calls, one per change, and the page reloads its state once they are done.

### The dashboard's routes

The page is the only client these were written for, and they are documented so that it is not the only way to learn them. Everything is under the server's own address. A test fails when a route is added to `api/dashboard.py` and not to this table.

**Invite links.** `GET /invite/{code}` is a team's invite link (ADR-0019): a page naming the team, with the sentence to paste into Claude Code or Codex. The code is the credential, as a ticket is for a transfer route: it is never logged, the page is sent with `Referrer-Policy: no-referrer` and a CSP that loads nothing, and a wrong or replaced code gets the same 404 as any other. `invite_to_team` and the dashboard both hand out the link.

**Signing in.** `GET /app/login/{ticket}` takes the link `open_dashboard` returned, sets the session cookie `aistack_session` (`__Host-aistack_session` over https; HttpOnly, SameSite=Lax, Secure over https, eight hours), and answers `303` to `/app`, which takes the ticket out of the address bar. A link and its session belong to the computer that asked for the link, and end when that computer is removed or given a new token (ADR-0027). A browser already signed in as somebody else gets a page asking first; its button is `POST /app/login/{ticket}`, with the request header, which switches. `GET /app` is the page. Either one, without a valid ticket or session, answers `401` with a short page saying how to get a link and, on a server, the sentence that connects a computer that is not connected yet. `GET /` redirects to `/app`, because the server's address is what a person opens first.

**What every `/api` route does.**

- It reads the user from the session cookie and from nowhere else. No route takes a user id.
- It answers `401` when there is no valid session: none, signed out, or opened by a computer that has since been removed or given a new token.
- A `POST` must carry the header `X-AIStack-Request` (any value) and a JSON object as its body, at most 16 KiB. `{}` is a valid body for a route that needs nothing.
- It runs one service call in one transaction and returns what that call returned. A route with nothing to return answers `{"ok": true}`.
- A refusal is `{"error": "<a sentence saying what to fix>"}` with `400` for a value that is not valid, `404` for something that does not exist or that this user may not see (the two are never told apart), `409` for a conflict such as a name already taken, and `500` with no detail for anything unexpected.
- Responses are `Cache-Control: no-store`.

| Route | Body | Returns |
|---|---|---|
| `GET /api/state` | | Everything the page shows, below |
| `GET /api/library.tar.gz` | | The whole Library as one archive, a folder per skill at its latest revision, as `aistack export` writes it; on the localhost dashboard too |
| `POST /api/logout` | `{}` | Ends the session, wherever its cookie was copied, and clears the cookie |
| `POST /api/start-agent` | `agent` (`claude-code` or `codex`), `project` (a key this computer manages), `skills` (a list of names) | Opens a terminal on this computer running `aistack start --new-terminal` with them, which says what it will start and waits for Enter (ADR-0038). Answers `ok`, or the command's own sentence when it refused. Localhost dashboard only: the server has no such route |
| `POST /api/skills/{name}/machines/{machine_id}` | `enabled` (true or false), optional `harness` (`claude_code`, the default, or `agents`), optional `project` (a key that computer manages) | Switches one of the user's own skills on or off in one harness of one of their computers, or in that project's folder there (server only). The files move at that folder's next sync there |
| `POST /api/machines/{machine_id}/projects` | `project` (a key), optional `harness` | Starts managing one of the user's projects, already known from another computer, on this computer. Its path is unknown until it syncs there. Server only |
| `POST /api/machines/{machine_id}/projects/remove` | `project`, optional `harness` (every harness when omitted) | Stops managing that project on this computer; its placements there go with it. The files on disk, the Library and the other computers are untouched. Answers `removed`, the number of folders. Server only |
| `POST /api/skills/{name}/share` | `team`, `group` (a path, or null for team level) | `team`, `group`, `revision`, `created`, `unchanged`, `previous_pushed_by`, `possibly_unrelated`, `overwrote_revision`, `updates_from`: what `share_skill` returns |
| `POST /api/skills/{name}/bring-back` | `{}` | `name`. Puts a skill removed from the Library back, on no computer. Server only |
| `GET /api/skills/{name}/history` | | `revisions`, newest first: each `revision`, `pushed_by`, `pushed_on` (UTC), and `files`. Server only |
| `POST /api/skills/{name}/restore` | `revision` | `revision`, the new one, and `unchanged`. Stores that revision's files as the newest, pushed by the user; every computer that has the skill installs it at its next sync. Server only |
| `GET /api/teams/{team}/skills/{name}/changes` | | What taking the team's latest would change in the user's copy: `from_revision` (theirs), `to_revision`, `pushed_by`, `files` (each `path`, `change` as `added`, `removed` or `changed`, and a unified `diff`), and `truncated` when the diff was cut |
| `POST /api/skills/{name}/remove` | `{}` | Removes the skill from the Library on every computer |
| `POST /api/rules` | `name`, `text`, optional `project` (a key), optional `agents` (a list of `claude_code` and `codex`), optional `confirmed` | Keeps a new rule in the Library, for every project or for that project (ADR-0036); a rule of that name the user removed comes back with this text. Answers `name`, `saved`, `credential_lines`, `revision` and `unchanged`. When the text has lines that look like a credential and `confirmed` is not true, nothing is stored: `saved` is false and `credential_lines` names the lines (1-based). A rule for every project is its agents' whole file for every project, so each agent takes one such rule (`409` otherwise). At most 64 KiB. Local mode logs it (ADR-0039) |
| `POST /api/rules/{name}/edit` | `text`, optional `project`, optional `confirmed` | Saves the text as the rule's next revision, or answers `unchanged` when it is the latest already. Answers as creating one does. Local mode logs it (ADR-0039) |
| `GET /api/rules/{name}/text` | `?project=<key>` for a project's rule | `name`, `project`, `revision`, `text` (the latest), and `credential_lines`. Local mode serves it too, read-only, as it replays rules it cannot record yet |
| `POST /api/rules/{name}/rename` | `new_name`, optional `project` | `name`. Unique among the user's rules in the same place. Local mode logs it (ADR-0039) |
| `POST /api/rules/{name}/agents` | `agents` (a list), optional `project` | `agents`: the agents the rule is now used for, replacing the choice before. Local mode logs it (ADR-0039) |
| `POST /api/rules/{name}/remove` | optional `project` | `name`. Removes the rule from the Library; files on computers are left as they are. Local mode logs it (ADR-0039) |
| `POST /api/projects/add` | `folder`, `ticked` (paths) | Localhost dashboard only (ADR-0039): keeps the files of the project that folder is in, as look-inside lists them, ticked as the page ticked them, and logs `project_files_listed`. Answers `project` (the key) and `name`. A project kept this way is shown by its files until a computer manages its folders. `/api/state` then shows a ticked file's text as this computer's working copy has it, with an `edit` when it differs from the commit checked out |
| `POST /api/projects/files/tick` | `project` (a key), `path`, `ticked` | Shows a listed file on the page and keeps its text current, or stops (forgetting what was read of it). Local mode logs it (ADR-0039) |
| `POST /api/projects/files/turn-off` | `project`, `path`, `turned_off` | Turns a repository's agent file off for the user, or on again; each computer with the project does it in the agent's settings at its next sync. Refused for an agent AIStack cannot turn a file off for, with the reason. Local mode logs it (ADR-0039) |
| `POST /api/projects/files/edit` | `project`, `path`, `text`, `base_hash` (the `content_hash` the page showed), `machine` (the computer to write it on), optional `confirmed` | Keeps a pending edit for that computer, replacing an earlier one not yet shared. `409` when the file changed since the page read it; the computer must manage the project. Answers as saving a rule does, credential check included. On the localhost dashboard, without `machine`, it writes the text into this computer's working copy at once, only while the file there has the text the edit started from (`409` otherwise), and logs nothing |
| `POST /api/projects/files/commit` | `project`, `path`, `note` | Asks the computer that wrote the latest edit to share it as a pull request, with `note` as the commit message. `409` before an edit has been written. Answers `note`. On the localhost dashboard it shares the file as this computer's working copy has it, at once, through the same branch-and-pull-request code `aistack sync` uses, and answers `note`, `branch`, `pull_request_url` and `opened`. The page then shows the file as shared until the working copy's commit has that text |
| `POST /api/machines/{machine_id}/remove` | `{}` | `removed`: the computer's name. Its token, sessions and transfer URLs end at once. The user's last computer is refused with `409`. Server only (ADR-0027) |
| `POST /api/computer-codes` | Options (defaults above) | One-use code, command, id and expiry, shown once; server only |
| `POST /api/computer-codes/{id}` | Options | Updates an unused code, without reviving expiry; server only |
| `POST /api/computer-codes/{id}/cancel` | `{}` | Cancels the code and any uncompleted request; server only |
| `POST /api/computer-codes/{id}/approve` | `{}` | Owner-scoped approval of the frozen waiting request; server only |
| `POST /api/computer-codes/{id}/deny` | `{}` | Owner-scoped denial; server only |
| `POST /api/machines/{machine_id}/rename` | `name` | `name`, unique among the user's computers. Server only |
| `POST /api/account` | `full_name` (blank clears it) | `full_name`. Server only |
| `POST /api/teams` | `name` | `name`. The caller is the new team's admin |
| `POST /api/teams/join` | `code` (a team's invite code) | `team` |
| `POST /api/teams/{team}/leave` | `{}` | The last member leaving deletes the team (ADR-0028) |
| `POST /api/teams/{team}/delete` | `{}` | Deletes the team, its copies of its skills, its groups and its invites. Members' Library copies stay. Admin only (ADR-0028) |
| `POST /api/teams/{team}/invite` | `{}` | `code`, shown this once: a new invite, one use, seven days, and its `id`, which the page shows a short tag of. Admins and members who can invite (ADR-0022) |
| `POST /api/teams/{team}/invites/{invite_id}/cancel` | `{}` | `ok`. Its maker, or an admin |
| `POST /api/teams/{team}/take` | `name`, `replace` (optional, true when the person agreed to replace their own unrelated skill of that name) | Copies the team's latest revision of that skill into the Library |
| `POST /api/teams/{team}/members/{username}` | Any of `role` (`ADMIN` or `MEMBER`), `sees_all_groups` (true or false), `can_invite` (true or false) | Admin only |
| `POST /api/teams/{team}/members/{username}/remove` | `{}` | Admin only |
| `POST /api/teams/{team}/groups` | `name`, optional `parent` (a path), optional `private` | `path`. Admin only |
| `POST /api/teams/{team}/group` | `path`, and `private` (admin only) and/or `subscribed` (anyone who sees the group's skills) | |
| `POST /api/teams/{team}/group/members` | `path`, `username`, `member` (true or false) | Admin only |
| `POST /api/teams/{team}/group/rename` | `path`, `name` | Admin only. The groups under it follow; answers the new `path` |
| `POST /api/teams/{team}/group/delete` | `path` | Admin only, and only a group with no skills and no groups inside it |
| `POST /api/teams/{team}/skills/{name}/move` | `group` (a path, or null for team level) | Admin only |
| `POST /api/teams/{team}/skills/{name}/remove` | `{}` | Removes the team's copy. Admin only |

A group's path contains slashes, so it always travels in the body and never in the address.

**On the localhost dashboard** (`aistack dashboard`, or local mode's `open_dashboard`), only the sign-in routes, `GET /app`, `GET /api/state`, `POST /api/logout`, placing a skill and removing one from the Library, the rule routes, and a project's file routes are served. Sharing, the computer and account routes, and every team route are server only, because a team needs a server everyone reaches. There, each `POST` result also carries `shared`: false when a GitHub Library could not be reached, so the change waits on this computer.

**`GET /api/state`.** One object, holding only what this user may see: `services/visibility.py` decided that before it was built, and the page filters nothing.

```json
{
  "user": {"username": "dimitris", "full_name": "Dimitris Christopoulos"},
  "machines": [
    {"id": "af6c2628-…", "name": "macbook", "os": "MACOS", "harnesses": ["claude_code"],
     "added_on": "2026-10-13T09:12:01.402113+00:00", "added_by": null, "added_by_removed": false,
     "last_synced": {"claude_code": "2026-10-14T00:40:12.513920+00:00"},
     "projects": [{"key": "github.com/demo-team/demo-api", "name": "demo-api",
                   "folders": [{"harness": "claude_code", "path": "/Users/dimitris/code/demo-api",
                                "last_synced_on": "2026-10-14T00:41:02.104771+00:00"}]}]}
  ],
  "skills": [
    {
      "name": "code-review",
      "description": "Reviews a diff against the team's standards.",
      "revision": 2,
      "pushed_by": "dimitris",
      "updated_on": "2026-10-14T00:43:56.158183+00:00",
      "files": 2,
      "placements": [{"machine": "af6c2628-…", "harness": "claude_code", "revision": 1,
                      "project": null}],
      "source": {
        "team": "acme", "group": null,
        "revision": 2, "latest_revision": 3, "latest_pushed_by": "maria",
        "update_available": true, "own_changes": false, "different_skill": false
      }
    }
  ],
  "removed": ["old-notes"],
  "rules": [
    {"name": "house-style", "project": null, "agents": ["claude_code", "codex"],
     "revision": 3, "pushed_by": "dimitris", "updated_on": "2026-10-21T09:02:11.507114+00:00"}
  ],
  "teams": [
    {
      "name": "acme", "kind": "SHARED", "role": "ADMIN", "sees_all_groups": false,
      "can_invite": false,
      "members": [
        {"username": "maria", "full_name": null, "role": "MEMBER", "sees_all_groups": false,
         "can_invite": true, "groups": ["backend"]}
      ],
      "groups": [
        {"path": "backend/aistack", "private": false, "member": true, "subscribed": true,
         "sees_skills": true}
      ],
      "skills": [
        {
          "name": "code-review", "description": "…", "team": "acme", "group": null,
          "revision": 3, "pushed_by": "maria",
          "updated_on": "2026-10-14T00:43:56.161865+00:00",
          "in_library": true
        }
      ],
      "invites": [
        {"id": "5d1e0c3a-…", "created_by": "dimitris",
         "created_on": "2026-10-14T00:30:02.114091+00:00",
         "expires_on": "2026-10-21T00:30:02.114091+00:00",
         "status": "PENDING", "used_by": null}
      ]
    }
  ],
  "server": true,
  "library": {"kind": "server"},
  "release": "0.1.0",
  "this_computer": "af6c2628-…"
}
```

| Field | Meaning |
|---|---|
| `release` | The AIStack release serving the page, as the startup log names it (Settings shows it) |
| `this_computer` | The `id` of the computer whose link opened this session, which the page marks "This one" |
| `server` | False on the localhost dashboard in local mode, where the page hides what only a server can do: creating, joining, and sharing with a team |
| `library` | Where the Library lives, by `kind`: `{"kind": "server"}`, `{"kind": "this_computer"}`, `{"kind": "postgresql", "provider": "Neon", "host": "…"}`, or `{"kind": "github", "repository": "owner/name", "problem": null, "unpublished": 0}`. Never an address or a password |
| `library.provider`, `host` | For a PostgreSQL Library: the provider recognised from the host (Neon, Supabase, or PostgreSQL), and the host |
| `library.repository`, `problem`, `unpublished` | For a GitHub Library: the repository as owner/name, why it could not be reached the last time it was tried (null when it answered), and how many changes made here have not reached it yet |
| `user` | The signed-in user: `username`, and `full_name` or null |
| `computer_codes` | Pending codes and waiting requests with options, reported details, arrival, expiry and completion status; never plaintext credentials. The dialog polls while open |
| `machines` | The user's computers, oldest first. `id` is the machine id the routes take, `name` its name, and `os` is `MACOS`, `WINDOWS`, or `LINUX` |
| `machines[].added_on`, `added_by` | When the computer was registered, and the name of the computer whose `add_machine` registered it: null for a first computer. `added_by_removed` is true when that computer has since been removed (ADR-0027) |
| `machines[].last_synced` | Each of its harnesses, with when it last synced (UTC), or null for one that never has |
| `machines[].harnesses` | The harnesses on that computer, in the server's order: those that have synced there, those holding a decision about a skill, and those with a project folder. `[]` for a computer with none, which has never synced |
| `machines[].projects` | The projects this computer manages (ADR-0026), by name: each with its `key` and `name`, and its `folders`, one per harness, with the top level last seen there (`path`, null until that folder syncs, and shown only), `last_synced_on`, and `repository_skills`: the names of the skills folders the repository itself holds there, as that folder's last sync listed them, for Start an agent |
| `project_files` | Every file listed in the user's projects (ADR-0036), by project and path: `project` (a key), `path`, `agent` (the agent it is shown under, or null for other Markdown), `agents` (every agent that reads it), `ticked`, `turned_off`, `turn_off_unavailable` (why it cannot be turned off for the user, or null), `size`, and for a ticked file the `text` a computer last sent, its `content_hash`, and `updated_on` (UTC). `edit` is the file's latest edit that is not cancelled, or null: `machine` (the computer it goes to), `text`, `content_hash`, `saved_on`, `written_on`, `note`, `shared_on`, `pull_request_url` and `branch` (the branch it was shared on, once shared). A shared edit is shown as shared until settled. On the localhost dashboard an edit is the working copy's difference from the commit checked out, and one this computer shared with that text, as it recorded beside its copy of the Library, is shown shared |
| `skills` | The Library, by name, without the ones removed from it. Each has its `name` and `description` |
| `removed` | The names of the skills removed from the Library, which Bring back can return |
| `rules` | The user's rules (ADR-0036), not the removed ones: those for every project first, then each project's, by name. Each has its `name`, `project` (a key, or null for every project), `agents` (`claude_code`, `codex`), and its latest revision: `revision`, `pushed_by`, `updated_on` (UTC). The text is read with `GET /api/rules/{name}/text` |
| `skills[].revision`, `pushed_by`, `updated_on`, `files` | The latest revision of the user's own copy: its number, who pushed it, when (UTC), and how many files it has |
| `skills[].placements` | Where the skill is switched on: each a computer's id (`machine`) and a `harness`, oldest computer first. On is a decision the server holds, not proof the files are there yet. `revision` is the one last installed or pushed there, null until it has synced. `project` is the key of the project folder it is in, or null for the computer's own folder |
| `skills[].source` | The team skill this copy was taken from or shared to, or null. Null also when the user can no longer see that skill: the copy is then simply theirs |
| `source.team`, `group` | The team that skill is in, and its group's path, or null at team level |
| `source.revision` | The team's revision this copy came from. `latest_revision` and `latest_pushed_by` describe the team's newest, and `update_available` is true when it is newer |
| `source.own_changes` | True when the user changed their copy since taking it, so taking the team's latest would replace those changes on every computer |
| `source.different_skill` | True when a share since the copy was taken put a different skill of the same name in the team: the offer is not an edit of what the user took |
| `teams` | The teams the user is in, by `name`. The Library is not among them. `kind` is `SHARED`: every team is one somebody created (ADR-0019) |
| `teams[].role`, `sees_all_groups`, `can_invite` | The user's own role in that team, `ADMIN` or `MEMBER`, whether they were given sight of every group, and whether an admin let them make invite links |
| `teams[].members` | Everyone in the team: `username`, `full_name`, `role`, `sees_all_groups`, `can_invite`, and `groups`. A member's private groups are listed only for an admin and for people in those groups |
| `teams[].groups` | The groups the user may see, by `path`; an admin is shown all of them. `private` is whether it is private, `member` whether the user is in it, `subscribed` whether they are offered its updates, `sees_skills` whether its skills are sent to them and they may subscribe to it: false only for an admin outside a private group, or under one, who is shown it to manage it |
| `teams[].skills` | The team's skills the user may see, each with its `name`, `description`, `team`, and latest revision (`revision`, `pushed_by`, `updated_on`). `group` is a path, or null at team level. `in_library` is true when one of the user's own skills was taken from it or shared to it |
| `teams[].invites` | The team's invites made in the last 30 days, newest first: every one for an admin, their own for a member who can invite, none for anyone else. Each has its `id` (what the cancel route takes), `created_by` (a username), `created_on`, `expires_on`, `status` (`PENDING`, `ACCEPTED`, `CANCELLED`, or `EXPIRED`), and `used_by` (the username that accepted it, or null). Never the code |

### Schema

Portability: runs identically on SQLite and Postgres. Enums are `VARCHAR + CHECK` (SQLAlchemy `Enum(native_enum=False)`), JSON is SQLAlchemy `JSON` (JSONB variant on PG), timestamps are `DateTime(timezone=True)` (timestamptz on PG, ISO text on SQLite).

```text
USER
  user_id       UUID PK
  username      VARCHAR(64)  NOT NULL UNIQUE
  full_name     VARCHAR(100)                          -- optional, what teammates read beside it
  is_admin      BOOLEAN      NOT NULL DEFAULT FALSE   -- first user to join. Nothing reads it
                                                      -- today, so it grants no power. Enforced by a unique
                                                      -- partial index on is_admin WHERE is_admin
                                                      -- (ADR-0008). The guarded UPDATE (... AND NOT
                                                      -- EXISTS (SELECT 1 FROM user WHERE is_admin))
                                                      -- is the fast path only: on Postgres READ
                                                      -- COMMITTED it lets two concurrent joins both
                                                      -- win. The update runs in a savepoint.
  created_on    TIMESTAMPTZ  NOT NULL

MACHINE
  machine_id    UUID PK
  user_id       FK → USER    NOT NULL
  name          VARCHAR(64)  NOT NULL
  os            ENUM(MACOS, WINDOWS, LINUX) NOT NULL   -- varchar+check, not native enum
  token_hash    VARCHAR(64)  NOT NULL UNIQUE           -- sha256 of bearer token; the auth lookup
  fingerprint_hash VARCHAR(64) NULL                  -- optional copied-connection check (ADR-0035)
  created_on    TIMESTAMPTZ  NOT NULL
  added_by_machine_id UUID   NULL                      -- the computer whose add_machine registered
                                                       -- it; null for a first computer. No FK, so
                                                       -- it outlives that computer (ADR-0027)
  UNIQUE (user_id, name)

COMPUTER_CODE                                  -- ADR-0035: new compatible table
  code_id            UUID PK
  user_id       FK → USER NOT NULL
  issuing_machine_id UUID NULL                  -- null for operator recovery
  issuing_token_hash VARCHAR(64) NULL            -- bind to current issuing token
  code_hash     VARCHAR(64) NOT NULL UNIQUE
  created_on, expires_on TIMESTAMPTZ NOT NULL
  options       JSON NOT NULL                    -- frozen on reservation
  request_hash  VARCHAR(64) NULL UNIQUE           -- separate 256-bit request bearer
  machine_id    UUID NULL                         -- reserved identity, no MACHINE yet
  request       JSON NULL                        -- reported name/OS, then setup confirmation
  requested_on  TIMESTAMPTZ NULL                  -- arrival, not identity proof
  approved_on, denied_on, cancelled_on, completed_on TIMESTAMPTZ NULL
                                                -- no placeholder MACHINE before completion

TEAM                                           -- ADR-0015
  team_id       UUID PK
  name          VARCHAR(64)  NOT NULL UNIQUE   -- a personal team carries its user's name
  kind          ENUM(PERSONAL, SHARED) NOT NULL  -- code asks the kind, never the name
  created_by    UUID FK → USER NULL            -- null only for a retired server team (0005)
  created_on    TIMESTAMPTZ  NOT NULL

INVITE                                         -- ADR-0022: one use, seven days
  invite_id     UUID PK
  team_id       UUID FK → TEAM ON DELETE CASCADE NOT NULL
  code_hash     VARCHAR(64)  NOT NULL UNIQUE   -- sha256 of the code; the join lookup
  created_by    UUID FK → USER NOT NULL
  created_on    TIMESTAMPTZ  NOT NULL
  expires_on    TIMESTAMPTZ  NOT NULL          -- read, not swept
  used_by       UUID FK → USER NULL            -- set by a conditional update: one winner
  used_on       TIMESTAMPTZ  NULL
  cancelled_on  TIMESTAMPTZ  NULL

TEAM_MEMBER
  team_member_id UUID PK
  team_id       UUID FK → TEAM ON DELETE CASCADE NOT NULL
  user_id       UUID FK → USER NOT NULL
  role          ENUM(ADMIN, MEMBER) NOT NULL
  sees_all_groups BOOLEAN    NOT NULL          -- reads every group, private ones included
  can_invite    BOOLEAN      NOT NULL DEFAULT FALSE  -- may make invite links, nothing else an
                                               -- admin can (ADR-0019, migration 0004)
  created_on    TIMESTAMPTZ  NOT NULL
  UNIQUE (team_id, user_id)

TEAM_GROUP
  group_id      UUID PK
  team_id       UUID FK → TEAM ON DELETE CASCADE NOT NULL
  path          VARCHAR(255) NOT NULL          -- 'backend/aistack': fixed at creation, so the
                                               -- groups above are read from it; ≤ 8 deep
  private       BOOLEAN      NOT NULL
  created_on    TIMESTAMPTZ  NOT NULL
  UNIQUE (team_id, path)

GROUP_MEMBER
  group_member_id UUID PK
  group_id      UUID FK → TEAM_GROUP ON DELETE CASCADE NOT NULL
  user_id       UUID FK → USER NOT NULL
  created_on    TIMESTAMPTZ  NOT NULL
  UNIQUE (group_id, user_id)

GROUP_UNSUBSCRIBED                             -- no update offers from this group or below
  group_unsubscribed_id UUID PK
  group_id      UUID FK → TEAM_GROUP ON DELETE CASCADE NOT NULL
  user_id       UUID FK → USER NOT NULL
  UNIQUE (group_id, user_id)

SKILL
  skill_id      UUID PK
  team_id       UUID FK → TEAM NOT NULL        -- the team whose vault holds it
  group_id      UUID FK → TEAM_GROUP ON DELETE SET NULL NULL   -- null = whole team
  source_skill_id UUID FK → SKILL ON DELETE SET NULL NULL      -- personal skills only: the
  source_revision INTEGER    NULL              -- team skill taken from or shared to, and its
                                               -- revision then. Newer there = an update on offer
  archived      BOOLEAN      NOT NULL          -- removed from the Library; kept so sync does
                                               -- not back the folder up again
  name          VARCHAR(64)  NOT NULL          -- ^[a-z0-9]+(-[a-z0-9]+)*$; UNIQUE (team_id, name)
  description   VARCHAR(1024) NOT NULL         -- denormalized from latest revision on push;
                                               -- required: it's the auto-trigger signal
  origin        VARCHAR(255) NULL              -- source URL when known. First-push-only: later
                                               -- pushes never overwrite it. A record only
  created_on    TIMESTAMPTZ  NOT NULL
  pushed_by     FK → USER    NOT NULL          -- who first pushed it into the vault.
                                               -- NEVER rendered as "author"/"created by":
                                               -- the vault holds third-party skills
SKILL_VERSION                                  -- immutable; a change is a new revision
  skill_version_id  UUID PK
  skill_id          FK → SKILL   NOT NULL
  revision          INTEGER      NOT NULL      -- server-assigned: 1, 2, 3…
  version           VARCHAR(32)  NULL          -- author's frontmatter version, verbatim
  content_hash      VARCHAR(64)  NOT NULL      -- canonical hash, see §4 Versions
  frontmatter_json  JSON         NOT NULL      -- parsed frontmatter incl. unknown fields;
                                               -- queryable convenience ONLY: SKILL.md in
                                               -- SKILL_FILE is verbatim truth, never regenerate
  created_on        TIMESTAMPTZ  NOT NULL
  pushed_by         FK → USER    NOT NULL      -- who uploaded this revision
  shared_over_unrelated BOOLEAN  NULL          -- true when a share put it over a different
                                               -- skill of the same name (UX-06)
  UNIQUE (skill_id, revision)                  -- revisions are allocated inside the push
                                               -- transaction (SELECT MAX(revision)+1 for this
                                               -- skill, then INSERT); on unique violation the
                                               -- push retries. Without this two concurrent
                                               -- pushes can both claim revision 2 on Postgres

SKILL_FILE
  skill_file_id     UUID PK
  skill_version_id  FK → SKILL_VERSION NOT NULL ON DELETE CASCADE
  path              VARCHAR(255) NOT NULL      -- validated per §4 Push validation
  content           TEXT         NOT NULL      -- UTF-8 only; binary rejected at push
  sha256            VARCHAR(64)  NOT NULL
  executable        BOOLEAN      NOT NULL DEFAULT FALSE  -- preserves +x for scripts
  UNIQUE (skill_version_id, path)

MACHINE_SKILL                                  -- desired state per machine and harness
  machine_skill_id  UUID PK                    -- (ADR-0004, ADR-0018)
  machine_id        FK → MACHINE NOT NULL ON DELETE CASCADE
  harness           ENUM(claude_code, agents) NOT NULL  -- varchar+check; rows from before
                                               -- harnesses became claude_code
  skill_id          FK → SKILL   NOT NULL
  enabled           BOOLEAN      NOT NULL      -- row with FALSE = explicit disable;
                                               -- no row = no decision on this machine.
                                               -- The distinction drives the sync contract
  revision          INTEGER      NULL          -- last installed or pushed here; an edited
                                               -- copy reports it as edited_from
  created_on        TIMESTAMPTZ  NOT NULL
  updated_on        TIMESTAMPTZ  NOT NULL
  UNIQUE (machine_id, harness, skill_id)

MACHINE_HARNESS                                -- the harnesses a machine has synced
  machine_harness_id UUID PK
  machine_id        FK → MACHINE NOT NULL ON DELETE CASCADE
  harness           ENUM(claude_code, agents) NOT NULL  -- varchar+check
  created_on        TIMESTAMPTZ  NOT NULL      -- its first sync
  last_synced_on    TIMESTAMPTZ  NULL
  UNIQUE (machine_id, harness)

PROJECT                                        -- a repository one person manages skills in (ADR-0026)
  project_id        UUID PK
  user_id           FK → USER NOT NULL ON DELETE CASCADE
  key               VARCHAR(255) NOT NULL      -- normalised remote, or local/<machine_id>/<digest>
  name              VARCHAR(64)  NOT NULL      -- display only
  created_on        TIMESTAMPTZ  NOT NULL
  UNIQUE (user_id, key)

MACHINE_PROJECT                                -- a project folder: one harness's folder in a project on a computer
  machine_project_id UUID PK
  machine_id        FK → MACHINE NOT NULL ON DELETE CASCADE
  project_id        FK → PROJECT NOT NULL ON DELETE CASCADE
  harness           ENUM(claude_code, agents) NOT NULL  -- varchar+check
  path              VARCHAR(1024) NULL         -- top level last seen, display only
  created_on        TIMESTAMPTZ  NOT NULL
  last_synced_on    TIMESTAMPTZ  NULL          -- null until its first sync
  repository_skills TEXT NULL                  -- names the repository holds there, one per line
  UNIQUE (machine_id, project_id, harness)
  INDEX (project_id)

MACHINE_PROJECT_SKILL                          -- desired state in a project folder
  machine_project_skill_id UUID PK
  machine_project_id FK → MACHINE_PROJECT NOT NULL ON DELETE CASCADE
  skill_id          FK → SKILL NOT NULL ON DELETE CASCADE
  enabled           BOOLEAN NOT NULL           -- false = explicit disable; no row = no decision
  revision          INT NULL                   -- last installed or pushed in this folder
  created_on        TIMESTAMPTZ  NOT NULL
  updated_on        TIMESTAMPTZ  NOT NULL
  UNIQUE (machine_project_id, skill_id)

RULE                                           -- a rule kept in the Library (ADR-0036)
  rule_id           UUID PK
  team_id           FK → TEAM NOT NULL ON DELETE CASCADE      -- the personal team, as a skill's
  project_id        FK → PROJECT NULL ON DELETE CASCADE      -- null: a rule for every project
  name              VARCHAR(64)  NOT NULL
  created_on        TIMESTAMPTZ  NOT NULL
  pushed_by         FK → USER NOT NULL ON DELETE CASCADE
  archived          BOOLEAN      NOT NULL      -- removed; the row stays, as a skill's does
  UNIQUE (team_id, project_id, name)
  UNIQUE INDEX (team_id, name) WHERE project_id IS NULL
  INDEX (project_id)

RULE_REVISION                                  -- immutable, like SKILL_VERSION
  rule_revision_id  UUID PK
  rule_id           FK → RULE NOT NULL ON DELETE CASCADE
  revision          INT NOT NULL
  text              TEXT NOT NULL              -- at most 64 KiB of UTF-8, enforced in the service
  content_hash      VARCHAR(64) NOT NULL       -- sha256 of the text's UTF-8 bytes
  created_on        TIMESTAMPTZ  NOT NULL
  pushed_by         FK → USER NOT NULL ON DELETE CASCADE
  UNIQUE (rule_id, revision)

RULE_AGENT                                     -- an agent the rule is written for
  rule_agent_id     UUID PK
  rule_id           FK → RULE NOT NULL ON DELETE CASCADE
  agent             ENUM(claude_code, codex, gemini_cli, cursor, copilot_cli, opencode) NOT NULL
  UNIQUE (rule_id, agent)

MACHINE_RULE                                   -- what a computer last had of a rule, per agent
  machine_rule_id   UUID PK
  machine_id        FK → MACHINE NOT NULL ON DELETE CASCADE
  rule_id           FK → RULE NOT NULL ON DELETE CASCADE
  agent             ENUM(as RULE_AGENT) NOT NULL
  revision          INT NULL                   -- last written or backed up there
  created_on, updated_on TIMESTAMPTZ NOT NULL
  UNIQUE (machine_id, rule_id, agent)
  INDEX (rule_id)

PROJECT_FILE                                   -- a Markdown file tracked in a project
  project_file_id   UUID PK
  project_id        FK → PROJECT NOT NULL ON DELETE CASCADE
  path              VARCHAR(1024) NOT NULL     -- relative to the top level
  agent             ENUM(as RULE_AGENT) NULL   -- null: not an agent's file
  ticked            BOOLEAN NOT NULL           -- only a ticked file is read again
  turned_off        BOOLEAN NOT NULL           -- off for this person, through the agent's settings
  size              INT NULL
  text              TEXT NULL                  -- the last text a computer uploaded
  content_hash      VARCHAR(64) NULL
  snapshot_machine_id FK → MACHINE NULL ON DELETE SET NULL
  snapshot_on       TIMESTAMPTZ NULL
  created_on        TIMESTAMPTZ NOT NULL
  UNIQUE (project_id, path)

PROJECT_FILE_EDIT                              -- an edit waiting for a working copy, then a pull request
  project_file_edit_id UUID PK
  project_file_id   FK → PROJECT_FILE NOT NULL ON DELETE CASCADE
  machine_id        FK → MACHINE NULL ON DELETE SET NULL   -- the working copy it goes to
  text              TEXT NOT NULL
  content_hash      VARCHAR(64) NOT NULL
  base_hash         VARCHAR(64) NOT NULL       -- the text it started from
  note              VARCHAR(4096) NULL         -- the commit message
  pull_request_url  VARCHAR(2048) NULL
  created_on        TIMESTAMPTZ NOT NULL
  written_on, shared_on, cancelled_on TIMESTAMPTZ NULL

LIBRARY_EVENT                                  -- local mode: one change to the Library, as a
  event_id          UUID PK                    -- GitHub Library's log holds it (ADR-0025).
                                               -- Written in the change's own transaction
  sort_key          VARCHAR(128) NOT NULL UNIQUE  -- time, machine id, event id: the replay
                                               -- order (ADR-0032)
  kind              VARCHAR(32)  NOT NULL
  body              TEXT         NOT NULL      -- the whole event as JSON, as written to git
  published         BOOLEAN      NOT NULL      -- false until it reached the repository

SCHEMA_COMPATIBILITY                           -- one row (ADR-0024)
  row_id            INTEGER PK                 -- always 1
  oldest_compatible_revision VARCHAR(32) NOT NULL  -- the oldest schema a release may know and
                                               -- still run on this database
  written_by_release VARCHAR(64) NOT NULL
  updated_on        TIMESTAMPTZ  NOT NULL      -- written by migrate_schema after each upgrade
```

Every foreign key in the project and rule tables cascades or sets null, because a release from before them rebuilds a GitHub Library's copy by deleting only the tables it knows (ADR-0025).

Behavior summary: install/adopt/restore/re-enable = `get_skill` (upsert MACHINE_SKILL enabled=true for that harness + materialize latest revision); remove = `disable_skill` + local folder deletion by the agent. Enabled skills always resolve to the latest revision (no pinning). One MCP call is one transaction: a push lands whole or not at all.

### Security posture

Trusted team, honestly stated:

- A skill body is instructions to an agent, so a hostile revision needs no script: the real vector is text, not the executable bit. Mitigation is visibility at the moment of risk: sync reports what it is about to change and who pushed it, before the agent writes anything.
- A machine updates to the latest revision of its user's own skill without confirmation. Only that user's pushes, and team revisions they chose to take, create such a revision. A teammate's change never arrives unasked: it is an offer that names who pushed it (ADR-0015).
- Any member may share over a team's skill where they may share a new one: at team level anyone, in a group those who belong to it or to a group above it (ADR-0029). The revision carries their name, and nobody receives it without accepting it.
- Machine tokens: sha256-hashed at rest, revocable by removing the computer on the dashboard or deleting its row, never logged.
- The server's invite code is a static long-lived shared secret, from `AISTACK_INVITE_CODE` or the file `AISTACK_INVITE_CODE_FILE` names: rotate by writing a new one and recreating the container (OPERATING.md); share it over something better than a group chat. Startup refuses a code under 24 characters, with fewer than 10 different ones, or printed in AIStack's own documents.
- Refused credentials are counted per client address in memory: after 20 in a minute the address gets 429 before any route runs, and each refusal is logged with the address and never with what was sent. A refused `join` for a taken name is limited to 5 an hour per address and per team code.
- Usernames and team names share one server-wide namespace, so anyone holding an invite code, or any account through `create_team`, can learn whether a name is taken. That limit makes listing them slow, not impossible: a private team's name should not itself be a secret. A team's invite is a row with a hashed code (ADR-0022): it admits one person, expires after seven days, and can be cancelled on its own. Since ADR-0019 it also creates accounts, which the expiry bounds even when a link lands in a proxy's log.
- The dashboard has no passwords. A sign-in link is a credential for five minutes, the session cookie for eight hours, and both die with the process because the signing key is in memory.

Deferred deliberately: audit trail, signing, per-skill approval workflows and push permissions. Computer connection approval follows ADR-0035.

Computer codes use twelve cryptographically random characters from `23456789ABCDEFGHJKMNPQRSTUVWXYZ` (31 characters, about 59.4 bits), displayed as three groups of four. Accept ASCII case variants with or without grouping dashes. Store only normalized sha256 hashes with indexed lookup. Unknown, expired, cancelled, denied and claimed codes give the same refusal; include transactional race losers in the existing failure limiter. Codes and request bearers travel only as bootstrap Authorization bearers, never arguments or URLs. Only creation returns the plaintext code. Dashboard state returns status and expiry, never code or command; no browser persistence. Removal or token rotation of the issuer invalidates uncompleted codes and requests, rechecked at redemption and approval. Operator `register-machine` can issue an explicitly labelled recovery code without approval when no computer remains. Recovery issuance, offboarding and forgetting use the admin command in the deployed server container, as OPERATING requires; never run an older admin package against that database. Older MCP clients remain supported. Owner-scoped dashboard mutations require the request header. Pending requests survive restart without automatic approval.

Joining and syncing use verified HTTPS. Loopback, RFC 1918, RFC 4193 and 100.64.0.0/10 addresses, or names resolving only to these, permit HTTP with one unencrypted-connection warning. Public HTTP requires `--allow-http` and a warning that the computer key can be read. Never forward credentials across an origin-changing redirect. OPERATING documents HTTPS through a reverse proxy or a VPN.

### Explicitly not built

No FastAPI, no background sync (local mode's daily release check is the only background work), no version pinning (always latest), no deleting a single revision (see §4 Tools), no project folders in local mode yet (a server syncs them; local mode follows once a release replays their events, ADR-0026), no rules/hooks/agents/MCP gateway/profiles, no OAuth/passwords, no binary files, no server-admin tools or pages (the `is_admin` column ships, but nothing reads it, so it grants no power; server-level operations are `aistack admin` commands), no harness besides Claude Code and the shared agents folder (ADR-0018). From ADR-0015: no permission matrix of roles × groups, no automatic updates from a team, no merging when both copies changed, no one machine on two servers. Anything needing many typed parameters is a dashboard action, not a tool: chat must stay low-friction.

### Proof of the MVP

The acceptance test the first release was held to, before teams. Push `wizard` and `domain-modeling` (both multi-file: a script, reference files) from machine A. Install on machine B via chat. Verify:

1. `diff -r` between source and installed copy is clean;
2. the executable bit round-trips through the vault (stored, re-applied on materialization). It is deliberately not part of the content hash (§4 Versions), and no skill in the current corpus is executable, so test it with a deliberately `chmod +x`'d file rather than assuming one exists;
3. one real run of each skill behaves identically to a native install;
4. an installed skill is usable in the same session it was installed in.

## 5. Post-MVP roadmap (decided order of interest, not committed)

1. **Second harness**: built 2026-10-14 as the shared agents folder that Codex and others read (ADR-0018, ADR-0021). Moved to the front on 2026-10-13: Claude Code now syncs a user's claude.ai skills on its own and has git-backed plugin marketplaces (§7), so one vault feeding several harnesses is where AIStack is not duplicated. The Agent Skills format is shared, so the adapter is mostly a target directory.
2. **Dashboard**: built 2026-10-14 without FastAPI (ADR-0017). A person can now remove and rename their own computers there (ADR-0027). What remains of the original plan: server admin management (grant admin, revoke other people's machines, recover locked-out users; the `is_admin` column exists and nothing reads it yet); version pinning; deleting a single revision (preview-confirm, tombstones so sync can say "deleted on purpose"); GitHub-link skill import; display names rendered from skill names.
3. **Rules**: the second resource type. Canonical rules projected into `CLAUDE.md` / `AGENTS.md` / `.cursor/rules/` by adapters.
4. **Background sync**: opportunistic (check on any MCP call) vs daemon; compare cost after the MVP.
5. **Hooks, agents**: same adapter approach; harness support varies.
6. **MCP gateway**: one AIStack MCP endpoint proxying enabled remote MCPs with central auth/policy.
7. **Profiles**: named bundles ("Backend Developer") assigning many resources at once.
8. **Teams and groups**: built 2026-10-14 (ADR-0015): a personal space per user, teams to share into, nested groups. Project-level precedence stays with item 9.
9. **Project-scoped sync**: per-project desired state once projects become a real concept. ADR-0026 sets out how. Built on a server: project identity, placements, sync, tools, the dashboard and event replay. Local mode's project actions are tracked in [#190](https://github.com/dchristopoulos/AIStack/issues/190).
10. **Secrets**: never sync plaintext credentials; store references (1Password, Vault, cloud secret stores).

## 6. Long-term direction (vision, not design)

The eventual product is the combination: cloud-style source of truth + team/project scoping + machine/harness synchronization + native resource adapters + remote MCP gateway + central auth/policy. Harnesses beyond Claude Code and Codex (Cursor, Pi, Hermes, Qwen Code, OpenCode, Gemini CLI, Copilot) come via adapters. The skill spec's portable core (`name`, `description`, body, bundled files) is normalized; complete original frontmatter is always preserved so harness-specific fields survive round-trips.

Things deliberately not overbuilt, ever, until demand is proven: a public marketplace, hundreds of integrations, universal conversion of every harness-specific field, command/prompt syncing, billing, collaborative editing, recommendation systems.

## 7. Competitive landscape (why this and not an existing tool)

- **Claude Code's own sync** (checked 2026-10-13): a session signed in to claude.ai downloads that account's skills, including ones an organization provides, into `~/.claude/skills/synced/` and keeps them current. It is download-only, edited on claude.ai, and tied to an Anthropic account. This covers "one developer, one harness, several machines" well enough that AIStack should not lead with it.
- **Claude Code plugin marketplaces**: a git repository as a team catalog, with auto-update off by default, git credentials required on every machine, and skills namespaced as `/plugin:skill`. Publishing is a commit, not a sentence in chat, and there is no per-machine state.
- **skillshare** (`runkids/skillshare`): a CLI with git as the source of truth, symlinking skills into several harnesses. Validates the multi-harness need; has no server, no per-machine desired state, and no handling of local edits.
- **MCP Gateway & Registry** (`agentic-community/mcp-gateway-registry`): gateway + registry + auth + virtual servers. AIStack differentiates on the developer/team synchronization experience across harnesses, machines, and projects, not on being "an MCP gateway".
- **AutoVault**: canonical skills synced into agents; validates the model and the need for a local write path (a cloud service cannot touch local skill directories; in AIStack, the agent itself is that write path). Broader than AIStack (profiles, signing, approval); borrow revision provenance thinking, not the architecture.
- **skills-mcp**: skills over MCP with progressive disclosure. Its metadata/body split informed the proxy idea, which we then killed (ADR-0001).
- **Skill Gateway** (one router meta-skill): rejected; native per-skill trigger descriptions are more precise.
- **Skill Manager / HarnessKit**: local-first multi-harness sync; validates adapters. AIStack's differentiator is the shared self-hosted server for teams.

## 8. Project structure (agreed, don't re-derive)

Deliberately pre-structured for scale (owner's choice over a flat MVP layout). Rule: code goes in the layer it belongs to, even while layers are thin.

```text
src/aistack/
  api/                     # the dashboard's routes: sign-in, the page, and the JSON API
                           # (ADR-0017). Starlette routes, as thin as the tools
  bundled/                 # files served as they are: the setup instructions, the
                           # sync-aistack skill a new machine needs before it can ask the
                           # server for anything, and the dashboard page; local/ holds local
                           # mode's setup steps and sync skill, which `aistack` prints
  bootstrap/               # app assembly & entrypoint
    __main__.py            #   `aistack` (local mode), `serve` (the server), `dashboard`,
                           #   `setup`, `sync-skill`, `check`, `github`, `export`, `move`,
                           #   `connect` (§4 Local mode), `sync` and `join` (ADR-0035)
    admin_cli.py           #   `aistack admin`: the operator's commands
    self_update.py         #   local mode's daily upgrade, in a background thread
    configuration/
      settings/            #   env config: DATABASE_URL, invite code, etc.
    context/               #   application context / wiring
  commons/
    exceptions/            # shared exception types
  db/
    engine + session setup; schema.py applies the migrations (ADR-0016)
    migrations/versions/   # numbered Alembic migrations, shipped in the package
    models/                # SQLAlchemy models for the nineteen tables
  mcp/                     # FastMCP server + auth
    local.py               # local mode's stdio server, with no auth (ADR-0020)
    local_dashboard.py     # local mode's open_dashboard: the localhost page in this process
    tools/                 # the thirteen MCP tools (onboarding, skills, sync, teams),
                           # and local.py: local mode's six, doing the disk work itself
    routes/                # plain HTTP beside MCP: the two transfer routes (ADR-0010),
                           # setup, and health; as thin as the tools
  services/                # business logic: push validation, sync reconciliation,
                           # visibility, team administration, token and ticket issuing;
                           # tools and routes stay thin, logic lives here
tests/
```

## 9. Open questions for the next phase

Still open:

1. What machine metadata beyond `name`/`os` ever matters: collect only when a feature needs it.
2. Whether `/mcp` reconnect picks up a changed bearer without restarting Claude Code. The onboarding flow says "restart once" until someone has watched it work without.

Resolved by the ticket #1 spikes: the pinned FastMCP threadpools plain `def` tools (ADR-0005 holds), and Claude Code completes elicitation, which sync then does not use (ADR-0012).

Resolved: the invite code is operator-supplied, from the environment or a file it names, never generated at boot and never printed; rotation is writing a new one and recreating the container. The generic-vs-specific resource model is settled by ADR-0007.
