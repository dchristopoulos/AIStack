## What this is

AIStack: a self-hosted, open-source control plane for AI dev configuration (skills first; rules, agents, hooks, MCPs later), synced across users, machines, and harnesses via MCP.

## Read before designing or implementing anything

- `docs/DESIGN.md` — the plan: MVP scope, six MCP tools, flows, final DB schema, project structure, roadmap. Where anything conflicts with it, this document wins.
- `CONTEXT.md` — domain glossary. Use these terms exactly; respect the `_Avoid_` lists.
- `docs/adr/` — decisions already made (full sync not proxy, SQLite default, token auth, server-side desired state). Do not relitigate them; write a new ADR to reverse one.

## Tech stack

Python 3.14, Poetry, SQLAlchemy, FastMCP. SQLite by default, Postgres via `DATABASE_URL` (ADR-0002) — code must run identically on both. FastAPI arrives post-MVP with the dashboard; `src/aistack/api/` stays empty until then.

## Structure

Layered layout under `src/aistack/` (see `docs/DESIGN.md` §8): MCP tool handlers in `mcp/tools/` stay thin; business logic goes in `services/`; models in `db/models/`. Put code in its layer even while layers are thin.

## Conventions

- Tests: pytest under `tests/`, mirroring `src/aistack/`.
- Trust boundaries are not optional: validate skill names and file paths at push exactly as the schema in `docs/DESIGN.md` specifies.
- Skill versions are immutable — never update a `SKILL_VERSION` row; a change is a new revision.
- Async all the way down: `create_async_engine`, `async_sessionmaker(expire_on_commit=False)`, `AsyncSession` in services. No lazy loading — pull relationships with `selectinload`.
- The session factory lives in `db/`; `bootstrap/context/` holds the singleton. A tool opens one session per call and passes it down; services never open their own. One MCP call is one transaction.
- Services raise domain exceptions from `commons/exceptions/`; the MCP layer converts them to `ToolError` in one place. Never return an error payload from a tool — at the protocol level it reads as success.
- Error text is agent-facing UX: say what to fix and what was received, not what class was raised.

## Agent skills

### Issue tracker

Issues live in GitHub Issues via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Default five canonical labels (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `CONTEXT.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.
