# AIStack

A cloud control plane for AI development configuration: skills, rules, agents, hooks, and MCP servers, kept in sync across users, projects, machines, and harnesses.

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
Reconciling a machine's actual local state (what's on disk) with its desired state on the server (what's enabled for that machine). Installs the missing, updates the stale, asks the user about local modifications or deletions. See ADR-0004.
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

**Workspace**:
The ownership and collaboration boundary. Every user gets a personal workspace; teams share a team workspace.
_Avoid_: Org, tenant, account

**Machine**:
A registered computer belonging to one user, authenticating with its own permanent token. The unit that enabled skills (and later, local resources) are scoped to.
_Avoid_: Device, host

**Enabled**:
Desired state: this skill should exist on this machine. Set by install ("install X" = enable + materialize), cleared by remove. Sync enforces it.
_Avoid_: Installed (that's actual state on disk), active
