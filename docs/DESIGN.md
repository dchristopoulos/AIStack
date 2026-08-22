# AIStack design

Scope, architecture, and schema for the MVP, settled 2026-08-21. Vocabulary lives in `CONTEXT.md`. Decisions and their reasoning live in `docs/adr/`. This document is the current plan, so where anything else disagrees with it, this wins.

## 1. What AIStack is

A self-hosted, open-source control plane for AI development configuration. A team, or a solo developer with several machines, runs one AIStack server. It holds the canonical copies of their skills, and later their rules, agents, hooks, and MCP server definitions. Every developer installs and syncs from that shared vault through chat, from inside their coding agent.

Core promise:

> Configure once. Keep your AI stack in sync across developers, projects, machines, and harnesses.

Two use cases drive the design:

- **Small team**: a shared skill vault. Every dev sees what the others use and can install it with one sentence in chat.
- **Solo dev**: same tools on every machine (desktop, MacBook, work laptop) and eventually every harness (Claude Code, Codex, ...).

Not a hosted SaaS. Whoever wants AIStack deploys it themselves — a company on its server, a solo dev on a VPS or home server. The project ships a one-container deploy and documents patterns (VPS, Tailscale); it does not solve hosting for you (no LAN discovery, no peer sync).

## 2. Stack

Settled:

```text
Python
Poetry
SQLAlchemy       async throughout (aiosqlite / asyncpg); FastMCP handlers are async
FastMCP          (the entire MVP server)
SQLite           default; DATABASE_URL switches to Postgres (ADR-0002)
FastAPI          post-MVP, arrives with the dashboard
```

Still open: frontend framework (blocked on nothing — decide when the dashboard starts).

## 3. Decisions (ADRs)

- **ADR-0001 — Full local sync, runtime proxy dead.** Skills are fully materialized on disk (body + bundled files) and run natively with zero runtime dependency on AIStack. The MCP is only the install/sync channel. The proxy-skill idea (tiny local stub fetching the body at trigger time) is dead: it costs strictly more tokens than native progressive disclosure, adds latency and an offline failure mode, and bundled files must be on disk anyway.
- **ADR-0002 — SQLite by default, Postgres via `DATABASE_URL`.** Self-hosted means every server dependency is the user's problem; one container beats two. Write volume is tiny.
- **ADR-0003 — API tokens, invite-code join, no login system.** Users self-onboard by redeeming the server's invite code via a `join` tool; tokens are embedded once in the harness MCP config and are the permanent identity mechanism. Dashboard-era login later sits on top of tokens, never replaces them.
- **ADR-0004 — Server holds desired state per machine.** Reverses the earlier stateless-sync idea: `machines` (one token each, bound to a user) and `machine_skills` (enabled flags) live server-side; sync reconciles desired vs actual, never resolving conflicts silently.

## 4. MVP

One Docker container. One volume (SQLite file + config). FastMCP served over streamable HTTP. Chat is the entire interface: no dashboard, no CLI, no daemon. Claude Code is the only supported harness.

### State model (ADR-0004)

The server holds **desired** state: which skills are enabled per machine. The local disk is **actual** state. Sync reconciles the two. Each machine belongs to one user and authenticates with its own permanent token — one lookup identifies both user and machine.

### Tools (all six, nothing else)

```text
join(invite_code, username, machine_name) → token for user's first machine
add_machine(name, os)         → registers another machine for this user; returns a
                                paste-ready MCP command with that machine's token
list_skills                   → browse the vault (name + description; this is also the search)
get_skill(name)               → full text-only manifest for install
push_skill(...)               → upload a skill; existing name = new revision
sync(actual: {name: hash})    → server compares against this machine's enabled skills,
                                returns installs/updates/conflicts to reconcile
```

### Flows

**Onboarding (admin)**: run the container, read the invite code from logs/config, share it with the team.

**Onboarding (user)**: tell the agent "join aistack as maria, code X, this is my macbook". `join` creates the user and the machine, returns the machine token; it goes into the MCP config once (the agent can perform the edit) and authenticates every future connection silently.

**Adding a machine**: on an already-registered machine — "add my Windows PC". `add_machine` returns the full MCP-config command with the new machine's token; the user pastes it on the other computer. No redeem step; the invite code is only for new users.

