# AIStack

[![Tests](https://github.com/dchristopoulos/AIStack/actions/workflows/tests.yaml/badge.svg)](https://github.com/dchristopoulos/AIStack/actions/workflows/tests.yaml)
[![PyPI](https://img.shields.io/pypi/v/aistack-mcp)](https://pypi.org/project/aistack-mcp/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

**Your coding agents' skills and rules in one private Library, on every computer and every agent, shared with your team when you choose.**

AIStack is a self-hosted, open-source dashboard for what Claude Code, Codex and other coding agents read: skills, and the rules in `CLAUDE.md`, `AGENTS.md` and their kin. It backs up what is on each computer, installs what each one should have, and shows each project the way your agents see it. Your agent reaches the same account over MCP, so everyday actions are one sentence in chat. No hosted service, no telemetry.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/images/project-dark.png">
  <img alt="A project's page: where it is on each computer, and every rule and skill its agents read, with Claude Code and Codex as columns" src="docs/images/project-light.png">
</picture>

## What it does

- **One private Library.** Skills and rules on your computers are backed up on their own and installed on the others. Sync never deletes, and never overwrites an edit it has not seen: it asks.
- **Organised by project.** Each project has one page: the computers it is on, and everything your agents read there, in the order they read it, with each agent as a column.
- **Rules, not just skills.** Your rules for every project, your private rules for one project, and the repository's own `AGENTS.md` or `CLAUDE.md`. Edit a repository's file on the page and AIStack shares it as a pull request on its own branch.
- **Start an agent with only the skills you pick.** Claude Code or Codex, in one project, for one session, with nothing changed on disk.
- **Teams and groups.** Share a skill with a team or a group such as `backend/payments`. A teammate's change is an offer you take, never something that lands on your computer unasked.
- **Runs where you choose.** On one computer, across your computers through a private GitHub repository or a PostgreSQL database, or as a server for a team.

| | |
|---|---|
| ![Every project: the rules and skills every agent reads everywhere](docs/images/every-project.png) | ![A repository's AGENTS.md in the side panel, with Edit and Commit](docs/images/rule-panel.png) |
| **Every project**: what reaches every project, on every computer | **A rule**: its text, who reads it, Edit and Commit… |
| ![The Start an agent dialog with skills ticked for one session](docs/images/start-an-agent.png) | |
| **Start an agent**: only the skills you tick, for one session | |

## Quick start

### For yourself (local mode)

Paste this into Claude Code or Codex:

```text
Set up AIStack: run `uvx aistack-mcp setup` and follow what it prints.
```

Setup asks where your Library lives (this computer, a private GitHub repository, or a PostgreSQL database such as [Neon](https://neon.tech)), installs AIStack with `uv tool install aistack-mcp`, connects your agent and adds the `sync-aistack` skill. On another computer, paste the same sentence and pick the same place. Then say **"open my aistack dashboard"**.

Nothing else runs: your agent starts AIStack over stdio ([ADR-0020](docs/adr/0020-local-mode-and-where-the-library-lives.md)).

### For a team (a server)

```bash
openssl rand -base64 24 > invite-code.txt && chmod 600 invite-code.txt
docker run -d --name aistack -p 127.0.0.1:8000:8000 \
  --read-only --tmpfs /tmp --cap-drop ALL --security-opt no-new-privileges \
  -e AISTACK_INVITE_CODE="$(cat invite-code.txt)" \
  -v aistack-data:/data ghcr.io/dchristopoulos/aistack:0.1
```

One container, one volume, SQLite inside (set `DATABASE_URL` for PostgreSQL). The port is published on this computer only, for a reverse proxy with TLS or `tailscale serve` in front. Then each person pastes this into their agent:

```text
Set up AIStack: fetch https://aistack.example.com/setup and follow it.
Invite code: <the invite code>. My username is <a short handle like maria>, and my name is <your name>.
```

To add another computer, choose **Add a computer** (the + beside Computers) on the dashboard and run its command there, such as `uvx aistack-mcp join https://aistack.example.com/mcp <computer-code>`. [Operating AIStack](docs/OPERATING.md) covers TLS, backups, upgrades and admin tasks.

### Just look at the page

```bash
git clone https://github.com/dchristopoulos/AIStack && cd AIStack
poetry install
CODE="$(openssl rand -base64 24)"
AISTACK_HOST=127.0.0.1 AISTACK_INVITE_CODE="$CODE" poetry run aistack serve &
poetry run python scripts/demo_seed.py http://127.0.0.1:8000 "$CODE"
```

It prints a sign-in link for each of three demo users, valid for five minutes.

## How it works

```mermaid
flowchart LR
    browser["Dashboard<br/>in your browser"]
    subgraph computer["Each computer"]
        agent["Claude Code, Codex, ..."]
        program["aistack program"]
        files["Skills and rule files<br/>on disk"]
    end
    library[("Your Library<br/>this computer, GitHub,<br/>PostgreSQL or a server")]
    team[("Teams and groups")]

    agent -- "MCP" --> library
    program -- "sync" --> library
    program --> files
    agent -. reads .-> files
    browser --> library
    library -- "share" --> team
    team -- "take" --> library
```

- **Files are copied to disk and read natively.** Once installed, nothing depends on AIStack being up ([ADR-0001](docs/adr/0001-full-sync-over-runtime-proxy.md)).
- **The program on the computer does the disk work**, and it acts on a click from the page only after you confirm in its terminal ([ADR-0035](docs/adr/0035-the-program-does-the-mechanical-work.md), [ADR-0038](docs/adr/0038-the-page-asks-the-program-to-act-on-a-computer.md)).
- **File contents never cross MCP.** Tools return a signed, five-minute URL ([ADR-0010](docs/adr/0010-signed-transfer-urls-for-skill-bytes.md)).
- **A computer installs only from its owner's Library.** A team's skill is taken into the Library first, so leaving a team removes nothing from a computer ([ADR-0015](docs/adr/0015-teams-and-groups.md)).

[`docs/DESIGN.md`](docs/DESIGN.md) is the full design, and [`docs/adr/`](docs/adr/) holds every decision with its reasoning.

## Commands

| Command | What it does |
|---|---|
| `aistack setup` | Prints the setup steps for a coding agent |
| `aistack dashboard` | Opens the dashboard on this computer (local mode) |
| `aistack sync` | Reconciles this computer's skills and rules with its server, in every project it manages (at session start, only the project the session is in; in local mode, say "sync aistack") |
| `aistack start --agent claude-code --skills code-review,tdd` | Starts Claude Code or Codex in this project with only those skills, for one session |
| `aistack project add ~/code/shop` | Adds a project and lists its agent files and other Markdown |
| `aistack join <server> <computer-code>` | Adds this computer to a server |
| `aistack check` | Says whether this computer reaches its Library |
| `aistack link` / `link remove` | Registers or removes the `aistack://` link the dashboard opens a terminal with |
| `aistack move github` | Moves the Library, with its history (also `postgresql`, `here`) |
| `aistack export` | Writes every skill in the Library to a folder |
| `AISTACK_HOST=127.0.0.1 aistack serve` | Runs the server without the container, listening on this computer only |
| `aistack backup <file>` / `restore <file>` | Copies the server's database |
| `aistack admin` | Manages a server's users, computers and teams |

`aistack --help` lists every option. In chat, say "sync aistack", "open my aistack dashboard", "install code-review from backend" or "share wizard with backend".

## Roadmap

- Teams sharing rules, as they share skills today.
- Writing rules for more agents than Claude Code and Codex (their files are already shown).
- Background sync, instead of syncing when asked or at session start.
- Server administration, version pinning and revision management on the dashboard.
- Hooks, agents and MCP server definitions.

Current limits: a skill is text files only (at most 100 files, 256 KiB each, 1 MiB in total), and a rule is at most 64 KiB.

## Security and privacy

AIStack collects nothing. A server makes no outbound connections and the page loads nothing from other sites. Machine tokens and invite codes are stored only as hashes and kept out of logs; uploaded archives are read in memory and never extracted; a team, group or skill you may not see answers exactly like one that does not exist. Report vulnerabilities as described in [SECURITY.md](SECURITY.md).

## Contributing

Issues and pull requests are welcome; open an issue before a larger change.

```bash
poetry install
poetry run playwright install chromium   # once, for the dashboard tests
poetry run pytest -rs
```

Read [`AGENTS.md`](AGENTS.md) for the conventions, [`CONTEXT.md`](CONTEXT.md) for the vocabulary, and [`docs/design-system.md`](docs/design-system.md) before changing the page. The PostgreSQL half of the suite needs `docker compose -f compose.test.yaml up -d` and `TEST_DATABASE_URL=postgresql+psycopg://aistack:aistack@localhost:5433/aistack_test`.

## License

[MIT](LICENSE)
