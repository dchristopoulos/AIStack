# AIStack

[![Tests](https://github.com/dchristopoulos/AIStack/actions/workflows/tests.yaml/badge.svg)](https://github.com/dchristopoulos/AIStack/actions/workflows/tests.yaml)
[![PyPI](https://img.shields.io/pypi/v/aistack-mcp)](https://pypi.org/project/aistack-mcp/)
[![Python](https://img.shields.io/badge/python-3.13-blue)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

**A self-hosted control plane for your AI coding agents' skills: back them up, keep every computer in sync, and share them with your team.**

AIStack keeps one private Library of the skills your coding agents use (Claude Code, Codex, and every agent that reads `~/.agents/skills`). It backs up what is on each computer, installs what each one should have, and lets you share skills with a team without a teammate's edit ever landing on your machine unannounced. You manage it from a web dashboard, and your agent reaches the same account over MCP, so everyday actions are one sentence in chat.

Open source, with no hosted service and no telemetry.

![The Library: every skill you keep, where it came from, and which computers have it](docs/images/dashboard-library.png)

## Why

A team writes a good code-review skill. It gets copied onto five laptops, and a month later there are five versions. A developer with a laptop and a desktop maintains the same setup twice. Nobody knows what their teammates' agents are running, and nobody wants a colleague's change to an agent's instructions to arrive without asking.

## Features

- **One private Library per person.** Skills on your computers are backed up automatically and installed on the others; each computer and agent can have its own selection.
- **Sync that never loses work.** Sync acts on its own only when nothing can be lost. A locally edited skill, a removed one, or a teammate's update is a question, never an overwrite.
- **Teams and nested groups.** Share a skill with a team or a group such as `backend/payments`. Groups can be open or private.
- **Updates are offers.** A teammate's new revision is offered with who pushed it; it reaches your computers only when you take it.
- **Web dashboard and MCP.** The dashboard covers everything; thirteen MCP tools cover what is worth saying in chat. Sign-in is a link your agent hands you, with no passwords.
- **Runs where you choose.** On one computer, across your computers through a private GitHub repository or a PostgreSQL database, or as a server for a team.

## Installation

AIStack needs Python 3.13. The recommended installer is [uv](https://docs.astral.sh/uv/getting-started/installation/):

```bash
uv tool install aistack-mcp
```

`pipx install aistack-mcp` works too. The package is named `aistack-mcp` on PyPI; it installs the `aistack` command. To run the latest code from this repository instead, use `uv tool install git+https://github.com/dchristopoulos/AIStack`.

For a team server, use the container image instead (see [Running a server](#running-a-server)).

## Quickstart

### For yourself

Paste this into Claude Code or Codex:

```text
Set up AIStack: run `uvx aistack-mcp setup` and follow what it prints.
```

Setup asks where your Library should live, connects your agent, and installs the `sync-aistack` skill:

| Where the Library lives | Good for | What it takes |
|---|---|---|
| This computer only | Trying it out | Nothing |
| A private GitHub repository | Your own computers | A GitHub sign-in on each; AIStack creates and maintains the repository |
| A PostgreSQL database ([Neon](https://neon.tech), Supabase, or your own) | Your own computers | One connection string pasted on each |
| An AIStack server | Teams | A machine that stays on |

In the first three, your agent starts AIStack itself over stdio and nothing else runs ([ADR-0020](docs/adr/0020-local-mode-and-where-the-library-lives.md)). On another computer, paste the same sentence and pick the same repository or database.

### Joining a team server

Paste this into your agent, with the server's address and an invite code:

```text
Set up AIStack: fetch https://aistack.example.com/setup and follow it.
Invite code: <the invite code>. Call me <your name>.
```

The agent registers the computer and connects itself. Restart it once when it says so. To add another computer later, say "add my other computer to aistack" on one that is already connected.

### Everyday use

| Say | What happens |
|---|---|
| "sync aistack" | Backs up what is new, installs and updates what this computer should have, and asks about the rest |
| "open my aistack dashboard" | Returns a link that opens the dashboard, signed in |
| "what skills do my teams have?" | Lists your skills, then each team's, with who pushed each |
| "install code-review from backend" | Takes the team's copy into your Library and installs it here |
| "share wizard with backend" | Gives the team a copy of your latest revision |
| "remove wizard from this machine" | Disables it here; it stays in your Library and on other computers |

Setup can also add a session-start hook that reminds the agent to sync, so your computers stay current without anyone asking.

### Try the dashboard without an agent

Start a local server from a checkout and fill it with a small demo team:

```bash
git clone https://github.com/dchristopoulos/AIStack && cd AIStack
poetry install
CODE="$(openssl rand -base64 24)"
AISTACK_HOST=127.0.0.1 AISTACK_INVITE_CODE="$CODE" poetry run aistack serve &
poetry run python scripts/demo_seed.py http://127.0.0.1:8000 "$CODE"
```

It prints a one-time sign-in link for each of three demo users.

## Running a server

```bash
openssl rand -base64 24 > invite-code.txt && chmod 600 invite-code.txt
docker run -d --name aistack -p 8000:8000 \
  -e AISTACK_INVITE_CODE="$(cat invite-code.txt)" \
  -v aistack-data:/data ghcr.io/dchristopoulos/aistack:0.1
```

`invite-code.txt` is the server's invite code, which you join with first; keep it.

One container, one volume, one port, with SQLite inside. Set `DATABASE_URL` to use PostgreSQL instead ([ADR-0002](docs/adr/0002-sqlite-default-postgres-optional.md)). The image is built for amd64 and arm64 and published only from commits that passed CI; `0.1` follows the releases of 0.1, and `edge` follows `main`. Upgrading is starting the new image: the server migrates its database at startup in a single transaction ([ADR-0016](docs/adr/0016-alembic-migrations-in-one-transaction.md)).

[Operating AIStack](docs/OPERATING.md) covers configuration, TLS, backups, upgrades, and administrative tasks such as revoking a machine or rotating the invite code.

## How it works

```mermaid
flowchart LR
    subgraph people["A person"]
        browser["Browser"]
        agent["Coding agent<br/>on each machine"]
    end
    subgraph server["AIStack · one process"]
        dash["Dashboard<br/>/app and /api"]
        tools["MCP tools<br/>metadata only"]
        routes["Transfer routes<br/>signed, short-lived URLs"]
        mine[("Library<br/>private, per user")]
        teams[("Teams and groups<br/>shared copies")]
        desired[("Desired state<br/>per machine")]
    end

    browser -- "sign-in link from chat" --> dash
    agent -- "MCP · machine token" --> tools
    agent -- "tar + curl" --> routes
    dash --- mine
    dash --- teams
    tools --- mine
    tools --- desired
    routes --- mine
    mine -- "share" --> teams
    teams -- "take" --> mine
```

- **Skills are copied to disk and run natively.** After an install, nothing depends on AIStack being up ([ADR-0001](docs/adr/0001-full-sync-over-runtime-proxy.md)).
- **The server holds desired state per machine.** Each machine has its own token, so a laptop and a desktop can enable different skills and sync reconciles each against its own list ([ADR-0004](docs/adr/0004-server-is-source-of-truth-per-machine.md)).
- **Metadata travels over MCP; file contents do not.** Tools return a signed, five-minute URL and the agent moves a gzipped tar with `curl` ([ADR-0010](docs/adr/0010-signed-transfer-urls-for-skill-bytes.md)).
- **A machine installs only from its owner's Library.** Team skills are taken into the Library first, so leaving a team never removes anything from a computer ([ADR-0015](docs/adr/0015-teams-and-groups.md)).
- **Sync policy is a pure table.** [`reconciliation.py`](src/aistack/services/reconciliation.py) maps what the server wants and what the disk holds to one action, with invariant tests over every row ([ADR-0006](docs/adr/0006-explicit-disable-sync-never-deletes.md), [ADR-0007](docs/adr/0007-skill-specific-tables-generic-model-deferred.md)).
- **The dashboard is part of the same process.** One HTML file with no build step, served by the Starlette app FastMCP runs on ([ADR-0017](docs/adr/0017-dashboard-in-the-same-process.md)).
- **A GitHub Library is an event log** that every computer replays ([ADR-0025](docs/adr/0025-a-github-library-is-a-log-each-computer-replays.md)).

The code is layered: thin MCP tools, HTTP routes, and dashboard routes call services in `services/`, which own the business logic and run inside one transaction per request. Authorization is a single middleware, so a new tool is covered by default. See [`docs/DESIGN.md`](docs/DESIGN.md) for the full design, and [`docs/adr/`](docs/adr/) for every architecture decision and its reasoning.

### Security

- Uploaded archives are read in memory under a decompression ceiling and never extracted; links, devices, and unsafe paths are rejected, and tests include gzip and pax-header bombs.
- File paths are validated so a skill pushed from Linux installs safely on macOS and Windows (reserved names, case and Unicode-normalization collisions).
- A team, group, or skill you may not see is answered exactly like one that does not exist.
- Machine tokens and invite codes are stored only as SHA-256 hashes and are kept out of logs and error messages; CI greps the container's output for every kind of secret.
- Dashboard sign-in links and session cookies are separate signed tickets, and every state-changing request requires a header a cross-site form cannot send.

Report vulnerabilities privately as described in [SECURITY.md](SECURITY.md).

## MCP tools

| Area | Tool | Purpose |
|---|---|---|
| Connect | `join` | Redeem an invite code and register the first machine |
| | `add_machine` | Register another computer and return its setup command |
| Library | `sync` | Compare a skills folder with the Library and report what to do |
| | `push_skill` | Get a signed URL to back up a skill; a repeated name becomes a new revision |
| | `get_skill` | Enable a skill on this machine and get a signed URL for its files |
| | `list_skills` | Your skills, then every team skill you may see |
| | `disable_skill` | Stop managing a skill on this machine |
| Teams | `share_skill` | Copy your latest revision into a team or group |
| | `list_teams` | Your teams, your role, and their size |
| | `create_team` | Create a team with you as admin |
| | `invite_to_team` | Create a single-use, seven-day invite |
| | `join_team` | Join a team with an invite code |
| Dashboard | `open_dashboard` | Return a link that signs a browser in |

Anything that needs many parameters is a dashboard action rather than a tool.

## Development

The stack is Python 3.13, FastMCP, Starlette, SQLAlchemy 2, Alembic, PyJWT, and Poetry; SQLite by default and PostgreSQL through `DATABASE_URL`. The dashboard is a single HTML file with no front-end build.

```bash
poetry install
poetry run playwright install chromium   # once, for the dashboard tests
poetry run pytest
```

PostgreSQL tests skip without a database. To run them:

```bash
docker compose -f compose.test.yaml up -d
TEST_DATABASE_URL=postgresql+psycopg://aistack:aistack@localhost:5433/aistack_test poetry run pytest
```

Tests against real GitHub are opt-in: `AISTACK_E2E_GITHUB_REPO=<owner>/<scratch-repo> poetry run pytest tests/e2e`.

CI runs the suite on SQLite and PostgreSQL, the dashboard tests in Chromium, Firefox, and WebKit, a Windows job, and a container job that drives the built image as two users across a restart on both databases.

Where to start reading the code:

1. [`docs/DESIGN.md`](docs/DESIGN.md) and the glossary in [`CONTEXT.md`](CONTEXT.md).
2. [`mcp/tools/`](src/aistack/mcp/tools/) and [`mcp/auth/`](src/aistack/mcp/auth/): the tools and the one authorization rule.
3. [`services/visibility.py`](src/aistack/services/visibility.py): who may see what.
4. [`services/reconciliation.py`](src/aistack/services/reconciliation.py) and [`services/sync_service.py`](src/aistack/services/sync_service.py): sync.
5. The upload path: [`routes/transfer.py`](src/aistack/mcp/routes/transfer.py), [`skill_archive.py`](src/aistack/services/skill_archive.py), [`skill_validation.py`](src/aistack/services/skill_validation.py).
6. [`db/migrations/versions/`](src/aistack/db/migrations/versions/): the schema.

## Roadmap

- **Project skills folders:** manage skills inside a repository, not only global folders ([ADR-0026](docs/adr/0026-skills-folders-inside-projects.md)).
- **Rules** as a second resource type, projected into `CLAUDE.md`, `AGENTS.md`, and `.cursor/rules/`.
- **Background sync**, instead of syncing when asked.
- **Dashboard administration:** server administration, version pinning, and revision management.
- Hooks, agents, and profiles.

Current limits: a skill is text files only (at most 100 files, 256 KiB each, 1 MiB in total), a machine always gets the latest revision of your copy, and restarting a server signs browsers out of the dashboard (machines stay connected). [`docs/DESIGN.md`](docs/DESIGN.md) §4 lists what is deliberately out of scope.

## Privacy

AIStack collects nothing and has no hosted service. A server makes no outbound connections, and the dashboard loads nothing from other sites. In local mode AIStack contacts only PyPI (a daily update check, which installs a newer release of the same minor version; `AISTACK_AUTO_UPDATE=off` in the agent's settings for AIStack turns it off), your own GitHub repository, or your own database.

A server stores each user's username and optional full name; their computers, by name and operating system, with a hash of each machine token; the skills they back up and share, with every revision and who pushed it; which skill is enabled in which folder of which computer; and teams, groups, memberships, and invites (as hashes of their codes). Logs record names and ids, never IP addresses, tokens, invite codes, or links. Whoever runs a server is responsible for its users' data, and can remove a user as described in [docs/OPERATING.md](docs/OPERATING.md).

## Contributing

Issues and pull requests are welcome. Before a larger change, open an issue to discuss it.

- Read [`AGENTS.md`](AGENTS.md) for the repository's conventions (layering, transactions, migrations, error handling), [`CONTEXT.md`](CONTEXT.md) for the vocabulary, and the [ADRs](docs/adr/) for decisions already made. Reversing a decision takes a new ADR.
- A schema change is a new Alembic migration in the same commit as the model change, tested on SQLite and PostgreSQL.
- Changes to the dashboard need the browser tests, and should follow [`docs/design-system.md`](docs/design-system.md).
- Keep commits focused, with an imperative subject and a body that explains why.

## License

[MIT](LICENSE)
