# Skill-specific tables; the generic resource model is deferred

Status: accepted

The MVP keeps `SKILL`, `SKILL_VERSION`, `SKILL_FILE`, `MACHINE_SKILL` and typed tools (`get_skill`, `push_skill`, `disable_skill`). A generic `RESOURCE` family with a type discriminator, intended to serve rules, agents, hooks, and MCP server definitions from one schema, was designed in full and rejected for now.

Why: the generic model unifies identity while pretending materialization, hashing, validation, conflict resolution, activation, and secrets are uniform across types. They are not. Skills are a directory of files whose installed bytes reproduce the canonical manifest. Rules are projected into shared files (`CLAUDE.md`, `AGENTS.md`, `.cursor/rules/`) by adapters, so the local artifact is generated, not a copy. Hooks are executable and event-bound, and the accepted policy of silently advancing enabled skills to the latest revision would be wrong for them. MCP server definitions are incomplete without credential binding and runtime state, which are not revisioned file contents.

Generic tools would also make chat carry architecture vocabulary — "get a resource, then interpret its type and target" instead of "install wizard" — which fails the maximum-UX bar in DESIGN.md §1 for no user benefit. Generic storage and generic tools are separable, but a generic store behind one typed tool is an abstraction with one implementation, which this project's conventions forbid.

**The deeper coupling is not table names.** The sync contract assumes the local artifact is a byte-identical copy of the canonical manifest, which is what makes "current / stale / locally modified" computable from one hash. A projected rule has at least three hashes (canonical, projected-per-target, observed) and no single inverse, so "push my local version" has no defined meaning. Renaming tables would not fix that; a rule adapter needs its own notion of observed state regardless of how rows are stored.

Rejected alongside it: an unused `resource_type = SKILL` column (permanent noise, and the migration is still required), and a `ResourceService`/materializer interface with one implementation.

**Revisit when either:** a second implemented type demonstrably shares identity, version, and assignment semantics; or profiles/workspace scoping need a real cross-type foreign-key target. The second is the likelier trigger — profiles referencing skills, rules, agents, and hooks across assignment scopes and harness targets multiplies into a join table per combination, and that is when a common identity target earns itself. `MACHINE_SKILL` is the first instance of that multiplication.

**What makes the migration survivable:** the schema is never externally exposed, tools already sit above services, versions are immutable and copy deterministically, and a self-hosted database is small enough for one transactional migration rather than a dual-write period. The likely destination is a generic identity/version/assignment core with *typed* payload models (`SKILL_FILE`, `RULE_DOCUMENT`, hook activation records) — not one uniform payload table. MCP tools may stay typed even after storage goes generic.

**The seam to preserve meanwhile** (costs nothing today): keep the sync reconciliation logic a pure function over `desired ∈ {enabled, disabled, undecided}` and `observed ∈ {absent, current, stale, unknown}`, returning a policy action. It should know nothing about skills, SQLAlchemy, paths, or adapters. Skill-specific code computes those facts; a future adapter computes them differently, and the data-loss policy is reused rather than reimplemented.
