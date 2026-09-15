# AIStack

A self-hosted, open-source control plane for AI development configuration. AIStack keeps skills in sync across users, machines, and harnesses. Rules, agents, hooks, and MCP server definitions are planned after the skills MVP.

## Language

**Harness**:
An AI coding tool that consumes configuration (Claude Code, Codex, Cursor, ...).
_Avoid_: Agent (that means a subagent definition), provider, IDE

**Resource**:
The umbrella term for anything AIStack manages: a skill, rule, agent, hook, or MCP server definition.
_Avoid_: Config item, asset

**Canonical Skill**:
The authoritative skill stored in the AIStack server: frontmatter, instruction body, and any bundled files.
_Avoid_: Remote skill, cloud skill, original, proxy skill (dead concept, see ADR-0001)

**Install**:
A full local copy of a canonical skill, materialized into a harness's skill directory. After install the skill runs natively with no AIStack dependency.
_Avoid_: Clone, stub, proxy

**Sync**:
Reconciling a machine's actual local state (what's on disk) with its desired state on the server (what's enabled for that machine). Installs the missing, updates the stale, asks the user about everything else. Never deletes local files, never flips enabled silently, and is not discovery (that's `list_skills`). See ADR-0004, ADR-0006.
_Avoid_: Pull, update-all

**Name**:
The stable machine-friendly identifier of a canonical skill, taken from its frontmatter `name` (e.g. `unslop`). Used in tool calls and directory names; there is no separate slug or display-name field — pretty rendering is a UI concern.
_Avoid_: Slug, skill id, display name

**Revision**:
The server-side integer that orders a skill's versions. Distinct from the author's optional frontmatter `version` string, which is preserved and shown when present.
_Avoid_: Version number (ambiguous)

**Vault**:
The shared pool of canonical skills on an AIStack server. One copy of each skill; every user installs from the same pool.
_Avoid_: Registry, library, marketplace

**Workspace** _(post-MVP — the term is reserved, the concept does not exist yet)_:
The ownership and collaboration boundary. The MVP has exactly one implicit vault shared by everyone on the server; personal and team workspaces arrive with real scoping (roadmap item 8). Don't write code or docs that assume workspaces today.
_Avoid_: Org, tenant, account

**Machine**:
A registered computer belonging to one user, authenticating with its own permanent token. The unit that enabled skills (and later, local resources) are scoped to.
_Avoid_: Device, host

**Enabled**:
Desired state: this skill should exist on this machine. Set by install ("install X" = enable + materialize), cleared by remove. Sync enforces it. A row with `enabled = false` means explicitly disabled; no row means no decision — the sync contract treats these differently.
_Avoid_: Installed (that's actual state on disk), active

**Pushed by**:
The AIStack user who uploaded a skill or revision into the vault. Pure provenance — it never claims authorship, because the vault holds third-party skills.
_Avoid_: Author, created by, uploaded by

**Origin**:
Optional source URL on a canonical skill (GitHub repo, marketplace page), recorded at push when known. Used to warn when a push to an existing name looks like an unrelated skill sharing the name.
_Avoid_: Upstream, remote

**Orphan**:
A skill on disk that the vault doesn't know. Sync reports orphans and offers to push; it never auto-pushes.
_Avoid_: Untracked skill, local-only skill (as a term of art)

**Adopt**:
Enabling a skill on this machine that already exists both on disk and in the vault, so future revisions flow to it. Always a question, never silent — adoption means future pushes overwrite that folder.
_Avoid_: Auto-enable, link

**Admin**:
The first user to join (`is_admin`). The server can only observe join order, not who deployed it — in practice the operator joins first, alone, before sharing the invite code. In the MVP, admin powers are documented DB operations (revoke a machine, recover a locked-out user); granting admin and admin UI arrive with the dashboard.
_Avoid_: Owner, superuser
