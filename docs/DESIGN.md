# AIStack design

Scope, architecture, and schema for the MVP, settled 2026-08-21, revised 2026-08-24 after two external design reviews, 2026-10-13 after research into what the client can carry (ADR-0010 to ADR-0012), 2026-10-14 for the personal space, teams, groups, migrations, and the dashboard (ADR-0015 to ADR-0017), and 2026-10-16 to match the code after the October audit. Vocabulary lives in `CONTEXT.md`. Decisions and their reasoning live in `docs/adr/`. This document is the current plan, so where anything else disagrees with it, this wins.

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

## 4. What is built

One Docker container. One volume (SQLite file + config). FastMCP served over streamable HTTP, plus plain HTTP routes on the same port: two that carry skill archives (ADR-0010), setup, health, and the dashboard with its JSON API (ADR-0017). The same package is also local mode (ADR-0020): `aistack` over stdio, started by the agent, with a few terminal commands beside it (§4 Local mode). Nothing syncs in the background; the only background work is local mode's daily check for a newer release. The connected agent, Claude Code or Codex, syncs both skills folders on its computer: Claude Code's and the shared agents folder that Codex and others read (ADR-0018, ADR-0021).

### State model (ADR-0004)

The server holds **desired** state: which of a user's own skills are enabled per machine and harness. The local disk is **actual** state. Sync reconciles the two. Each machine belongs to one user and authenticates with its own permanent token: one lookup identifies both user and machine.

### Auth

Two MCP principals, one centralized authorization rule enforced before any tool logic runs:

- **Bootstrap principal**: an invite code presented as a bearer token: the server's, or a team's, which `join` also makes the new user a member of (ADR-0019). May call `join` and nothing else.
- **Machine principal**: a machine token (sha256-hashed at rest). May call everything except `join`.

The dashboard has its own credential and reaches no MCP tool: a session cookie holding a signed ticket for one user, set by opening the link `open_dashboard` returns (ADR-0017). `/app` and `/api/*` refuse without it, and a request that changes state must also carry a header a cross-site form cannot send.

`join` creates the user and their first machine and returns the permanent machine token. The agent writes it into the MCP config; from then on it authenticates every connection silently. The first user to join is marked the server's admin (`is_admin`), but no code reads that mark today, so it grants no power: server-level operations are `aistack admin` commands (`docs/OPERATING.md`).

**Secrets rule.** Tokens appear exactly once: in the `join` / `add_machine` result (and therefore in the local Claude Code transcript, accepted for the MVP), or in what `aistack admin rotate` and `register-machine` print to the operator's terminal. They never appear in server logs, HTTP logs, error messages, or any other tool result. The invite code is never emitted in logs, errors, tool arguments, or tool results; it exists only as the bootstrap `Authorization` bearer and as operator-supplied config. A team's invite code is made by the server, stored only as a hash, and appears once, in the answer to the admin who asked for it. A dashboard link is a credential for five minutes and is never logged.

**Revocation** (lost or stolen machine): the user removes the computer on the dashboard, which ends its token, its dashboard sessions and its transfer URLs at once (ADR-0027); the user's last computer cannot be removed there. The operator can also remove the computer with `aistack admin remove-machine`. If that was the user's only machine, recovery is `aistack admin register-machine` or `aistack admin rotate` for that same user. Never delete the user: `pushed_by` is a non-null FK from `SKILL` and `SKILL_VERSION`, so deleting a contributor either fails or destroys provenance.

### Tools (all thirteen, nothing else)

