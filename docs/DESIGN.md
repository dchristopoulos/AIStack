# AIStack design

Scope, architecture, and schema for the MVP, settled 2026-08-21, revised 2026-08-24 after two external design reviews. Vocabulary lives in `CONTEXT.md`. Decisions and their reasoning live in `docs/adr/`. This document is the current plan, so where anything else disagrees with it, this wins.

## 1. What AIStack is

A self-hosted, open-source control plane for AI development configuration. A team, or a solo developer with several machines, runs one AIStack server. It holds the canonical copies of their skills, and later their rules, agents, hooks, and MCP server definitions. Every developer installs and syncs from that shared vault through chat, from inside their coding agent.

Core promise:

> Configure once. Keep your AI stack in sync across developers, projects, machines, and harnesses.

Two use cases drive the design:

- **Small team**: a shared skill vault. Every dev sees what the others use and can install it with one sentence in chat.
- **Solo dev**: same tools on every machine (desktop, MacBook, work laptop) and eventually every harness (Claude Code, Codex, ...).

The design bar is maximum UX: the vault exists to make configuration simpler, so any feature that makes chat interactions more complicated than the problem it solves is out. When in doubt, do the smart thing silently where no data can be lost, and ask one clear question where it can.

Not a hosted SaaS. Whoever wants AIStack deploys it themselves — a company on its server, a solo dev on a VPS or home server. The project ships a one-container deploy and documents patterns (VPS, Tailscale); it does not solve hosting for you (no LAN discovery, no peer sync).

## 2. Stack

Settled:

```text
Python
Poetry
SQLAlchemy       synchronous; FastMCP threadpools plain `def` tools, so sync drivers
                 never block the event loop (see ADR-0005)
FastMCP          (the entire MVP server)
SQLite           default; DATABASE_URL switches to Postgres via psycopg (ADR-0002)
FastAPI          post-MVP, arrives with the dashboard
```

SQLite connections set `PRAGMA journal_mode=WAL`, an explicit 5-second busy timeout (the Python default, kept explicit because it is policy, not accident), and `PRAGMA foreign_keys=ON` — SQLite ignores `ON DELETE CASCADE` without it.

Still open: frontend framework (blocked on nothing — decide when the dashboard starts).

## 3. Decisions (ADRs)

- **ADR-0001 — Full local sync, runtime proxy dead.** Skills are fully materialized on disk (body + bundled files) and run natively with zero runtime dependency on AIStack. The MCP is only the install/sync channel.
- **ADR-0002 — SQLite by default, Postgres via `DATABASE_URL`.** One container beats two. Write volume is tiny (measured: five concurrent 20-file pushes drain in under 25 ms).
- **ADR-0003 — API tokens, invite-code join, no login system.** Users self-onboard with the server's invite code; machine tokens are the permanent identity mechanism. Mechanism amended 2026-08-24: FastMCP auth guards the endpoint before tool dispatch, so the invite code is presented as a bootstrap bearer token, not a tool argument. See §4 Auth.
- **ADR-0004 — Server holds desired state per machine.** `machines` and `machine_skills` live server-side; sync reconciles desired vs actual, never resolving conflicts silently.
- **ADR-0005 — Synchronous SQLAlchemy.** Reverses the earlier async convention. FastMCP threadpools sync tools by default; aiosqlite is itself a thread wrapper; the measured workload never justifies async discipline.
- **ADR-0006 — Explicit disable; sync never deletes.** Local deletion is never inferred as intent. Sync acts silently only where no data can be lost, and only `disable_skill` may cause a local file deletion.
- **ADR-0007 — Skill-specific tables; the generic resource model is deferred.** A single `RESOURCE` family serving skills, rules, hooks, agents, and MCP definitions was designed and rejected for now: those types don't share a materialization lifecycle, and generic tools would make chat carry architecture vocabulary for no user benefit. Trigger conditions for revisiting it are named in the ADR.
- **ADR-0008 — One admin, enforced by a partial unique index.** Amends the `is_admin` schema comment: the guarded UPDATE is safe on SQLite and wrong on Postgres, so the index is the enforcer, the update is the fast path, and a savepoint absorbs the loser. SQLite engines take `connect_args={"autocommit": False}` so savepoints work at all.
- **ADR-0009 — Length-prefixed canonical content hash.** Reverses the JSON canonicalization above before implementation: agent and server must agree byte for byte, and that agreement cannot rest on two JSON serializers matching. Length-prefixed framing is unambiguous with no library on either side.

