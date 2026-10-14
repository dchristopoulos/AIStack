# AIStack

[![tests](https://github.com/dchristopoulos/AIStack/actions/workflows/tests.yaml/badge.svg)](https://github.com/dchristopoulos/AIStack/actions/workflows/tests.yaml)

A self-hosted home for your AI coding skills. Every skill on your computers is backed up to a private space of your own and kept current on each machine. From there you share skills with a team, or with a group inside one, and take the ones your teammates shared.

You see and manage all of it on a web dashboard. Your coding agent is connected to the same account over MCP, so the everyday actions are also a sentence in chat.

Open source, one container, no passwords.

![My skills: every skill, and which of your computers has it](docs/images/dashboard-my-skills.jpg)

| A team, with nested groups | Managing groups |
|---|---|
| ![A team's skills by group](docs/images/dashboard-team.jpg) | ![Groups: open or private, and who is in them](docs/images/dashboard-groups.jpg) |

## The problem

A team writes a good code-review skill. It gets copied onto five laptops, and within a month there are five versions. A developer with a MacBook and a desktop maintains the same setup twice. Nobody knows what their teammates' agents are running, and nobody wants a colleague's edit to an agent's instructions landing on their machine unannounced.

## How it is organized

Three places hold skills. Each is more widely seen than the one before.

| Place | Who sees it | How a skill gets there | What installs from it |
|---|---|---|---|
| **My skills** | Only you | Sync backs up what is on your computers, without asking | Your machines, and nothing else |
| **A team** | Its members | A member shares one of their own skills | Nothing directly: you take a copy into My skills |
| **A group** in a team, such as `backend` or `backend/aistack` | Open: whoever sees the group above it. Private: the people added to it | A member of it, or of a group above it, shares into it | The same as a team |

**My skills** is yours alone and mirrors your computers. It is the only place a machine ever installs from, so what runs on your laptop is always your own copy.

**Teams** are created by any user, who becomes the team's admin, and joined with the team's invite code. Every account is also in the server's team, `everyone`. Sharing gives the team its own copy of a skill, with its own history, and every revision says who shared it.

**Groups** sit inside a team like channels, and nest. A private group is seen only by the people added to it. Two roles exist, admin and member; "backend developer" is not a role, it is being in the `backend` group.

Two rules follow from "a machine installs only from My skills":

- **A teammate's change is an offer.** When a team's copy is newer than the one you took, sync tells you who changed it and asks. It never applies the change. A skill is instructions to an agent, and somebody else's edit does not reach your machine until you say yes.
- **Leaving a team takes nothing off your computer.** Neither does being removed from one, or an admin deleting the team's copy. What you took is yours.

The reasoning is in [ADR-0015](docs/adr/0015-teams-and-groups.md).

## How it works

```mermaid
flowchart LR
    subgraph people["A person"]
        browser["Browser"]
        agent["Coding agent<br/>on each machine"]
    end
    subgraph server["AIStack server · one container, one port"]
        dash["Dashboard<br/>/app and /api"]
        tools["13 MCP tools<br/>metadata only"]
        routes["2 transfer routes<br/>signed, 5-minute URLs"]
        mine[("My skills<br/>private, per user")]
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

**The dashboard is the product; MCP is the connector.** Both are the same process and call the same services. The dashboard is one HTML page with no build step, and there are no passwords: you ask your agent to open it and get a link that signs your browser in ([ADR-0017](docs/adr/0017-dashboard-in-the-same-process.md)).

**Skills are copied to disk in full and run natively.** After an install there is no runtime dependency on AIStack: if the server is down, every skill still works ([ADR-0001](docs/adr/0001-full-sync-over-runtime-proxy.md)).

**The server holds desired state per machine.** Each machine has its own token, so the server knows who you are and which computer you are on. A MacBook and a work laptop can enable different skills, and sync reconciles each against its own list ([ADR-0004](docs/adr/0004-server-is-source-of-truth-per-machine.md)).

**Metadata travels over MCP; bytes do not.** A tool argument is text the model generates token by token, which is slow and not exact for a file. So `push_skill` and `get_skill` return a short-lived signed URL, and the agent moves a gzipped tar with `curl` ([ADR-0010](docs/adr/0010-signed-transfer-urls-for-skill-bytes.md)).

## Sync never loses your work

Sync compares one machine with My skills. It acts without asking only when nothing can be lost and nothing is shared.

| What sync finds | What happens |
|---|---|
| Enabled here, not on disk | Installed |
| Enabled here, an older unmodified revision | Updated, and you are told who pushed the new one |
| On disk, not yet in My skills | Backed up to My skills. It is private, so nothing is shared |
| Enabled here, edited locally | You are asked: restore, back up your version, or leave it |
| You removed it earlier, and the folder is still there | You are asked: bring it back, or delete the folder |
| In My skills and on disk, never chosen on this machine | You are asked whether to manage it here |
| A team has a newer revision of a skill you took | Offered, with who pushed it. You decide each time |

Sync itself is read-only: it reports, and the agent acts through other tools. It never deletes a file, never changes what a machine has enabled, and never applies a teammate's change. Every answer that would overwrite your files or discard edits says so first. The policy is one table in [`reconciliation.py`](src/aistack/services/reconciliation.py), with tests that state it as invariants over every row ([ADR-0006](docs/adr/0006-explicit-disable-sync-never-deletes.md)).

## Connecting a computer

Paste this into Claude Code, with your server's address and the invite code its operator gave you:

```text
Set up AIStack: fetch https://aistack.example.com/setup and follow it.
Invite code: <the server's invite code>. Call me <your name>.
```

The agent registers this computer, installs the `sync-aistack` skill, and connects Claude Code to the server. Restart Claude Code once when it says so. That restart is the only one: Claude Code reads its server list at startup, and skills installed afterwards load live.

For a second computer, say "add my other computer to aistack" on one that is already connected. It returns one command to paste there. No invite code is involved.

## Things to say in chat

| Say | What happens |
|---|---|
| "sync aistack" | Backs up what is new on this computer, installs and updates what it should have, and asks about the rest. Do it when you start work, like `git pull` |
| "open my aistack dashboard" | Gives you a link that opens the dashboard, signed in |
| "what skills do my teams have?" | Lists your own skills, then each team's, with who pushed each |
| "install code-review from backend" | Takes the team's copy into My skills and installs it here. Usable in the same session |
| "share wizard with backend" | Gives the team a copy of your latest revision |
| "create a team called backend" | Creates it with you as admin. "Invite someone to backend" returns its invite code |
| "join a team with this code" | Joins the team a teammate's invite code belongs to |
| "remove wizard from this machine" | Disables it here and deletes the local folder. It stays in My skills and on your other machines |

A revision records who pushed it. That is provenance, not authorship: people back up and share third-party skills, and AIStack never claims you wrote something you only uploaded.

Everything else is on the dashboard: which of your computers has which skill, groups and who is in them, members and roles, moving or removing a team's skill, unsubscribing from a group's updates, leaving a team, and removing a skill from My skills.

## Running a server

```bash
docker build -t aistack .
docker run -d --name aistack -p 8000:8000 \
  -e AISTACK_INVITE_CODE="$(openssl rand -base64 24)" \
  -v aistack-data:/data aistack
```

One container, one volume, SQLite inside. The dashboard needs no second service and no extra port. Point `DATABASE_URL` at PostgreSQL and the same image uses that instead ([ADR-0002](docs/adr/0002-sqlite-default-postgres-optional.md)). An upgrade is starting the new image: the server migrates its database at startup, in one transaction ([ADR-0016](docs/adr/0016-alembic-migrations-in-one-transaction.md)).

To look around without setting anything up, fill a fresh server with a small demo team. It prints a dashboard link for each of three people, and everything it creates goes through the same tools and routes a real user's agent and browser use:

```bash
poetry run python scripts/demo_seed.py http://127.0.0.1:8000 "<the invite code>"
```

[**Operating AIStack**](docs/OPERATING.md) covers configuration, reaching the server from other machines, backups, upgrades, and the operator's tasks: revoke a machine, recover a locked-out user, take someone off the server, rotate the invite code.

## The thirteen tools

MCP carries what is worth saying in a sentence. Anything that would need many typed parameters is a dashboard action instead.

| | Tool | What it does |
|---|---|---|
| **Connect** | `join` | Redeem the server's invite code, register your first machine, get its token |
| | `add_machine` | Register another computer and return a ready command to paste there |
| **My skills** | `sync` | Compare this machine with My skills and report what to do. Changes nothing |
| | `push_skill` | Get a signed URL to back a skill up to. A repeated name becomes a new revision |
| | `get_skill` | Enable a skill on this machine and get a signed URL for its files. With a team, take that team's copy first |
| | `list_skills` | Your own skills, then every team skill you may see. This is also the search |
| | `disable_skill` | Stop managing a skill on this machine |
| **Teams** | `share_skill` | Copy your latest revision into a team or a group |
| | `list_teams` | The teams you are in, your role, and their size |
| | `create_team` | Create a team with you as its admin |
| | `invite_to_team` | Make a new invite code for a team you administer. The previous one stops working |
| | `join_team` | Join a team with its invite code |
| **Dashboard** | `open_dashboard` | Return a link that signs a browser in for you |

## Reading the code

About 5,800 lines of Python and 6,900 of tests. A good order:

1. [`docs/DESIGN.md`](docs/DESIGN.md) for the plan and [`CONTEXT.md`](CONTEXT.md) for the vocabulary the code uses.
2. [`mcp/tools/`](src/aistack/mcp/tools/) — the thirteen tools. Each is thin: read the caller, open one transaction, call a service.
3. [`mcp/auth/`](src/aistack/mcp/auth/) — two principals, one rule, enforced in one middleware so a new tool is covered by default.
4. [`services/visibility.py`](src/aistack/services/visibility.py) — who may see what, in one module. Group access is plain code over two queries, and something you may not see answers exactly like something that does not exist.
5. [`services/skill_service.py`](src/aistack/services/skill_service.py) for push, share, and take, and [`services/team_service.py`](src/aistack/services/team_service.py) for team administration, where every function begins by establishing the caller's place in the team.
6. [`services/reconciliation.py`](src/aistack/services/reconciliation.py) — the sync policy as a pure table, and [`services/sync_service.py`](src/aistack/services/sync_service.py), which computes its inputs and the team updates on offer.
7. The push pipeline, which is the trust boundary: [`transfer_ticket.py`](src/aistack/services/transfer_ticket.py) → [`routes/transfer.py`](src/aistack/mcp/routes/transfer.py) → [`skill_archive.py`](src/aistack/services/skill_archive.py) → [`skill_validation.py`](src/aistack/services/skill_validation.py).
8. [`db/schema.py`](src/aistack/db/schema.py) and [`db/migrations/versions/`](src/aistack/db/migrations/versions/) — the schema as migrations. `0002_teams.py` is the one that moved a shared vault into teams without hiding anything from anyone.
9. [`api/dashboard.py`](src/aistack/api/dashboard.py) — the dashboard's sign-in and JSON routes, as thin as the tools, and [`services/dashboard_service.py`](src/aistack/services/dashboard_service.py), which assembles what one user may see.

Things in there that took some care:

- **Untrusted archives.** An uploaded tar is decompressed under a hard ceiling before `tarfile` sees it, read in memory, and never extracted. Links, devices, and sparse files reject the push. Tests build a gzip bomb and a pax-header bomb and assert both are refused.
- **Paths every filesystem can hold.** A skill pushed from Linux must install on Windows and macOS, so reserved device names, trailing dots, case-only differences, and NFC/NFD twins are rejected at push.
- **YAML without surprises.** Frontmatter is parsed with every scalar kept as a string, so `version: 1.10` is not stored as `1.1`, nothing can construct an object, and an alias bomb is stopped by a node budget.
- **Hidden means indistinguishable.** A team you are not in, a private group, and a skill inside one are answered with the same exception and the same sentence as one that does not exist. A test holds a table of what every tool shows an outsider, and fails when a tool is added without a row.
- **Migrations that roll back whole.** Every pending migration runs in one transaction on both databases. On SQLite that took turning foreign keys off around the table rebuild and checking them before commit; a test rebuilds a referenced table with rows in it and fails without that.
- **Races proven, not hoped.** Two pushes reading the same latest revision are held at a `threading.Barrier` in the exact window, so the test fails without the unique constraint. It runs against real PostgreSQL in CI.
- **One hash, one implementation.** The server computes the content hash at push from the bytes and at sync from the digests the agent sent. Its test asserts a constant derived with `perl`, `shasum`, and `xxd`.
- **Secrets stay out of logs.** Machine tokens, both kinds of invite code, transfer URLs, and dashboard links never reach a log line or an error. Tests assert it per flow, and CI greps the container's own output.
- **A dashboard with no passwords.** The sign-in link and the session cookie are signed tickets with different purposes, so neither can stand in for the other, and a request that changes anything must carry a header a cross-site form cannot send.
- **Two databases, one behavior.** Every service and HTTP test runs against SQLite and PostgreSQL. Concurrent writers wait instead of failing on SQLite, which took an explicit `BEGIN IMMEDIATE` ([ADR-0014](docs/adr/0014-sqlite-transactions-begin-immediate.md)).

### Tests

```bash
poetry install
poetry run pytest
```

The PostgreSQL half skips without a database. To run all of it:

```bash
docker compose -f compose.test.yaml up -d
TEST_DATABASE_URL=postgresql+psycopg://aistack:aistack@localhost:5433/aistack_test poetry run pytest
```

CI also builds the container and drives it from outside as two users: one pushes and shares, the other takes the skill and gets the same bytes, across a restart and on both databases.

### How the whole thing was verified

What the repository itself shows:

- The test suite covers each service directly and each flow over real HTTP with real bearer tokens: join, push, install, sync, teams and invite codes, share and take, team updates, and the dashboard from sign-in to an update taken there.
- The upgrade from a single shared vault is tested on a database built at the old schema: afterwards everyone sees what they saw before, and a failed migration leaves the database as it was.
- The dashboard page is driven in a real browser against the real server: sign-in from a link, taking an update, sharing into a nested group, creating and joining a team, what a member is not shown, and a phone-width layout.
- The container job runs the built image, not the source tree.

What it does not show, stated plainly:

- The first release, before teams, was also run end to end by fresh agents that were given only what a real client gets: the tool descriptions and the `/setup` page. That exercise has not been repeated for sharing, taking, team updates, or the dashboard. Those rest on the tests above.
- No test drives a signed-in Claude Code session. "A skill is usable in the session that installed it" rests on Claude Code's own live reloading of skills, not on a run of this project.

## How this compares

Checked in October 2026.

| | AIStack | Claude Code's claude.ai sync | Plugin marketplaces | A git repo of skills |
|---|---|---|---|---|
| Share a skill | A sentence in chat, or a click | Upload on claude.ai | A commit | A commit |
| Per-machine choice of skills | Yes | No | No | No |
| Handles local edits | Asks, never overwrites | Overwrites | Replaces on update | Merge conflicts |
| Needs | Your own server | An Anthropic account | Git credentials on every machine | Git everywhere |
| Works beyond Claude Code | Planned next | No | No | Manually |

For one developer on one harness, Claude Code's own sync is the simpler choice, and AIStack does not try to beat it. AIStack is for people who want their own server, a private space per person with teams and groups on top, per-machine control, and one source of truth across more than one coding agent, which is why a second harness is the first thing on the roadmap.

## Status and roadmap

Built: skills for Claude Code, a private space per user, teams with invite codes, nested groups that are open or private, share and take, team updates as offers, schema migrations, and the dashboard.

Not built, in the order they are likely to arrive:

1. **A second harness**, Codex first. The skill format is shared, so the work is mostly a target directory.
2. **Rules**, the second resource type, projected into `CLAUDE.md`, `AGENTS.md`, and `.cursor/rules/`.
3. **Background sync.** Today nothing happens until you say "sync aistack".
4. **More on the dashboard**: server administration as buttons, version pinning, deleting a single revision.
5. Hooks, agents, an MCP gateway, and profiles.

Deliberately left out ([ADR-0015](docs/adr/0015-teams-and-groups.md)): automatic updates from a team, a permission matrix of roles and groups, and merging. When your copy and the team's have both changed, taking the team's replaces your latest, which stays in your history; nothing is merged line by line.

Known limits today:

- Claude Code only, and its global skills directory only.
- No version pinning: a machine always gets the latest revision of your own copy.
- One machine belongs to one server.
- Restarting the server signs everyone out of the dashboard, because the signing key lives in memory. Machines stay connected.
- Server administration (revoking a machine, recovering a locked-out user) is a documented script, not a button.
- A skill is text files only, at most 100 of them, 256 KiB each and 1 MiB together, up to 8 folders deep. Empty folders are not stored and `.env` files are refused.

[`docs/DESIGN.md`](docs/DESIGN.md) §4 lists everything left out and why.

## Documentation

Decisions are written down before code, with the reasoning kept.

- [Design document](docs/DESIGN.md) — scope, tool contracts, flows, the sync contract, push validation, teams and groups, the dashboard, schema, roadmap
- [Operating AIStack](docs/OPERATING.md) — deployment, upgrades, and the operator's tasks
- [Domain glossary](CONTEXT.md) — the vocabulary the code and docs share
- [AGENTS.md](AGENTS.md) — the conventions a coding agent follows when working in this repository
- Decision records:
  - [0001 Full local sync instead of runtime proxy skills](docs/adr/0001-full-sync-over-runtime-proxy.md)
  - [0002 SQLite by default, Postgres via DATABASE_URL](docs/adr/0002-sqlite-default-postgres-optional.md)
  - [0003 Personal API tokens with invite-code join, no login system](docs/adr/0003-token-auth-with-invite-code-join.md)
  - [0004 Server-side desired state per machine (reverses stateless sync)](docs/adr/0004-server-is-source-of-truth-per-machine.md)
  - [0005 Synchronous SQLAlchemy, not async](docs/adr/0005-synchronous-sqlalchemy.md)
  - [0006 Explicit disable; sync never deletes; ask only when data can be lost](docs/adr/0006-explicit-disable-sync-never-deletes.md)
  - [0007 Skill-specific tables; the generic resource model is deferred](docs/adr/0007-skill-specific-tables-generic-model-deferred.md)
  - [0008 One admin, enforced by a partial unique index](docs/adr/0008-single-admin-partial-index.md)
  - [0009 Length-prefixed canonical content hash, not JSON](docs/adr/0009-length-prefixed-canonical-content-hash.md)
  - [0010 Skill bytes travel over signed transfer URLs, not through the model](docs/adr/0010-signed-transfer-urls-for-skill-bytes.md)
  - [0011 The server alone computes the canonical content hash](docs/adr/0011-server-alone-computes-the-content-hash.md)
  - [0012 Sync returns its questions as data; the agent asks them in chat](docs/adr/0012-sync-returns-questions-as-data.md)
  - [0013 The MCP endpoint is stateless](docs/adr/0013-stateless-streamable-http.md)
  - [0014 SQLite transactions take the write lock at BEGIN](docs/adr/0014-sqlite-transactions-begin-immediate.md)
  - [0015 A personal space per user, teams to share into, and groups inside a team](docs/adr/0015-teams-and-groups.md)
  - [0016 Schema changes are Alembic migrations, applied at startup in one transaction](docs/adr/0016-alembic-migrations-in-one-transaction.md)
  - [0017 The dashboard is served by the server, and a link from chat signs you in](docs/adr/0017-dashboard-in-the-same-process.md)

## Stack

Python 3.13, FastMCP (and the Starlette application underneath it), SQLAlchemy, Alembic, PyJWT, Poetry. SQLite by default, PostgreSQL through `DATABASE_URL`. No front-end framework and no build step.

## License

MIT. See [LICENSE](LICENSE).
