# AIStack

Keep your AI development setup in sync across every developer, machine, and coding agent you use.

Self-hosted. Open source. Driven entirely from chat, through MCP.

> Status: feature one is implemented. The server starts, authenticates bootstrap access, and `join` registers a user and first machine. The remaining MVP tools are planned.

## The problem

Skills, rules, agents, hooks, and MCP servers live in a different place for every tool. Claude Code reads `~/.claude/skills/` and `CLAUDE.md`. Codex wants `AGENTS.md`. Cursor uses `.cursor/rules/`. Each of them keeps its own MCP config.

So a team writing one code-review skill copies it into three tools, on five laptops, and every copy drifts. A developer with a MacBook and a desktop maintains the same setup twice. Nothing is shared, and nobody knows what their teammates are running.

AIStack gives a team one server that holds the canonical copies, and each machine pulls what it needs.

## How it works

The planned MVP runs in one container. Feature one currently runs from source using the commands below. Once the skill tools are implemented, everyone connects their harness to the server and works in plain language:

```text
"push my wizard skill to aistack"
"what skills does the team have?"
"install python-testing"
"sync aistack"
```

Skills are copied to disk in full and run natively afterwards, with no runtime dependency on AIStack. If the server goes down, every skill on your machine still works. The alternative, small proxy skills that fetch their instructions from the server on trigger, costs more tokens and breaks offline, so it was rejected. [ADR-0001](docs/adr/0001-full-sync-over-runtime-proxy.md) has the numbers.

```mermaid
flowchart TD
    subgraph server["AIStack server (self-hosted, one container)"]
        vault["Skill vault<br/>canonical versions + files"]
        desired["Desired state<br/>which skills each machine wants"]
    end

    subgraph mac["Dimitris · MacBook"]
        cc["Claude Code"]
    end

    subgraph pc["Dimitris · Windows PC"]
        cc2["Claude Code"]
    end

    subgraph maria["Maria · Laptop"]
        cc3["Claude Code"]
    end

    cc <-->|"MCP, machine token"| server
    cc2 <-->|"MCP, machine token"| server
    cc3 <-->|"MCP, machine token"| server
```

Each machine authenticates with its own token, so the server knows both who you are and which computer you are on. That is what lets a MacBook and a Windows PC hold different sets of enabled skills.

## MVP

The MVP supports Claude Code and seven MCP tools for skills. Feature one delivers `join`; the other six are planned.

| Tool | What it does |
|---|---|
| `join` | **Implemented.** Redeem the team invite code, register your first machine, get its token |
| `add_machine` | Planned. Register another computer and return a ready MCP command to paste there |
| `list_skills` | Planned. Browse the team vault |
| `get_skill` | Planned. Fetch a skill's files for install and enable it on this machine |
| `push_skill` | Planned. Upload a skill, where a repeated name creates a new revision |
| `sync` | Planned. Compare local state against the server's desired state for this machine |
| `disable_skill` | Planned. Disable a skill for this machine; the harness then removes its local folder |

Sync never overwrites a locally modified skill. It asks whether to restore the vault copy, push your edit as a new revision, or leave it alone.

Deliberately not in the MVP: dashboard, CLI, version pinning, project-scoped installs, rules, hooks, agents, MCP gateway. The roadmap in the design document has the order they arrive in.

## Running it

```bash
cp .env.example .env      # then set AISTACK_INVITE_CODE to a secret of your own
poetry install
poetry run python -m aistack.bootstrap
```

The server refuses to start on the placeholder invite code, and it never prints the one you
set. Share it with your team over something private; each person redeems it once, with `join`.

## Reviewing feature one

Read the current implementation in this order:

1. [`docs/DESIGN.md`](docs/DESIGN.md) and [`CONTEXT.md`](CONTEXT.md) define the seven-tool MVP and its terms.
2. [`src/aistack/mcp/tools/onboarding.py`](src/aistack/mcp/tools/onboarding.py) is the thin `join` tool. It opens one transaction and calls the service.
3. [`src/aistack/services/onboarding_service.py`](src/aistack/services/onboarding_service.py), [`src/aistack/mcp/auth/`](src/aistack/mcp/auth/), and [`src/aistack/db/engine.py`](src/aistack/db/engine.py) contain the join flow, authorization, and database rules.
4. [`tests/services/test_onboarding_service.py`](tests/services/test_onboarding_service.py), [`tests/mcp/`](tests/mcp/), and [`tests/db/`](tests/db/) cover rejection paths, bearer verification, and database behaviour.

The historical [builder notes](docs/reviews/ticket-1.md) and [review](docs/reviews/ticket-1-codex.md) record the baseline findings and their follow-up verification.

### Tests

```bash
poetry run pytest
```

The concurrent-admin tests need real PostgreSQL and skip without it. Setting `TEST_DATABASE_URL`
also runs the service, HTTP, and shared constraint tests against PostgreSQL. To run them:

```bash
docker compose -f compose.test.yaml up -d
TEST_DATABASE_URL=postgresql+psycopg://aistack:aistack@localhost:5433/aistack_test poetry run pytest
```

## Stack

Python 3.13, Poetry, SQLAlchemy, FastMCP. SQLite by default so the whole thing is one container, with Postgres available through `DATABASE_URL` for larger teams ([ADR-0002](docs/adr/0002-sqlite-default-postgres-optional.md)). FastAPI joins later, with the dashboard.

## Documentation

Design decisions are written down before code, and the reasoning is kept.

- [Design document](docs/DESIGN.md), MVP scope, tool contracts, flows, database schema, roadmap
- [Domain glossary](CONTEXT.md), the vocabulary the code and docs both use
- Decision records:
  - [0001 Full local sync instead of runtime proxy skills](docs/adr/0001-full-sync-over-runtime-proxy.md)
  - [0002 SQLite by default, Postgres via DATABASE_URL](docs/adr/0002-sqlite-default-postgres-optional.md)
  - [0003 API tokens with invite-code join, no login system](docs/adr/0003-token-auth-with-invite-code-join.md)
  - [0004 Server-side desired state per machine](docs/adr/0004-server-is-source-of-truth-per-machine.md)

## License

MIT. See [LICENSE](LICENSE).