```text
join(username, machine_name, os, full_name?)
                              → creates user + first machine; returns the machine token
                                (bootstrap principal only; first user becomes admin.
                                `os` is required: MACHINE.os is NOT NULL and MCP cannot
                                reveal the client's platform; `full_name` is what
                                teammates read beside the username)
add_machine(name, os)         → registers another machine for this user; returns a
                                paste-ready Claude Code command and Codex config
                                block, each with that machine's token
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
sync(local: {name: {path: sha256}}, harness?, here?, project?, repository?)
                              → reconcile desired vs actual for one harness; see the sync
                                contract. `here` names the session's repository, and
                                `project` syncs that project's folder instead (ADR-0026)
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

The `aistack` command (`bootstrap/__main__.py`) also takes these terminal commands: `serve` runs the server; `dashboard` serves the Library's dashboard on 127.0.0.1 and opens it; `setup` prints local mode's setup steps and `sync-skill` its sync skill (there is no server to fetch them from); `check` sets up this computer's side of the Library once and says whether it works; `github` signs in to GitHub and finds or creates the private repository a Library lives in; `export` writes every skill in the Library to a folder; `status --hook` is local mode's session-start hook, which reminds the agent to sync only when a dry run of sync, rolled back, has something to do; `move github`, `move postgresql` or `move here` moves the Library with its history; `connect claude-code` or `connect codex` connects an agent to it. When local mode runs from a uv tool install, `bootstrap/self_update.py` checks for a newer release once a day in a background thread and installs it for the next start.

### Flows

**Onboarding (admin)**: set `AISTACK_INVITE_CODE` in env, run the container, share the code with the team over something private. The admin already knows the code because they set it; it is never printed. Startup logs confirm an invite code is configured without echoing its value. The admin joins first and becomes admin.

**Onboarding (user)**: paste one sentence into Claude Code: "Set up AIStack: fetch `<server>/setup` and follow it. Invite code: …". The server serves those instructions itself, with its own address filled in, because they cannot come from the vault they set up. The agent creates the skills directory if missing, fetches the `sync-aistack` skill from the server, calls `join` with one HTTP request carrying the invite code as its bearer (ADR-0013), writes the returned machine token into the MCP config at user scope, and tells the user to restart Claude Code once. After that restart, installed skills load live, mid-session, no further restarts (Claude Code watches the skills directory, verified against its docs; the one exception is a directory created after session start, which this flow handles by creating it first).

**Adding a machine**: on an already-registered machine: "add my Windows PC". `add_machine` returns the full Claude Code command and the Codex `config.toml` block, each with the new machine's token; the user pastes the one for their agent on the other computer. No redeem step; the invite code is only for new users.

**Back up** (push): "push my wizard skill to aistack", or a name sync listed under `backup`: the agent calls `push_skill` with the skill's name and gets back a signed upload URL, then sends a gzipped tar of the skill directory to it with `tar` and `curl`, as the tool's description spells out. The server validates the archive, stores the revision in the caller's own skills, and answers the upload with the result the agent reports; a rejection comes back as the same kind of sentence a tool error would carry. Uploading content identical to the latest revision creates nothing and says so, so repeating "push all my skills" does not mint a revision per skill per run. Pushing a name the user already has adds a revision. Push records an optional `origin` URL (GitHub repo, marketplace page) the first time, when the agent knows it. Push enables the skill for the calling machine and shares nothing.

**Share**: "share wizard with backend": `share_skill` copies the latest revision of the caller's own skill into a team, or a group in it. No bytes move through the client. The team's copy has its own history, and every revision in it names who shared it (`pushed_by` means exactly that, AIStack never claims authorship). Any member may share over a team's skill at team level, and over one in a group if they may share into that group (ADR-0029). When the team already had that name and the sharer's copy was never taken from it, the result says so (`possibly_unrelated`), because it may be an unrelated skill that shares the name. When the sharer's copy was taken from an older revision than the team's latest, the result names the revision it went over (`overwrote_revision`), because that revision's changes are no longer in the team's latest.

**Take**: "install wizard from backend": `get_skill` with a team copies that team's latest revision into the caller's own skills, remembers the source and its revision, and then installs as below. The copy stays theirs if they leave the team. When the caller already has a different skill of that name that was never taken from this team, the call is refused with a sentence naming their revision and the computers it is on, until it is repeated with `replace` true: taking replaces it everywhere, and it may be an unrelated skill that only shares the name. A copy follows one team for updates; sharing it into another team leaves it following the first (`updates_from` in the share result).

**Gathering rules**: `tar` archives a symlink as a symlink, not as its target, so a link to `~/.ssh/id_rsa` inside a skill folder arrives as a link entry and the server rejects the push by naming it. The same goes for sockets, devices, FIFOs, and hard links. The push prompt tells the agent to set `COPYFILE_DISABLE=1` on macOS so `tar` does not synthesize `._*` AppleDouble entries, and to leave `.git` out. The server enforces all of it regardless (§4 Push validation); the prompt only makes the first attempt succeed.

**Bulk import** ("move to AIStack"): not a tool. The first sync lists every local skill under `backup` and the agent pushes each one.

**Install**: "install wizard": `get_skill` marks one of the caller's own skills enabled for this machine and returns a signed download URL. The agent downloads and extracts the archive under `<skills>/.aistack-staging/`, then renames it into the global skills directory, so a failed download never leaves half a skill where Claude Code is watching. Install = enable + materialize; "remove wizard" = `disable_skill` + the agent deletes the local folder. After install the skill is a plain native skill, usable immediately in the same session. On a server, a project's skills folders are synced the same way once the person adds the project: the `sync-aistack` skill sorts their folders with git, and installs only where it has made git ignore the folder (ADR-0026).

### The sync contract

Sync is **manual**: the user says "sync aistack" (a one-liner local skill, **written directly to disk by the `setup-aistack` snippet**, because a fresh vault cannot install the very skill that talks to it, plus the habit documented in the README: sync when you start work, like `git pull`). Nothing runs in the background; the server never polls upstream. Sync is not discovery: it reconciles what this machine manages, `list_skills` finds what it doesn't.

**Per harness.** One sync call covers one harness's folder. The server reads only that harness's decisions for the machine, so every table below applies per folder, unchanged (ADR-0018): a skill enabled in Claude Code and never decided in the agents folder is undecided there. A skill backed up from a folder is placed in that folder only. Sync records that the harness synced, and when, in `machine_harness`; that is the only thing it writes. The report's `first_sync` says whether this call created that row, which is when the agent asks once whether both folders should hold the same skills (ADR-0021).

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
| not among the user's own skills | any | list under `backup`; the agent backs it up to the Library **without asking**. That space is private, so nothing is shared and nobody else sees the user as the pusher of something they only downloaded (this replaces "never auto-push", which guarded a vault everyone shared) |

A prompt that leads to overwriting local content must say so. "Adopt?" on its own is not informed consent when the local copy matches no revision.

**Hash precedence** (identical content can legitimately be pushed as two revisions, so a hash can match both): if the local hash equals the latest revision's, the copy is current. Otherwise, if it equals any revision's, it is stale. Otherwise it is unknown.

**No-op states**, stated so the contract covers the full product rather than relying on inference: absent + disabled, absent + no row, and absent + not in the Library all mean nothing to do and are never reported.

Every answer maps to an existing tool: restore / re-enable / adopt → `get_skill` (on the wire, `restore` for a skill already enabled here and `enable` for the other two); push → `push_skill`; remove → the flag is already false, the agent just deletes the folder; skip → nothing. No hidden verbs.

**Wire contract**: the agent sends, for every skill folder in the harness's skills folder, each file's relative path and the sha256 of its bytes. The server derives the canonical hash from those (ADR-0011) and returns *action metadata only*: skills to install, skills to update, questions, the names to back up, and team updates on offer. For each entry that is the skill name, the target revision, and who pushed it; a question also carries the state that was found, the options the user may choose, and for each option whether it replaces local files and whether it discards local edits (ADR-0012). It never returns file content. The agent then calls `get_skill` per install or update, and `push_skill` per name to back up. This keeps a sync of fifty skills small, and makes `get_skill` the single materialization path rather than a second one hiding inside sync.

Two folders are never reported: `synced`, which Claude Code reserves for skills it downloads from claude.ai, and anything starting with a dot. The `sync-aistack` skill leaves them out of what it sends, along with `.DS_Store` files. The `sync-aistack` folder itself is never listed under `backup`: setup wrote it from the server, so it needs no backing up. Instead the server compares it with the copy it ships, and when the machine's is missing or different the report carries `sync_skill_url`, which the agent downloads over it without asking. In the agents folder that happens only where the skill already is, because setup put it there for a connected Codex, or on a computer whose Claude Code never synced: there the agent syncing that folder is the one connected to AIStack, as on a Codex-only computer added with `add_machine`. Anywhere else it would tell an unconnected agent to sync (ADR-0021). That is how the skill follows a server upgrade, and how a machine connected with `add_machine`, which never ran setup, gets it at all; the download uses `curl --create-dirs`, because such a machine has no `sync-aistack` folder yet. If the user pushes their own copy of the skill, it is reconciled like any other and the field stays null.

Three invariants:

1. **Sync never deletes a local file.** Only `disable_skill` leads to local deletion, and only because the user asked.
2. **Sync never flips `enabled` silently.** Adoption and re-enable are always questions, because both mean later revisions will overwrite that folder: something the user must agree to once.
3. **Sync never applies a teammate's change.** A newer revision in a team is listed under `team_updates` and reaches a machine only when the user accepts it, each time (ADR-0015).

Known, accepted quirks: a renamed local folder shows up as one missing skill plus one new one to back up (self-explaining, not destructive); a user who never says "sync aistack" never receives updates (background sync is roadmap item 4).

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

**Two columns are the map.** A rail on the left holds the user's spaces, the way a chat application lists servers: *Personal* on top, then each team, then one *+* that creates a team or joins one with a code. The column beside it lists what is in the chosen space, and the account bar with sign-out runs under both at the bottom. For Personal that is the Library, with a blue dot and a count when updates are waiting, and then each computer as one row per coding agent on it, opening that agent's page at `#/f/<machine id>/<agent>`. The *+* beside the Computers heading says what to ask an already connected agent to add another computer. A computer's agents are the `harnesses` `/api/state` lists for it, and a skill is placed in one of them, not on the computer as a whole. For a team it is All skills, the team's groups nested a step in per level, then Members and Settings. A private group has a lock, every group shows how many skills are in it and below it, and a blue dot marks one with an update waiting for a skill the user took. Choosing a group opens the team's skills narrowed to that group and the groups under it, at `#/t/<team>/skills/<group path>`, an address that can be reloaded or sent to a teammate. The tree is built from the groups `/api/state` sends, so a private group the user is not in is absent from it, and its address opens the whole team exactly as an unknown one does.

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
| `POST /api/skills/{name}/machines/{machine_id}` | `enabled` (true or false), optional `harness` (`claude_code`, the default, or `agents`), optional `project` (a key that computer manages) | Switches one of the user's own skills on or off in one harness of one of their computers, or in that project's folder there (server only). The files move at that folder's next sync there |
| `POST /api/machines/{machine_id}/projects` | `project` (a key), optional `harness` | Starts managing one of the user's projects, already known from another computer, on this computer. Its path is unknown until it syncs there. Server only |
| `POST /api/machines/{machine_id}/projects/remove` | `project`, optional `harness` (every harness when omitted) | Stops managing that project on this computer; its placements there go with it. The files on disk, the Library and the other computers are untouched. Answers `removed`, the number of folders. Server only |
| `POST /api/skills/{name}/share` | `team`, `group` (a path, or null for team level) | `team`, `group`, `revision`, `created`, `unchanged`, `previous_pushed_by`, `possibly_unrelated`, `overwrote_revision`, `updates_from`: what `share_skill` returns |
| `POST /api/skills/{name}/bring-back` | `{}` | `name`. Puts a skill removed from the Library back, on no computer. Server only |
| `GET /api/skills/{name}/history` | | `revisions`, newest first: each `revision`, `pushed_by`, `pushed_on` (UTC), and `files`. Server only |
| `POST /api/skills/{name}/restore` | `revision` | `revision`, the new one, and `unchanged`. Stores that revision's files as the newest, pushed by the user; every computer that has the skill installs it at its next sync. Server only |
| `GET /api/teams/{team}/skills/{name}/changes` | | What taking the team's latest would change in the user's copy: `from_revision` (theirs), `to_revision`, `pushed_by`, `files` (each `path`, `change` as `added`, `removed` or `changed`, and a unified `diff`), and `truncated` when the diff was cut |
| `POST /api/skills/{name}/remove` | `{}` | Removes the skill from the Library on every computer |
| `POST /api/machines/{machine_id}/remove` | `{}` | `removed`: the computer's name. Its token, sessions and transfer URLs end at once. The user's last computer is refused with `409`. Server only (ADR-0027) |
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
| `POST /api/teams/{team}/group` | `path`, and `private` (admin only) and/or `subscribed` (anyone who sees the group) | |
| `POST /api/teams/{team}/group/members` | `path`, `username`, `member` (true or false) | Admin only |
| `POST /api/teams/{team}/group/rename` | `path`, `name` | Admin only. The groups under it follow; answers the new `path` |
| `POST /api/teams/{team}/group/delete` | `path` | Admin only, and only a group with no skills and no groups inside it |
| `POST /api/teams/{team}/skills/{name}/move` | `group` (a path, or null for team level) | Admin only |
| `POST /api/teams/{team}/skills/{name}/remove` | `{}` | Removes the team's copy. Admin only |