## 4. MVP

One Docker container. One volume (SQLite file + config). FastMCP served over streamable HTTP. Chat is the entire interface: no dashboard, no CLI, no daemon. Claude Code is the only supported harness.

### State model (ADR-0004)

The server holds **desired** state: which skills are enabled per machine. The local disk is **actual** state. Sync reconciles the two. Each machine belongs to one user and authenticates with its own permanent token — one lookup identifies both user and machine.

### Auth

Two principals, one centralized authorization rule enforced before any tool logic runs:

- **Bootstrap principal** — the invite code presented as a bearer token. May call `join` and nothing else.
- **Machine principal** — a machine token (sha256-hashed at rest). May call everything except `join`.

`join` creates the user and their first machine and returns the permanent machine token. The agent writes it into the MCP config; from then on it authenticates every connection silently. First user to join becomes the admin.

**Secrets rule.** Tokens appear exactly once: in the `join` / `add_machine` result (and therefore in the local Claude Code transcript — accepted for the MVP). They never appear in server logs, HTTP logs, error messages, or any other tool result. The invite code is never emitted in logs, errors, tool arguments, or tool results; it exists only as the bootstrap `Authorization` bearer and as operator-supplied config.

**Revocation** (lost or stolen machine): the admin deletes the machine row — a documented one-line DB operation, no tool. If that was the user's only machine, recovery is inserting a replacement machine row (or rotating an existing machine's `token_hash`) for that same user. Never delete the user: `pushed_by` is a non-null FK from `SKILL` and `SKILL_VERSION`, so deleting a contributor either fails or destroys provenance. Dashboard makes both a button later.

### Tools (all seven, nothing else)

```text
join(username, machine_name, os) → creates user + first machine; returns the machine token
                                (bootstrap principal only; first user becomes admin.
                                `os` is required — MACHINE.os is NOT NULL and MCP cannot
                                reveal the client's platform)
add_machine(name, os)         → registers another machine for this user; returns a
                                paste-ready MCP command with that machine's token
list_skills                   → browse the vault (name + description; this is also the
                                search — and the only discovery mechanism, sync is not)
get_skill(name)               → full manifest of the latest revision; enables the skill
                                for the calling machine. The one "enable + give me the
                                files" verb — install, restore, re-enable, adopt all
                                resolve to it
push_skill(...)               → upload a skill; existing name = new revision; enables
                                the skill for the calling machine
sync(actual: {name: hash})    → reconcile desired vs actual; see the sync contract
disable_skill(name)           → enabled = false for this machine; the agent then
                                deletes the local folder
```

`delete_skill` (hard delete from the vault) is deliberately deferred to the dashboard, alongside archive: a fresh install after deleting the latest revision would silently receive an older one, hard delete erases the provenance of a hostile revision after it propagated, and a safe version needs preview-confirm plus tombstones. Disable covers "get this off my machines"; immutable revisions keep the history.

### Flows

**Onboarding (admin)**: set `AISTACK_INVITE_CODE` in env, run the container, share the code with the team over something private. The admin already knows the code because they set it — it is never printed. Startup logs confirm an invite code is configured without echoing its value. The admin joins first and becomes admin.

**Onboarding (user)**: run the documented `setup-aistack` snippet (README copy-paste — it cannot come from the vault it sets up). It creates the skills directory if missing, connects with the invite code, calls `join`, writes the returned machine token into the MCP config, and tells the user to restart Claude Code once. After that restart, installed skills load live, mid-session, no further restarts (Claude Code watches the skills directory — verified against its docs; the one exception is a directory created after session start, which this flow handles by creating it first).

**Adding a machine**: on an already-registered machine — "add my Windows PC". `add_machine` returns the full MCP-config command with the new machine's token; the user pastes it on the other computer. No redeem step; the invite code is only for new users.

