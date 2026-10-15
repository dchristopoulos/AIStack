# AIStack

[![tests](https://github.com/dchristopoulos/AIStack/actions/workflows/tests.yaml/badge.svg)](https://github.com/dchristopoulos/AIStack/actions/workflows/tests.yaml)

A self-hosted home for your AI coding skills. Every skill on your computers is backed up to a private space of your own and kept current on each machine. From there you share skills with a team, or with a group inside one, and take the ones your teammates shared.

You see and manage all of it on a web dashboard. Your coding agent is connected to the same account over MCP, so the everyday actions are also a sentence in chat.

Open source and free, with no hosted service: it runs on your own computers, and you choose where your Library lives.

## Where your Library lives

| Choice | What it costs you | For |
|---|---|---|
| **Only this computer** | Nothing to set up. No other computer reaches it | Trying it out, or one computer |
| **A private GitHub repository** | Your own GitHub login on each computer, through the `gh` command. Nothing to keep switched on, nothing pauses, and every change is in the repository's history ([ADR-0025](docs/adr/0025-a-github-library-is-a-log-each-computer-replays.md)) | Your laptop and your desktop |
| **A free PostgreSQL database** ([Neon](https://neon.tech) recommended; Supabase works) | A free account and one address pasted on each computer. Nothing to keep switched on. Supabase pauses after about a week unused | Your laptop and your desktop |
| **A computer that stays on**, running the AIStack server | Free on a computer you own, but it must stay on (or a few dollars a month on a host) | Teams, and the only choice that works for one |

For the first three, your coding agent starts AIStack itself and nothing runs in between ([ADR-0020](docs/adr/0020-local-mode-and-where-the-library-lives.md)). Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then paste this into Claude Code or Codex:

```text
Set up AIStack: run `uvx aistack-mcp setup` and follow what it prints.
```

It asks which choice you want, creates the private repository with `gh` or walks you through creating the Neon database, connects your agent, and installs the `sync-aistack` skill. On another computer, paste the same and choose the same repository or database. If a laptop is lost, revoke GitHub CLI under Settings → Applications on github.com and sign in again on the others with `gh auth login`, or reset the database password and paste the new address on the others ([ADR-0023](docs/adr/0023-every-computer-keeps-the-database-address.md)). "Open my aistack dashboard" opens your Library in the browser, on that computer only, as it does on a server.

For a team, run a server and connect each computer to it: see [Connecting a computer to a server](#connecting-a-computer-to-a-server).

To move your own Library onto a team's server later, run `aistack-mcp export` on a computer that has it. It writes every skill in the Library, at its latest revision, to `./aistack-library`, with each skill's files checked against the hash recorded when they were pushed. Then connect that computer to the server, copy the skill folders you want into `~/.claude/skills`, and say "sync aistack": sync backs up whatever the new Library lacks, without asking. Revision history and which computer had which skill stay behind.

## Try it in two minutes

No coding agent and no Docker needed to look around. This starts a server on your machine and fills it with a small demo team:

```bash
git clone https://github.com/dchristopoulos/AIStack && cd AIStack
poetry install
AISTACK_INVITE_CODE=try-it-out-locally-1234 poetry run aistack serve &
poetry run python scripts/demo_seed.py http://127.0.0.1:8000 try-it-out-locally-1234
```

It prints a sign-in link for each of three people: an admin, a member with an update waiting, and a member who is kept out of a private group. Open one. Everything the script created went through the same tools and routes a real user's agent and browser use.

## What it looks like

![The Library: every skill you keep, where it came from, and which computers have it](docs/images/dashboard-library.png)

| One computer's coding agent | A team, with nested groups |
|---|---|
| ![What Claude Code on one computer has, with Add skills and Copy from](docs/images/dashboard-computer.png) | ![A team's skills by group](docs/images/dashboard-team.png) |
| **Managing groups** | **An update a teammate pushed, offered and not applied** |
| ![Groups: open or private, and who is in them](docs/images/dashboard-groups.png) | ![An update waiting in the Library, in dark mode](docs/images/dashboard-update-dark.png) |

## The problem

A team writes a good code-review skill. It gets copied onto five laptops, and within a month there are five versions. A developer with a MacBook and a desktop maintains the same setup twice. Nobody knows what their teammates' agents are running, and nobody wants a colleague's edit to an agent's instructions landing on their machine unannounced.

## How it is organized

Three places hold skills. Each is more widely seen than the one before.

| Place | Who sees it | How a skill gets there | What installs from it |
|---|---|---|---|
| **Library** | Only you | Sync backs up what is on your computers, without asking | Your machines, and nothing else |
| **A team** | Its members | A member shares one of their own skills | Nothing directly: you take a copy into the Library |
| **A group** in a team, such as `backend` or `backend/aistack` | Open: whoever sees the group above it. Private: the people added to it | A member of it, or of a group above it, shares into it | The same as a team |

**The Library** is yours alone and mirrors your computers. It is the only place a machine ever installs from, so what runs on your laptop is always your own copy.

**Teams** are created by any user, who becomes the team's admin, and joined with the team's invite code. A team's invite link also creates the account of someone new to the server. Sharing gives the team its own copy of a skill, with its own history, and every revision says who shared it.

**Groups** sit inside a team like channels, and nest. A private group is seen only by the people added to it. Two roles exist, admin and member; "backend developer" is not a role, it is being in the `backend` group.

Two rules follow from "a machine installs only from the Library":

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

**The dashboard is the product; MCP is the connector.** Both are the same process and call the same services. The dashboard is one HTML page with no build step, and there are no passwords: you ask your agent to open it and get a link that signs your browser in ([ADR-0017](docs/adr/0017-dashboard-in-the-same-process.md)).

**Skills are copied to disk in full and run natively.** After an install there is no runtime dependency on AIStack: if the server is down, every skill still works ([ADR-0001](docs/adr/0001-full-sync-over-runtime-proxy.md)).

**The server holds desired state per machine.** Each machine has its own token, so the server knows who you are and which computer you are on. A MacBook and a work laptop can enable different skills, and sync reconciles each against its own list ([ADR-0004](docs/adr/0004-server-is-source-of-truth-per-machine.md)).

**Metadata travels over MCP; bytes do not.** A tool argument is text the model generates token by token, which is slow and not exact for a file. So `push_skill` and `get_skill` return a short-lived signed URL, and the agent moves a gzipped tar with `curl` ([ADR-0010](docs/adr/0010-signed-transfer-urls-for-skill-bytes.md)).

## Sync never loses your work

Sync compares one machine with the Library. It acts without asking only when nothing can be lost and nothing is shared.

| What sync finds | What happens |
|---|---|
| Enabled here, not on disk | Installed |
| Enabled here, an older unmodified revision | Updated, and you are told who pushed the new one |
| On disk, not yet in the Library | Backed up to the Library. It is private, so nothing is shared |
| Enabled here, edited locally | You are asked: restore, back up your version, or leave it |
| You removed it earlier, and the folder is still there | You are asked: bring it back, or delete the folder |
| In the Library and on disk, never chosen on this machine | You are asked whether to manage it here |
| A team has a newer revision of a skill you took | Offered, with who pushed it. You decide each time |

Sync itself only reports, and the agent acts through other tools; the one thing it records is when each folder last synced. It never deletes a file, never changes what a machine has enabled, and never applies a teammate's change. Every answer that would overwrite your files or discard edits says so first. The policy is one table in [`reconciliation.py`](src/aistack/services/reconciliation.py), with tests that state it as invariants over every row ([ADR-0006](docs/adr/0006-explicit-disable-sync-never-deletes.md)).

## Connecting a computer to a server

Paste this into Claude Code or Codex, with your server's address and an invite code: the one its operator gave you, or a team's, which also puts you in that team:

```text
Set up AIStack: fetch https://aistack.example.com/setup and follow it.
Invite code: <the invite code>. Call me <your name>.
```

The agent registers this computer, installs the `sync-aistack` skill, and connects itself to the server. Restart it once when it says so. That restart is the only one: the agent reads its server list at startup, and skills installed afterwards load live.

One connected agent is enough for the whole computer. Sync keeps Claude Code's skills folder and the shared `~/.agents/skills` folder in line, and that shared folder is what Codex, Gemini CLI, Kimi Code, Cursor, Copilot CLI, opencode, and Amp read. The first time, it asks once whether both folders should hold the same skills ([ADR-0021](docs/adr/0021-one-agent-syncs-every-folder.md)). Setup also offers to sync at the start of every session: a `SessionStart` hook that only reminds the agent to run `sync-aistack`, so your computers stay current without anyone asking.

For a second computer, say "add my other computer to aistack" on one that is already connected. It returns one command to paste there. No invite code is involved.

## Things to say in chat

| Say | What happens |
|---|---|
| "sync aistack" | Backs up what is new on this computer, installs and updates what it should have, and asks about the rest. Do it when you start work, like `git pull`, or let the session-start hook ask for it |
| "open my aistack dashboard" | Gives you a link that opens the dashboard, signed in |
| "what skills do my teams have?" | Lists your own skills, then each team's, with who pushed each |
| "install code-review from backend" | Takes the team's copy into the Library and installs it here. Usable in the same session |
| "share wizard with backend" | Gives the team a copy of your latest revision |
| "create a team called backend" | Creates it with you as admin. "Invite someone to backend" returns its invite code |
| "join a team with this code" | Joins the team a teammate's invite code belongs to |
| "remove wizard from this machine" | Disables it here and deletes the local folder. It stays in the Library and on your other machines |

A revision records who pushed it. That is provenance, not authorship: people back up and share third-party skills, and AIStack never claims you wrote something you only uploaded.

Everything else is on the dashboard: which of your computers has which skill, groups and who is in them, members and roles, moving or removing a team's skill, unsubscribing from a group's updates, leaving a team, and removing a skill from the Library.

## Running a server

```bash
docker run -d --name aistack -p 8000:8000 \
  -e AISTACK_INVITE_CODE="$(openssl rand -base64 24)" \
  -v aistack-data:/data ghcr.io/dchristopoulos/aistack:latest
```

The image is published from every commit on `main` that passed the tests, for Intel and ARM machines; `docker build -t aistack .` builds the same thing from a checkout. One container, one volume, SQLite inside. The dashboard needs no second service and no extra port. Point `DATABASE_URL` at PostgreSQL and the same image uses that instead ([ADR-0002](docs/adr/0002-sqlite-default-postgres-optional.md)). An upgrade is starting the new image: the server migrates its database at startup, in one transaction ([ADR-0016](docs/adr/0016-alembic-migrations-in-one-transaction.md)).

To look around without setting anything up, fill a fresh server with a small demo team. It prints a dashboard link for each of three people, and everything it creates goes through the same tools and routes a real user's agent and browser use:

```bash
poetry run python scripts/demo_seed.py http://127.0.0.1:8000 "<the invite code>"
```

The screenshots in this README are retaken the same way, from a fresh server, by `scripts/retake_screenshots.py`.

[**Operating AIStack**](docs/OPERATING.md) covers configuration, reaching the server from other machines, backups, upgrades, and the operator's tasks: revoke a machine, recover a locked-out user, take someone off the server, rotate the invite code.

## The thirteen tools

MCP carries what is worth saying in a sentence. Anything that would need many typed parameters is a dashboard action instead.

| | Tool | What it does |
|---|---|---|
| **Connect** | `join` | Redeem the server's or a team's invite code, register your first machine, get its token |
| | `add_machine` | Register another computer and return what to paste there, for Claude Code or Codex |
| **Library** | `sync` | Compare one skills folder on this machine with the Library and report what to do. Changes no skill and no decision |
| | `push_skill` | Get a signed URL to back a skill up to. A repeated name becomes a new revision |
| | `get_skill` | Enable a skill on this machine and get a signed URL for its files. With a team, take that team's copy first |
| | `list_skills` | Your own skills, then every team skill you may see. This is also the search |
| | `disable_skill` | Stop managing a skill on this machine |
| **Teams** | `share_skill` | Copy your latest revision into a team or a group |
| | `list_teams` | The teams you are in, your role, and their size |
| | `create_team` | Create a team with you as its admin |
| | `invite_to_team` | Make an invite link for a team. It lets in one person, creating their account if they are new, and lasts seven days. Cancel one in the dashboard |
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
- The dashboard page is driven in a real browser against the real server: sign-in from a link, taking an update, sharing into a nested group, creating and joining a team, what a member is not shown, and a phone-width layout. The same tests run in Chromium, Firefox, and WebKit.
- The container job runs the built image, not the source tree.

What it does not show, stated plainly:

- The first release, before teams, was also run end to end by fresh agents that were given only what a real client gets: the tool descriptions and the `/setup` page. That exercise has not been repeated for sharing, taking, team updates, or the dashboard. Those rest on the tests above.
- A signed-in Claude Code session was run once by hand against a local server (2026-10-14): it listed a team's skills over MCP, installed one with the tool's own `curl` and `tar` steps, executable bit intact, and used it in the same session without a restart. The first attempt to use the skill straight after installing it answered "Unknown skill"; a moment later it was found. No automated test repeats this.
- The session-start hook was checked in a headless Claude Code session (2026-10-14): its line reached the model's context at startup.
- A whole sync was run once from a signed-in Claude Code session (2026-10-14, Claude Code 2.1.241, headless, against a local server). The computer's skills folder held 25 real skills and the server was arranged so one sync met every part of the report. Told only "sync aistack", and given its two answers in advance, the session hashed the folder, called `sync`, and then:

  | The report said | What the session did |
  |---|---|
  | 24 skills already current | Nothing |
  | 1 to install, pushed from another computer and switched on from the dashboard | Installed it, executable bit intact |
  | 1 to update, an untouched older revision | Replaced it with revision 2 |
  | 2 on disk and not yet in the Library | Backed both up without asking |
  | 1 edited locally | Left it alone, as answered, and said the edits exist only on that computer |
  | 1 update offered by a team, pushed by a teammate | Took it, as answered, and named who pushed it |

  A second sync straight afterwards reported nothing to do except the edited skill, which it asks about again. It took 14 turns, about three minutes, and $0.95. One thing went wrong on the way: the session wrote its install commands with shell variables in an `rm`, Claude Code refused that as unsafe, and the session rewrote them with plain paths and carried on. The folders the run added were removed afterwards and the skills folder was checked to be file for file what it had been. This is one run with one model, and no automated test repeats it.
- A sync was run once from Codex (2026-10-15, Codex CLI 0.162 from the ChatGPT app, `codex exec`, against a local server). It was connected the way setup connects it, with an `[mcp_servers.aistack]` block in `~/.codex/config.toml` that `codex mcp get aistack` listed. Its `~/.agents/skills` held `sync-aistack` and one skill the Library did not have, and the Library held one skill switched on for that folder but missing from it. Told only "sync aistack", Codex loaded `sync-aistack`, synced only the agents folder because there was no `~/.claude`, hashed it, called `sync`, backed up the new skill without asking, and installed the missing one byte for byte. Three things got in the way, all from Codex's own safeguards and not from AIStack:
  - Non-interactive `codex exec` refuses an MCP tool that needs approval, so the run set `default_tools_approval_mode = "approve"` for the aistack server on the command line. Setup now writes `approval_mode = "approve"` for `sync`, `get_skill`, and `push_skill` only, so sync runs without a prompt and every other AIStack tool still asks. Codex 0.162 was checked to read those lines; a sync was not run again with them.
  - Codex's `workspace-write` sandbox keeps `.agents` read-only, so the first install failed and Codex said so. The upload still went through. The install succeeded once the run was given write access, which stands in for the user approving the write. Setup leaves that approval in place: declaring `~/.agents/skills` a writable root would let every Codex session, in any repository, change the skills every agent on the computer loads.
  - The `codex` 0.146 on the PATH rejected the model configured in that file, so the run used the CLI the ChatGPT app ships.

  The skills folder was a scratch home directory, and the config file was restored from a backup afterwards. This is one run with one model, and no automated test repeats it.
- Local mode was run once by hand (2026-10-15, Claude Code 2.1.241, headless). Two scratch home folders stood in for a laptop and a desktop, each starting the built package with `uvx --from <wheel> aistack-mcp` over stdio, and both pointed at one SQLite Library. Told "sync aistack", the laptop's session backed up its one skill. Asked what was in the Library and to install it, the desktop's session listed it, synced, and installed it byte for byte with its executable bit, in six turns. No server ran at any point. This is one run with one model; `tests/mcp/test_local_mode.py` repeats the same flow without an agent.
- Local setup was run once by hand (2026-10-15) in a scratch home folder, against the built package and a PostgreSQL address pasted as `postgresql://`. Each step of `aistack setup` worked as written: the start check stayed silent on success and printed one sentence for a wrong password. Claude Code 2.1.241, headless and connected with setup's own command, was then told "sync aistack". It loaded the local `sync-aistack` skill, synced both folders, backed up the one skill on disk, and asked the first-sync question about using the same skills in both folders. Setup's `claude mcp add` itself was not run, because it would have changed the real Claude Code configuration.
- A sync was run from Codex in local mode (2026-10-15, Codex CLI 0.162 from the ChatGPT app, `codex exec`). It was connected with setup's Codex settings given on the command line, with a scratch home folder and the built package. Told "sync aistack", it loaded the local `sync-aistack` skill and backed up the one skill in `~/.agents/skills`. With that folder deleted, a second sync installed it again, byte for byte. AIStack wrote the folder itself, so Codex's sandbox had nothing to approve. The first attempt found no server: AIStack's first start downloaded its packages for longer than Codex waits, which is why setup runs AIStack once before connecting the agent, and why its Codex settings now allow a minute.
- Every chat request a person makes was run against a server from source (2026-10-15), once in headless Claude Code 2.1.241 and once in `codex exec` (Codex CLI 0.162 from the ChatGPT app), each in a scratch home folder, connected as a seeded user with a machine token and nothing else. The phrases were "sync aistack" (with a new skill, an edited one, and an older revision on disk), "what skills do my teams have?", "install release-notes from aistack", "share pr-description with aistack", "remove … from this machine", "create a team called platform and invite someone", and "add my other computer". Both agents did each one. What got in the way, and what changed:
  - Claude Code wrote its install steps as a shell function with `rm -rf "$STAGE/$name"`, which it refuses to run, in every session that installed something. It recovered each time, at the cost of a few turns. `get_skill` now says to run the steps per skill with the paths written out, and the same sync then took 14 turns instead of 20.
  - Asked to add a computer where the user runs Codex, Codex got only a `claude mcp add` command, searched the web, and improvised a setup that needs an environment variable set forever. `add_machine` now also returns the `config.toml` block setup writes, which Codex then showed as it was.
  - Codex left out the team when told "install release-notes from aistack", was refused, and listed every skill to find it. The refusal now names the teams the caller can see that share a skill of that name, so the next call succeeds.
  - Both agents compared a team's revision number with the user's own, which count separately. `list_skills` now says so.

  The sessions ran with their permission checks off, inside a macOS sandbox that denied writes to the real skills folders and agent configuration. This is one run per agent with one model each, and no automated test repeats it.
- A Library was shared through a real private GitHub repository (2026-10-15, Claude Code 2.1.241 headless, the built package through `uvx`, two scratch home folders as a laptop and a desktop, the owner's `gh` login). `aistack check` on each reported the repository. Told "sync aistack", the laptop's session backed up its skill, which put four event files in the repository. Asked what was in the Library and to install it, the desktop's session listed it and installed it byte for byte with its executable bit, in seven turns. The first attempt found two faults, fixed before this run: a clone that timed out left a broken clone that later passed for a working one, so changes were marked shared without being pushed; and git asked the macOS keychain helper Homebrew configures before `gh`, which hung. AIStack now clones into a temporary folder and moves it into place, and gives git `gh`'s login alone for GitHub.

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

Built: skills for Claude Code, Codex, and every agent that reads `~/.agents/skills`, a private space per user, teams with invite codes, nested groups that are open or private, share and take, team updates as offers, schema migrations, and the dashboard.

Not built, in the order they are likely to arrive:

1. **Every agent on a computer on the dashboard**: a page per skills folder, and agents in the Add to… dialog.
2. **Rules**, the second resource type, projected into `CLAUDE.md`, `AGENTS.md`, and `.cursor/rules/`.
3. **Background sync.** Today nothing happens until you say "sync aistack".
4. **More on the dashboard**: server administration as buttons, version pinning, deleting a single revision.
5. Hooks, agents, an MCP gateway, and profiles.

Deliberately left out ([ADR-0015](docs/adr/0015-teams-and-groups.md)): automatic updates from a team, a permission matrix of roles and groups, and merging. When your copy and the team's have both changed, taking the team's replaces your latest, which stays in your history; nothing is merged line by line.

Known limits today:

- Two skills folders: Claude Code's and the shared `~/.agents/skills`. Project folders are not managed.
- "Add my other computer" returns a Claude Code command. A second computer where Codex is the only agent is not connected that way yet.
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
  - [0018 One account for every coding agent on a computer](docs/adr/0018-one-account-for-every-coding-agent.md)
  - [0019 Invites are the way in](docs/adr/0019-invites-are-the-way-in.md)
  - [0021 One connected agent syncs every skills folder on its computer](docs/adr/0021-one-agent-syncs-every-folder.md)

## Stack

Python 3.13, FastMCP (and the Starlette application underneath it), SQLAlchemy, Alembic, PyJWT, Poetry. SQLite by default, PostgreSQL through `DATABASE_URL`. No front-end framework and no build step.

## License

MIT. See [LICENSE](LICENSE).