A group's path contains slashes, so it always travels in the body and never in the address.

**On the localhost dashboard** (`aistack dashboard`, or local mode's `open_dashboard`), only the sign-in routes, `GET /app`, `GET /api/state`, `POST /api/logout`, placing a skill and removing one from the Library are served. Sharing, the computer and account routes, and every team route are server only, because a team needs a server everyone reaches. There, each `POST` result also carries `shared`: false when a GitHub Library could not be reached, so the change waits on this computer.

**`GET /api/state`.** One object, holding only what this user may see: `services/visibility.py` decided that before it was built, and the page filters nothing.

```json
{
  "user": {"username": "dimitris", "full_name": "Dimitris Christopoulos"},
  "machines": [
    {"id": "af6c2628-…", "name": "macbook", "os": "MACOS", "harnesses": ["claude_code"],
     "added_on": "2026-10-13T09:12:01.402113+00:00", "added_by": null, "added_by_removed": false,
     "last_synced": {"claude_code": "2026-10-14T00:40:12.513920+00:00"},
     "projects": [{"key": "github.com/dchristopoulos/aistack", "name": "aistack",
                   "folders": [{"harness": "claude_code", "path": "/Users/dimitris/code/aistack",
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
  "teams": [
    {
      "name": "acme", "kind": "SHARED", "role": "ADMIN", "sees_all_groups": false,
      "can_invite": false,
      "members": [
        {"username": "maria", "full_name": null, "role": "MEMBER", "sees_all_groups": false,
         "can_invite": true, "groups": ["backend"]}
      ],
      "groups": [
        {"path": "backend/aistack", "private": false, "member": true, "subscribed": true}
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
  "release": "0.1.0"
}
```

| Field | Meaning |
|---|---|
| `release` | The AIStack release serving the page, as the startup log names it (Settings shows it) |
| `server` | False on the localhost dashboard in local mode, where the page hides what only a server can do: creating, joining, and sharing with a team |
| `library` | Where the Library lives, by `kind`: `{"kind": "server"}`, `{"kind": "this_computer"}`, `{"kind": "postgresql", "provider": "Neon", "host": "…"}`, or `{"kind": "github", "repository": "owner/name", "problem": null, "unpublished": 0}`. Never an address or a password |
| `library.provider`, `host` | For a PostgreSQL Library: the provider recognised from the host (Neon, Supabase, or PostgreSQL), and the host |
| `library.repository`, `problem`, `unpublished` | For a GitHub Library: the repository as owner/name, why it could not be reached the last time it was tried (null when it answered), and how many changes made here have not reached it yet |
| `user` | The signed-in user: `username`, and `full_name` or null |
| `machines` | The user's computers, oldest first. `id` is the machine id the routes take, `name` its name, and `os` is `MACOS`, `WINDOWS`, or `LINUX` |
| `machines[].added_on`, `added_by` | When the computer was registered, and the name of the computer whose `add_machine` registered it: null for a first computer. `added_by_removed` is true when that computer has since been removed (ADR-0027) |
| `machines[].last_synced` | Each of its harnesses, with when it last synced (UTC), or null for one that never has |
| `machines[].harnesses` | The harnesses on that computer, in the server's order: those that have synced there, those holding a decision about a skill, and those with a project folder. `[]` for a computer with none, which has never synced |
| `machines[].projects` | The projects this computer manages (ADR-0026), by name: each with its `key` and `name`, and its `folders`, one per harness, with the top level last seen there (`path`, null until that folder syncs, and shown only) and `last_synced_on` |
| `skills` | The Library, by name, without the ones removed from it. Each has its `name` and `description` |
| `removed` | The names of the skills removed from the Library, which Bring back can return |
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
| `teams[].groups` | The groups the user may see, by `path`; an admin sees all of them. `private` is whether it is private, `member` whether the user is in it, `subscribed` whether they are offered its updates |
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
  created_on    TIMESTAMPTZ  NOT NULL
  added_by_machine_id UUID   NULL                      -- the computer whose add_machine registered
                                                       -- it; null for a first computer. No FK, so
                                                       -- it outlives that computer (ADR-0027)
  UNIQUE (user_id, name)

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

Every foreign key in the project tables cascades, because a release from before them rebuilds a GitHub Library's copy by deleting only the tables it knows (ADR-0025).

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

Deferred deliberately: audit trail, signing, approval workflows, per-skill push permissions.

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
                           #   and `connect` (§4 Local mode)
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
    models/                # SQLAlchemy models for the eighteen tables
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