**Push**: "push my wizard skill to aistack" — the agent reads the local skill directory and calls `push_skill` with a manifest: a list of files, each with `path`, `content`, and `executable`. Not a flat `{path: content}` map — that cannot carry the executable bit `SKILL_FILE` stores and the proof requires. `get_skill` and `sync` hand back the same shape. Binary files are rejected at push with a clear error. Pushing an existing name creates a new revision. Any member may push a new revision of any skill (trusted team; `created_by` gives attribution).

**Bulk import** ("move to AIStack"): not a tool. A documented prompt — "push all my skills" — makes the agent loop `push_skill` over the local skills directory.

**Install**: "install wizard from aistack" — `get_skill`, agent writes the files to the global skills directory, and the server marks the skill enabled for this machine. Install = enable + materialize; "remove wizard" = disable + delete the local folder. After install the skill is a plain native skill. (Sync manages only the global directory in the MVP; a project-local copy is a manual chat action the server doesn't track.)

**Sync**: manual only, via a local one-liner "sync aistack" skill that tells the agent to call the `sync` tool with `{name: content_hash}` of what's on disk. The server answers with: skills to install (enabled, missing locally), skills to update (hash behind latest revision — always latest in MVP, no pinning), and conflicts. Conflicts are never resolved silently: **locally modified** → ask the user: restore vault version / push as new revision / skip (warned again next sync); **enabled but locally deleted** → ask: reinstall / disable for this machine.

### Versions

Every push creates a `skill_version` with a server-side auto-incrementing `revision` (always present, orders history) and the author's optional frontmatter `version` string (preserved, displayed when present — never invented). Sync compares content hashes, not version numbers. The whole-skill `content_hash` is the sync unit (hash of sorted per-file hashes).

### Schema (final for MVP)

Portability: runs identically on SQLite and Postgres. Enums are `VARCHAR + CHECK` (SQLAlchemy `Enum(native_enum=False)`), JSON is SQLAlchemy `JSON` (JSONB variant on PG), timestamps are `DateTime(timezone=True)` (timestamptz on PG, ISO text on SQLite).

```text
USER
  user_id       UUID PK
  username      VARCHAR(64)  NOT NULL UNIQUE
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
  created_on    TIMESTAMPTZ  NOT NULL
  created_by    FK → USER    NOT NULL

SKILL_VERSION                                  -- immutable; a change is a new revision
  skill_version_id  UUID PK
  skill_id          FK → SKILL   NOT NULL
  revision          INTEGER      NOT NULL      -- server-assigned: 1, 2, 3…
  version           VARCHAR(32)  NULL          -- author's frontmatter version, verbatim
  content_hash      VARCHAR(64)  NOT NULL      -- sha256 over sorted (path, file-sha256) pairs
  frontmatter_json  JSON         NOT NULL      -- parsed frontmatter incl. unknown fields;
                                               -- queryable convenience ONLY — SKILL.md in
                                               -- SKILL_FILE is verbatim truth, never regenerate
  created_on        TIMESTAMPTZ  NOT NULL
  created_by        FK → USER    NOT NULL
  UNIQUE (skill_id, revision)

SKILL_FILE
  skill_file_id     UUID PK
  skill_version_id  FK → SKILL_VERSION NOT NULL ON DELETE CASCADE
  path              VARCHAR(255) NOT NULL      -- relative; no leading "/", no "..", no "\"
  content           TEXT         NOT NULL      -- UTF-8 only; binary rejected at push
  sha256            VARCHAR(64)  NOT NULL
  executable        BOOLEAN      NOT NULL DEFAULT FALSE  -- preserves +x for scripts
  UNIQUE (skill_version_id, path)

MACHINE_SKILL                                  -- desired state per machine (ADR-0004)
  machine_skill_id  UUID PK
  machine_id        FK → MACHINE NOT NULL ON DELETE CASCADE
  skill_id          FK → SKILL   NOT NULL
  enabled           BOOLEAN      NOT NULL DEFAULT TRUE
  created_on        TIMESTAMPTZ  NOT NULL
  updated_on        TIMESTAMPTZ  NOT NULL
  UNIQUE (machine_id, skill_id)
```

Behavior summary: install = upsert MACHINE_SKILL enabled=true + materialize latest revision locally; remove = enabled=false + delete local folder. Enabled skills always resolve to the latest revision (no pinning). Sync is explicit, compares local hashes against `content_hash`, and never overwrites local modifications silently. AIStack-managed installs are global per machine; no project-scoped installs, no background updates, no upstream GitHub polling.

### Explicitly not in the MVP

No dashboard, no FastAPI, no CLI/daemon, no archive/delete, no version pinning (always latest), no project-scoped sync (global directory only), no rules/hooks/agents/MCP gateway/profiles, no workspaces beyond the single implicit one, no OAuth/passwords, no binary files, no harness besides Claude Code. Anything needing many typed parameters waits for the dashboard — chat must stay low-friction.

### Proof of the MVP

Push `wizard` and `domain-modeling` (both multi-file: a script, reference files) from machine A. Install on machine B via chat. Verify:

1. `diff -r` between source and installed copy is clean;
2. the script's executable bit survives the round trip;
3. one real run of each skill behaves identically to a native install.

## 5. Post-MVP roadmap (decided order of interest, not committed)

1. **Dashboard** — FastAPI joins the stack; login sessions on top of tokens; per-machine enable toggles in a UI; version pinning (pick a revision per machine); archive skills (hidden from vault, versions retained) and delete-archived (permanent); GitHub-link skill import; display names rendered from skill names.
2. **Rules** — the second resource type. Canonical rules projected into `CLAUDE.md` / `AGENTS.md` / `.cursor/rules/` by adapters.
3. **Second harness** — Codex is the likely candidate; adapters translate canonical resources into native form.
4. **Background sync** — opportunistic (check on any MCP call) vs daemon; compare cost after the MVP. Daemon is the industry standard and preferred if costs are similar.
5. **Hooks, agents** — same adapter approach; harness support varies.
6. **MCP gateway** — one AIStack MCP endpoint proxying enabled remote MCPs (GitHub, Linear, ...) with central auth/policy; local MCPs configured by a local component. This is the established gateway/virtual-server pattern and a major differentiator, but it comes after sync works.
7. **Profiles** — named bundles ("Backend Developer") assigning many resources at once.
8. **Workspaces/projects as real scoping** — precedence chain (workspace → project → user → machine → harness) computing an effective configuration. The full model from the original design; only build it when team demand makes the single-vault model insufficient.
9. **Project-scoped sync** — per-project desired state (nullable scope/path on machine_skills) once projects become a real concept.
10. **Secrets** — never sync plaintext credentials; store references (1Password, Vault, cloud secret stores) if MCP credential management arrives.

## 6. Long-term direction (vision, not design)

The eventual product is the combination: cloud-style source of truth + team/project scoping + machine/harness synchronization + native resource adapters + remote MCP gateway + central auth/policy. Harnesses beyond Claude Code and Codex (Cursor, Pi, Hermes, Qwen Code, OpenCode, Gemini CLI, Copilot) come via adapters. The skill spec's portable core (`name`, `description`, body, bundled files) is normalized; complete original frontmatter is always preserved so harness-specific fields survive round-trips.

Things deliberately not overbuilt, ever, until demand is proven: a public marketplace, hundreds of integrations, universal conversion of every harness-specific field, command/prompt syncing, billing, collaborative editing, recommendation systems.

## 7. Competitive landscape (why this and not an existing tool)

- **MCP Gateway & Registry** (`agentic-community/mcp-gateway-registry`): gateway + registry + auth + virtual servers. AIStack differentiates on the developer/team synchronization experience across harnesses, machines, and projects — not on being "an MCP gateway".
- **AutoVault**: canonical skills synced into agents; validates the model and the need for a local write path (a cloud service cannot touch local skill directories — in AIStack, the agent itself is that write path).
- **skills-mcp**: skills over MCP with progressive disclosure. Its metadata/body split informed the proxy idea — which we then killed (ADR-0001) because native skills already do progressive disclosure.
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
  mcp/                     # FastMCP server + auth hook
    tools/                 # the six MCP tools (onboarding, skills, sync)
  services/                # business logic: push validation, sync reconciliation,
                           # token issuing — tools stay thin, logic lives here
tests/
```

## 9. Open questions for the next phase

The schema and sync semantics are settled (see §4). What remains is implementation-level:

1. Exact tool input/output shapes (FastMCP schemas) for the six tools. The file manifest is settled (see **Push** above); the rest are not.
2. What machine metadata beyond `name`/`os` ever matters — collect only when a feature needs it.
3. Invite-code lifecycle: rotation, and whether it's env-var or generated at first boot.
4. Token revocation story (regenerate a machine token when a laptop is lost).