**Push**: "push my wizard skill to aistack" — the agent reads the local skill directory and calls `push_skill` with a manifest: a list of files, each with `path`, `content`, and `executable`. Pushing an existing name creates a new revision and the response says so loudly: who pushed the previous revision and, when origins differ or are unknown, a warning that this may be an unrelated skill sharing the name. Push records an optional `origin` URL (GitHub repo, marketplace page) when the agent knows it. Any member may push a new revision of any skill (trusted team; `pushed_by` gives provenance, and it means exactly that — AIStack never claims authorship). Push enables the skill for the calling machine.

**Gathering rules (agent-side, documented with the push prompt)**: walk the skill directory with `lstat`; reject symlinks, sockets, devices, and FIFOs; verify every resolved path stays inside the skill root; reject duplicate paths after Unicode/case normalization. A symlink to `~/.ssh/id_rsa` inside a skill folder must never be uploaded as content.

**Bulk import** ("move to AIStack"): not a tool. A documented prompt — "push all my skills" — makes the agent loop `push_skill` over the local skills directory.

**Install**: "install wizard from aistack" — `get_skill`, agent writes the files to the global skills directory (write to a temporary sibling, then rename), and the server marks the skill enabled for this machine. Install = enable + materialize; "remove wizard" = `disable_skill` + the agent deletes the local folder. After install the skill is a plain native skill, usable immediately in the same session. (Sync manages only the global directory in the MVP; a project-local copy is a manual chat action the server doesn't track.)

### The sync contract

Sync is **manual**: the user says "sync aistack" (a one-liner local skill, **written directly to disk by the `setup-aistack` snippet** — a fresh vault cannot install the very skill that talks to it — plus the habit documented in the README: sync when you start work, like `git pull`). Nothing runs in the background; the server never polls upstream. Sync is not discovery: it reconciles what this machine manages, `list_skills` finds what it doesn't.

One rule: **sync acts silently only on skills enabled for this machine, and only when the local copy is absent or matches a revision the server knows. Everything else is reported, and the user decides.**

Enabled for this machine:

| local state | sync does |
|---|---|
| absent | install, silently |
| matches an older revision | update, silently — reporting what changed and who pushed it |
| matches the latest revision | nothing |
| matches no revision (locally modified) | ask: restore / push / skip (skip re-reports next sync) |

Not enabled for this machine, but present on disk:

| server state | local hash | sync does |
|---|---|---|
| explicitly disabled here (`enabled = false` row) | matches latest | report: re-enable (no rewrite) or remove |
| explicitly disabled here | matches an older revision | report: re-enable **and update** (states that files will be replaced) or remove |
| explicitly disabled here | matches no revision | report: push / re-enable-and-replace (**states this discards local edits**) / remove / skip |
| in the vault, no decision here (no row) | matches latest | report: adopt (no rewrite) |
| in the vault, no decision here | matches an older revision | report: adopt **and update** (states that files will be replaced) |
| in the vault, no decision here | matches no revision | report: push / adopt-and-replace (**states this discards local edits**) / skip |
| not in the vault at all | any | report as orphan, offer to push — **never auto-push** (a fresh machine may hold dozens of third-party skills; importing them unasked creates false provenance) |

A prompt that leads to overwriting local content must say so. "Adopt?" on its own is not informed consent when the local copy matches no revision.

**Hash precedence** (identical content can legitimately be pushed as two revisions, so a hash can match both): if the local hash equals the latest revision's, the copy is current. Otherwise, if it equals any revision's, it is stale. Otherwise it is unknown.

**No-op states**, stated so the contract covers the full product rather than relying on inference: absent + disabled, absent + no row, and absent + not in the vault all mean nothing to do and are never reported.

Every answer maps to an existing tool: restore / re-enable / adopt → `get_skill`; push → `push_skill`; remove → the flag is already false, the agent just deletes the folder; skip → nothing. No hidden verbs.

**Wire contract**: `sync` returns *action metadata only* — for each entry, the skill name, the action, the target revision, and who pushed it. It never returns file content. The agent then calls `get_skill` per install or update. This keeps a sync of fifty skills small, and makes `get_skill` the single materialization path rather than a second one hiding inside sync.

Two invariants:

1. **Sync never deletes a local file.** Only `disable_skill` leads to local deletion, and only because the user asked.
2. **Sync never flips `enabled` silently.** Adoption and re-enable are always questions, because both mean future pushes will overwrite that folder — something the user must agree to once.

Known, accepted quirks: a renamed local folder shows up as one missing skill plus one orphan (self-explaining, not destructive); a user who never says "sync aistack" never receives updates (background sync is roadmap item 4).

### Versions

Every push creates a `skill_version` with a server-side auto-incrementing `revision` (always present, orders history) and the author's optional frontmatter `version` string (preserved, displayed when present — never invented). Sync compares content hashes, not version numbers.

**Canonical content hash.** Agent and server compute this independently and must agree byte for byte, so the procedure is exact:

1. **Path form.** Relative and `/`-separated; convert `\` to `/` before validation. NFC-normalize once, before validation, storage, sorting, and hashing. Reject paths containing control characters.
2. **Order.** Sort by the unsigned UTF-8 *bytes* of the normalized path. Never a locale-aware sort.
3. **Content digest.** sha256 of the file's exact bytes — never text mode, never CRLF translation, never BOM stripping, never Unicode normalization of content.
4. **Framing.** For each file in order, feed the outer sha256: the path's byte length as an unsigned 8-byte big-endian integer, then the path's UTF-8 bytes, then the raw 32-byte content digest.
5. **`content_hash`** is the lowercase hex of the outer digest.

Length-prefixed framing rather than JSON (ADR-0009): what must match is the bytes, not the data structure, and two conforming JSON serializers can legitimately differ in escaping and representation. Length prefixing needs no library, no separator, and no escaping — a field cannot be misread as part of the next one.

**The executable bit is deliberately NOT hashed.** It is stored per file and applied on materialization, but excluded from the hash: Windows filesystems cannot carry it, so a Windows machine would recompute a different bit than the vault holds and see a permanent phantom conflict on every sync of every skill with a script. The cost is that a chmod-only revision is invisible to sync and needs a content change to propagate. Measured against the real corpus that costs nothing — zero of 75 files across 26 installed skills are executable, including `wizard`'s own `template.sh`, because skills invoke scripts as `bash template.sh`. Git avoids the same problem with an index; an index is not worth building for a bit that is currently always false.

### Schema (final for MVP)

Portability: runs identically on SQLite and Postgres. Enums are `VARCHAR + CHECK` (SQLAlchemy `Enum(native_enum=False)`), JSON is SQLAlchemy `JSON` (JSONB variant on PG), timestamps are `DateTime(timezone=True)` (timestamptz on PG, ISO text on SQLite).

```text
USER
  user_id       UUID PK
  username      VARCHAR(64)  NOT NULL UNIQUE
  is_admin      BOOLEAN      NOT NULL DEFAULT FALSE   -- first user to join. Enforced by a unique
                                                      -- partial index on is_admin WHERE is_admin
                                                      -- (ADR-0008). The guarded UPDATE (... AND NOT
                                                      -- EXISTS (SELECT 1 FROM user WHERE is_admin))
                                                      -- is the fast path only: on Postgres READ
                                                      -- COMMITTED it lets two concurrent joins both
                                                      -- win. The update runs in a savepoint.
                                                      -- Reserved: no MVP tool reads it
  created_on    TIMESTAMPTZ  NOT NULL

MACHINE
  machine_id    UUID PK
  user_id       FK → USER    NOT NULL
  name          VARCHAR(64)  NOT NULL
  os            ENUM(MACOS, WINDOWS, LINUX) NOT NULL   -- varchar+check, not native enum
  token_hash    VARCHAR(64)  NOT NULL UNIQUE           -- sha256 of bearer token; the auth lookup
  created_on    TIMESTAMPTZ  NOT NULL
  UNIQUE (user_id, name)

SKILL
  skill_id      UUID PK
  name          VARCHAR(64)  NOT NULL UNIQUE   -- ^[a-z0-9]+(-[a-z0-9]+)*$
  description   VARCHAR(1024) NOT NULL         -- denormalized from latest revision on push;
                                               -- required: it's the auto-trigger signal
  origin        VARCHAR(255) NULL              -- source URL when known. First-push-only: later
                                               -- pushes are compared against it, never overwrite
                                               -- it. Differing origins, or a NULL on either
                                               -- side, trigger the name-collision warning
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
                                               -- queryable convenience ONLY — SKILL.md in
                                               -- SKILL_FILE is verbatim truth, never regenerate
  created_on        TIMESTAMPTZ  NOT NULL
  pushed_by         FK → USER    NOT NULL      -- who uploaded this revision
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

MACHINE_SKILL                                  -- desired state per machine (ADR-0004)
  machine_skill_id  UUID PK
  machine_id        FK → MACHINE NOT NULL ON DELETE CASCADE
  skill_id          FK → SKILL   NOT NULL
  enabled           BOOLEAN      NOT NULL      -- row with FALSE = explicit disable;
                                               -- no row = no decision on this machine.
                                               -- The distinction drives the sync contract
  created_on        TIMESTAMPTZ  NOT NULL
  updated_on        TIMESTAMPTZ  NOT NULL
  UNIQUE (machine_id, skill_id)
```

Behavior summary: install/adopt/restore/re-enable = `get_skill` (upsert MACHINE_SKILL enabled=true + materialize latest revision); remove = `disable_skill` + local folder deletion by the agent. Enabled skills always resolve to the latest revision (no pinning). One MCP call is one transaction — a push lands whole or not at all.

### Security posture

Trusted team, honestly stated:

- A skill body is instructions to an agent, so a hostile revision needs no script — the real vector is text, not the executable bit. Mitigation is visibility at the moment of risk: sync reports what it is about to change and who pushed it, before the agent writes anything.
- Revisions auto-update to latest without confirmation. This is accepted risk for a trusted team, recorded here so it is a decision and not an accident.
- Machine tokens: sha256-hashed at rest, revocable by row deletion, never logged.
- The invite code is a static long-lived shared secret: rotate by changing the env var and restarting; share it over something better than a group chat. Expiry/single-use codes are post-MVP.

Deferred deliberately: audit trail, signing, approval workflows, per-skill push permissions (all dashboard-era).

### Explicitly not in the MVP

No dashboard, no FastAPI, no CLI/daemon, no archive, no `delete_skill` (see §4 Tools), no version pinning (always latest), no project-scoped sync (global directory only), no rules/hooks/agents/MCP gateway/profiles, no workspaces beyond the single implicit one, no OAuth/passwords, no binary files, no admin tools (the `is_admin` column ships; its powers are documented DB operations until the dashboard), no harness besides Claude Code. Anything needing many typed parameters waits for the dashboard — chat must stay low-friction.

### Proof of the MVP

Push `wizard` and `domain-modeling` (both multi-file: a script, reference files) from machine A. Install on machine B via chat. Verify:

1. `diff -r` between source and installed copy is clean;
2. the executable bit round-trips through the vault (stored, re-applied on materialization). It is deliberately not part of the content hash (§4 Versions), and no skill in the current corpus is executable — so test it with a deliberately `chmod +x`'d file rather than assuming one exists;
3. one real run of each skill behaves identically to a native install;
4. an installed skill is usable in the same session it was installed in.

## 5. Post-MVP roadmap (decided order of interest, not committed)

1. **Dashboard** — FastAPI joins the stack; login sessions on top of tokens; admin management (grant admin, revoke machines, recover locked-out users — the `is_admin` column already exists); per-machine enable toggles; version pinning; archive skills and `delete_skill` (preview-confirm, per-revision, tombstones so sync can say "deleted on purpose"); GitHub-link skill import; display names rendered from skill names.
2. **Rules** — the second resource type. Canonical rules projected into `CLAUDE.md` / `AGENTS.md` / `.cursor/rules/` by adapters.
3. **Second harness** — Codex is the likely candidate; adapters translate canonical resources into native form.
4. **Background sync** — opportunistic (check on any MCP call) vs daemon; compare cost after the MVP.
5. **Hooks, agents** — same adapter approach; harness support varies.
6. **MCP gateway** — one AIStack MCP endpoint proxying enabled remote MCPs with central auth/policy.
7. **Profiles** — named bundles ("Backend Developer") assigning many resources at once.
8. **Workspaces/projects as real scoping** — precedence chain computing an effective configuration.
9. **Project-scoped sync** — per-project desired state once projects become a real concept.
10. **Secrets** — never sync plaintext credentials; store references (1Password, Vault, cloud secret stores).

## 6. Long-term direction (vision, not design)

The eventual product is the combination: cloud-style source of truth + team/project scoping + machine/harness synchronization + native resource adapters + remote MCP gateway + central auth/policy. Harnesses beyond Claude Code and Codex (Cursor, Pi, Hermes, Qwen Code, OpenCode, Gemini CLI, Copilot) come via adapters. The skill spec's portable core (`name`, `description`, body, bundled files) is normalized; complete original frontmatter is always preserved so harness-specific fields survive round-trips.

Things deliberately not overbuilt, ever, until demand is proven: a public marketplace, hundreds of integrations, universal conversion of every harness-specific field, command/prompt syncing, billing, collaborative editing, recommendation systems.

## 7. Competitive landscape (why this and not an existing tool)

- **MCP Gateway & Registry** (`agentic-community/mcp-gateway-registry`): gateway + registry + auth + virtual servers. AIStack differentiates on the developer/team synchronization experience across harnesses, machines, and projects — not on being "an MCP gateway".
- **AutoVault**: canonical skills synced into agents; validates the model and the need for a local write path (a cloud service cannot touch local skill directories — in AIStack, the agent itself is that write path). Broader than AIStack (profiles, signing, approval); borrow revision provenance thinking, not the architecture.
- **skills-mcp**: skills over MCP with progressive disclosure. Its metadata/body split informed the proxy idea — which we then killed (ADR-0001).
- **Skill Gateway** (one router meta-skill): rejected; native per-skill trigger descriptions are more precise.
- **Skill Manager / HarnessKit**: local-first multi-harness sync; validates adapters. AIStack's differentiator is the shared self-hosted server for teams.

## 8. Project structure (agreed — don't re-derive)

Deliberately pre-structured for scale (owner's choice over a flat MVP layout). Rule: code goes in the layer it belongs to, even while layers are thin.

```text
src/aistack/
  api/                     # FastAPI — EMPTY until the dashboard (post-MVP); do not fill early
  bootstrap/               # app assembly & entrypoint
    __main__.py            #   python -m aistack.bootstrap
    configuration/
      settings/            #   env config: DATABASE_URL, invite code, etc.
    context/               #   application context / wiring
  commons/
    exceptions/            # shared exception types
  db/
    engine + session setup
    models/                # SQLAlchemy models for the six tables
  mcp/                     # FastMCP server + auth
    tools/                 # the seven MCP tools (onboarding, skills, sync)
  services/                # business logic: push validation, sync reconciliation,
                           # token issuing — tools stay thin, logic lives here
tests/
```

## 9. Open questions for the next phase

Facts to verify in ticket #1 (spikes — decisions do not depend on them, only which variant gets built):

1. **Elicitation end to end**: does Claude Code + the pinned FastMCP version complete the current MCP elicitation flow? If yes, sync asks inside one call; if no, sync returns questions as data and the agent asks in chat. Both are designed above.
2. **Threadpool default**: confirm the pinned FastMCP version threadpools `def` tools (a sleeping tool called twice concurrently: ~1× the sleep means threads).

Implementation-level, still open:

3. What machine metadata beyond `name`/`os` ever matters — collect only when a feature needs it.
4. Exact FastMCP schemas for the seven tools (the file manifest shape is settled: a list of `{path, content, executable}`; `sync` returns action metadata only, never file content).

Resolved: the invite code is operator-supplied via env only, never generated at boot and never printed — rotation is changing the env var and restarting. The generic-vs-specific resource model is settled by ADR-0007.
