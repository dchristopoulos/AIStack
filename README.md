# AIStack

[![tests](https://github.com/dchristopoulos/AIStack/actions/workflows/tests.yaml/badge.svg)](https://github.com/dchristopoulos/AIStack/actions/workflows/tests.yaml)

One self-hosted vault for your team's AI coding skills. Push a skill from one machine, install it on another, and keep every copy current, all by talking to your coding agent.

```text
"push my wizard skill to aistack"
"what skills does the team have?"
"install code-review"
"sync aistack"
```

Open source, one container, driven entirely from chat through MCP.

## The problem

A team writes a good code-review skill. It gets copied onto five laptops, and within a month there are five versions. A developer with a MacBook and a desktop maintains the same setup twice. Nobody knows what their teammates' agents are running.

AIStack gives the team one server that holds the canonical copy of each skill and remembers which machine wants which. Every machine pulls what it should have.

## How it works

```mermaid
flowchart LR
    subgraph a["Dimitris · MacBook"]
        cca["Claude Code"]
    end
    subgraph b["Maria · Laptop"]
        ccb["Claude Code"]
    end
    subgraph server["AIStack server · one container"]
        tools["7 MCP tools<br/>metadata only"]
        routes["2 transfer routes<br/>signed, 5-minute URLs"]
        vault[("Vault<br/>immutable revisions")]
        desired[("Desired state<br/>per machine")]
    end

    cca -- "MCP · machine token" --> tools
    ccb -- "MCP · machine token" --> tools
    cca -- "tar + curl" --> routes
    ccb -- "curl + tar" --> routes
    tools --- vault
    tools --- desired
    routes --- vault
```

Three ideas carry the design.

**Skills are copied to disk in full and run natively.** After an install there is no runtime dependency on AIStack: if the server is down, every skill still works. Small proxy skills that fetch their instructions on demand were considered and rejected ([ADR-0001](docs/adr/0001-full-sync-over-runtime-proxy.md)).

**The server holds desired state per machine.** Each machine has its own token, so the server knows who you are and which computer you are on. A MacBook and a work laptop can enable different skills, and sync reconciles each one against its own list ([ADR-0004](docs/adr/0004-server-is-source-of-truth-per-machine.md)).

**Metadata travels over MCP; bytes do not.** A tool argument is text the model generates token by token. Sending a 19 KB skill that way takes about a minute and is not exact. So `push_skill` and `get_skill` return a short-lived signed URL, and the agent moves a gzipped tar with `curl` ([ADR-0010](docs/adr/0010-signed-transfer-urls-for-skill-bytes.md)). Measured on localhost with a real 13 KB, three-file skill, `tar` and `curl` included: a push takes about 65 ms and an install about 60 ms.

## Sync never loses your work

Sync acts on its own only when nothing can be lost: a skill you enabled is missing, or your copy is an older revision you never edited. Everything else is a question.

| What sync finds | What it does |
|---|---|
| Enabled here, not on disk | Installs it |
| Enabled here, an older unmodified revision | Updates it, and tells you who pushed the new one |
| Enabled here, edited locally | Asks: restore, push your version, or leave it |
| You removed it earlier, and the folder is back | Asks: bring it back, or delete the folder |
| In the vault and on disk, never chosen on this machine | Asks whether to start managing it |
| On disk, not in the vault | Lists it and offers to push. Never pushes on its own |

It never deletes a file and never changes what a machine has enabled. Every answer that would overwrite your files or discard edits says so first. That rule is one table in [`reconciliation.py`](src/aistack/services/reconciliation.py), with tests that state it as invariants over every row ([ADR-0006](docs/adr/0006-explicit-disable-sync-never-deletes.md)).

## Joining a server

Paste this into Claude Code, with your server's address and the invite code your admin gave you:

```text
Set up AIStack: fetch https://aistack.example.com/setup and follow it.
Invite code: <the invite code>. Call me <your name>.
```

The agent registers this computer, installs the `sync-aistack` skill, and connects Claude Code to the server. Restart Claude Code once when it says so. That restart is the only one: Claude Code reads its server list at startup, and skills installed afterwards load live.

## Using it

Everything is a sentence. These are the ones worth knowing.

| Say | What happens |
|---|---|
| "sync aistack" | Installs and updates what this machine should have, and asks about anything it will not decide for you. Do it when you start work, like `git pull` |
| "what skills does the team have?" | Lists the vault with descriptions |
| "install code-review" | Enables the skill for this machine and installs it. Usable in the same session |
| "push my wizard skill to aistack" | Uploads it. A name the vault already has becomes a new revision; nothing is overwritten |
| "push all my skills to aistack" | The same, in a loop. Unchanged skills create no revision. Only content counts: a `chmod` alone is not a change |
| "remove wizard from this machine" | Disables it here and deletes the local folder. It stays in the vault and on your other machines |
| "add my other computer to aistack" | Returns one command to paste on that computer. No invite code needed |

A revision records who pushed it. That is provenance, not authorship: the vault holds third-party skills too, and AIStack never claims you wrote something you only uploaded.

## Running a server

```bash
docker build -t aistack .
docker run -d --name aistack -p 8000:8000 \
  -e AISTACK_INVITE_CODE="$(openssl rand -base64 24)" \
  -v aistack-data:/data aistack
```

One container, one volume, SQLite inside. Point `DATABASE_URL` at PostgreSQL and the same image uses that instead ([ADR-0002](docs/adr/0002-sqlite-default-postgres-optional.md)).

[**Operating AIStack**](docs/OPERATING.md) covers configuration, reaching the server from other machines, backups, and the admin operations: revoke a machine, recover a locked-out user, rotate the invite code.

## The seven tools

| Tool | What it does |
|---|---|
| `join` | Redeem the team invite code, register your first machine, get its token |
| `add_machine` | Register another computer and return a ready command to paste there |
| `list_skills` | Browse the vault. This is also the search |
| `get_skill` | Enable a skill on this machine and get a signed URL for its files |
| `push_skill` | Get a signed URL to upload a skill to. A repeated name becomes a new revision |
| `sync` | Compare this machine with what it should have, and report what to do |
| `disable_skill` | Stop managing a skill on this machine |

No dashboard, no CLI, no daemon. Anything that would need many typed parameters waits for a dashboard instead of being forced into chat.

## Reading the code

About 3,500 lines of Python and 5,200 of tests. A good order:

1. [`docs/DESIGN.md`](docs/DESIGN.md) for the plan and [`CONTEXT.md`](CONTEXT.md) for the vocabulary the code uses.
2. [`mcp/tools/`](src/aistack/mcp/tools/) — the seven tools. Each is thin: read the caller, open one transaction, call a service.
3. [`mcp/auth/`](src/aistack/mcp/auth/) — two principals, one rule, enforced in one middleware so a new tool is covered by default.
4. [`services/reconciliation.py`](src/aistack/services/reconciliation.py) — the sync policy as a pure table.
5. The push pipeline, which is the trust boundary: [`transfer_ticket.py`](src/aistack/services/transfer_ticket.py) → [`routes/transfer.py`](src/aistack/mcp/routes/transfer.py) → [`skill_archive.py`](src/aistack/services/skill_archive.py) → [`skill_validation.py`](src/aistack/services/skill_validation.py) → [`skill_service.py`](src/aistack/services/skill_service.py).

Things in there that took some care:

- **Untrusted archives.** An uploaded tar is decompressed under a hard ceiling before `tarfile` sees it, read in memory, and never extracted. Links, devices, and sparse files reject the push. Tests build a gzip bomb and a pax-header bomb and assert both are refused, the first in under a second.
- **Paths every filesystem can hold.** A skill pushed from Linux must install on Windows and macOS, so reserved device names, trailing dots, case-only differences, and NFC/NFD twins are rejected at push.
- **YAML without surprises.** Frontmatter is parsed with every scalar kept as a string, so `version: 1.10` is not stored as `1.1`, nothing can construct an object, and an alias bomb is stopped by a node budget.
- **Races proven, not hoped.** Two pushes reading the same latest revision are held at a `threading.Barrier` in the exact window, so the test fails without the unique constraint. It runs against real PostgreSQL in CI.
- **One hash, one implementation.** The server computes the content hash at push from the bytes and at sync from the digests the agent sent. Its test asserts a constant derived with `perl`, `shasum`, and `xxd`.
- **Secrets stay out of logs.** Tokens, the invite code, and transfer URLs never reach a log line or an error. CI greps the container's own output for all three.
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

CI also builds the container and drives it from outside as two machines, across a restart, on both databases.

### How the whole thing was verified

Beyond the tests, the flows were run end to end by fresh agents that were given only what a real client gets: the server's tool descriptions and the `/setup` page. They joined, pushed multi-file skills from one machine, installed them on another, edited, re-pushed, and synced, with a clean `diff -r` between source and installed copy. What they stumbled on became [#24](https://github.com/dchristopoulos/AIStack/issues/24).

Two honest limits. Those agents were not a signed-in Claude Code session, so "a skill is usable in the session that installed it" rests on Claude Code's own live reloading of skills, not on a run of this project. And the executable bit was checked separately, by hand, with the system `tar` and `curl`: a file pushed as `0755` installs as `0755` beside `0644` neighbors, and re-pushing after only a `chmod -x` returns the same revision, marked unchanged.

## How this compares

Checked in October 2026.

| | AIStack | Claude Code's claude.ai sync | Plugin marketplaces | A git repo of skills |
|---|---|---|---|---|
| Publish a skill | A sentence in chat | Upload on claude.ai | A commit | A commit |
| Per-machine choice of skills | Yes | No | No | No |
| Handles local edits | Asks, never overwrites | Overwrites | Replaces on update | Merge conflicts |
| Needs | Your own server | An Anthropic account | Git credentials on every machine | Git everywhere |
| Works beyond Claude Code | Planned next | No | No | Manually |

For one developer on one harness, Claude Code's own sync is the simpler choice, and AIStack does not try to beat it. AIStack is for a team that wants its own vault, publishing from chat, per-machine control, and one source of truth across more than one coding agent, which is why a second harness is the first thing on the roadmap.

## Status and roadmap

The MVP is complete: seven tools, Claude Code, skills.

Deliberately not built yet, in the order they are likely to arrive:

1. **A second harness**, Codex first. The skill format is shared, so the work is mostly a target directory.
2. **A dashboard**: admin operations as buttons, per-machine toggles, version pinning, archive and delete.
3. **Rules**, the second resource type, projected into `CLAUDE.md`, `AGENTS.md`, and `.cursor/rules/`.
4. **Background sync**, then hooks, agents, an MCP gateway, and profiles.

Known limits today: no version pinning (a machine always gets the latest revision), and global skills directory only. One server is one team: personal teams, several teams per user, and groups inside a team are designed ([ADR-0015](docs/adr/0015-teams-and-groups.md)) and not built. A skill is text files only, at most 100 of them, 256 KB each and 1 MiB together, up to 8 folders deep; empty folders are not stored and `.env` files are refused. [`docs/DESIGN.md`](docs/DESIGN.md) §4 lists everything left out and why.

## Documentation

Decisions are written down before code, with the reasoning kept.

- [Design document](docs/DESIGN.md) — scope, tool contracts, flows, push validation, schema, roadmap
- [Operating AIStack](docs/OPERATING.md) — deployment and admin operations
- [Domain glossary](CONTEXT.md) — the vocabulary the code and docs share
- Decision records:
  - [0001 Full local sync instead of runtime proxy skills](docs/adr/0001-full-sync-over-runtime-proxy.md)
  - [0002 SQLite by default, Postgres via DATABASE_URL](docs/adr/0002-sqlite-default-postgres-optional.md)
  - [0003 API tokens with invite-code join, no login system](docs/adr/0003-token-auth-with-invite-code-join.md)
  - [0004 Server-side desired state per machine](docs/adr/0004-server-is-source-of-truth-per-machine.md)
  - [0005 Synchronous SQLAlchemy](docs/adr/0005-synchronous-sqlalchemy.md)
  - [0006 Explicit disable; sync never deletes](docs/adr/0006-explicit-disable-sync-never-deletes.md)
  - [0007 Skill-specific tables; the generic model is deferred](docs/adr/0007-skill-specific-tables-generic-model-deferred.md)
  - [0008 One admin, enforced by a partial unique index](docs/adr/0008-single-admin-partial-index.md)
  - [0009 Length-prefixed canonical content hash](docs/adr/0009-length-prefixed-canonical-content-hash.md)
  - [0010 Skill bytes travel over signed transfer URLs](docs/adr/0010-signed-transfer-urls-for-skill-bytes.md)
  - [0011 The server alone computes the content hash](docs/adr/0011-server-alone-computes-the-content-hash.md)
  - [0012 Sync returns its questions as data](docs/adr/0012-sync-returns-questions-as-data.md)
  - [0013 The MCP endpoint is stateless](docs/adr/0013-stateless-streamable-http.md)
  - [0014 SQLite transactions take the write lock at BEGIN](docs/adr/0014-sqlite-transactions-begin-immediate.md)
  - [0015 Teams hold skills; groups decide who sees them](docs/adr/0015-teams-and-groups.md) (designed, not built)
  - [0016 Schema changes are Alembic migrations, in one transaction](docs/adr/0016-alembic-migrations-in-one-transaction.md)

## Stack

Python 3.13, FastMCP, SQLAlchemy, Alembic, Poetry. SQLite by default, PostgreSQL through `DATABASE_URL`.

## License

MIT. See [LICENSE](LICENSE).
