# Operating AIStack

For whoever runs the server. Everything here is one container and one volume: the MCP endpoint, the routes that move skill files, and the web dashboard are one process on one port.

## Run it

```bash
docker run -d --name aistack \
  -p 8000:8000 \
  -e AISTACK_INVITE_CODE="$(openssl rand -base64 24)" \
  -v aistack-data:/data \
  --restart unless-stopped \
  ghcr.io/dchristopoulos/aistack:latest
```

The image is published by CI from every commit on `main` that passed the tests, for `linux/amd64` and `linux/arm64`. `latest` follows `main`; each commit is also tagged `sha-<commit>`, and version tags such as `0.1.0` arrive with releases. To build it yourself instead, `docker build -t aistack .` in a checkout and run `aistack` in place of the published name.

Without Docker, the same server runs from PyPI with [uv](https://docs.astral.sh/uv/), which fetches Python 3.13 if it needs to. The database is a SQLite file in the current folder unless `DATABASE_URL` says otherwise:

```bash
AISTACK_INVITE_CODE="$(openssl rand -base64 24)" uvx aistack-mcp serve
```

Or with Compose, which reads `AISTACK_INVITE_CODE` from the environment or a `.env` file:

```bash
AISTACK_INVITE_CODE="$(openssl rand -base64 24)" docker compose up -d
```

Write the invite code down before you run either. You chose it, the server never prints it, and there is no command that shows it afterwards. The startup log says only `Invite code: 'configured'`.

The volume at `/data` holds the SQLite database, which is every user, machine, team, group, skill, and revision. Stopping, removing, and recreating the container keeps all of it as long as the volume stays.

Then join first, alone, before you share the code: the first user to join becomes the server's admin. The README has the one-paste setup. After that, people usually arrive through a team's invite link, which creates their account; your own code is for admitting someone directly.

## Configuration

All of it is environment variables.

| Variable | Default | Meaning |
|---|---|---|
| `AISTACK_INVITE_CODE` | none, required | The shared secret new users join the server with. At least 16 characters. The server refuses to start without one |
| `AISTACK_PUBLIC_URL` | taken from each request | The address clients reach the server at, such as `https://aistack.example.com`. Set it behind a reverse proxy |
| `DATABASE_URL` | `sqlite:////data/aistack.db` | Any `postgresql+psycopg://` URL switches to PostgreSQL |
| `AISTACK_HOST` | `0.0.0.0` | Interface to bind |
| `AISTACK_PORT` | `8000` | Port to listen on |
| `AISTACK_MCP_PATH` | `/mcp` | Path of the MCP endpoint |
| `AISTACK_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL` |

### Why `AISTACK_PUBLIC_URL` matters

The server hands out URLs: the `claude mcp add` command from `add_machine`, the upload and download links that move skill files, and the link that signs a browser in to the dashboard. It builds them from its own address. Reached directly, it reads that address from the request. Behind a proxy that terminates TLS or rewrites the host, the request says `http://aistack:8000` and every URL it hands out is one nobody outside can open. Set the variable to the address people actually type. When it starts with `https://`, the dashboard's session cookie is marked `Secure`.

## Reaching it from other machines

AIStack ships a container and does not solve hosting. Whatever you choose, run **exactly one instance**: the key that signs dashboard links, sessions, and transfer URLs lives in that process's memory, so a second replica behind the same address refuses what the first one signed. Autoscaling platforms (Cloud Run, Azure Container Apps, Fly.io) need their maximum set to one. A platform that stops the container when idle restarts it on the next request, which signs the dashboard out each time.

Two patterns that work:

**A private network (Tailscale, WireGuard, a VPN).** Run the container on any machine in the network and use its private address. Nothing is exposed to the internet, and plain HTTP inside an encrypted tunnel is fine. This is the least work for a solo developer or a small team.

```text
AISTACK_PUBLIC_URL=http://aistack.your-tailnet.ts.net:8000
```

**A VPS behind a reverse proxy with TLS.** Put Caddy, nginx, or Traefik in front, terminate HTTPS there, and forward everything to port 8000. Forward all paths, not only `/mcp`: skill files travel over `/transfer/...`, setup is served from `/setup`, and the dashboard is `/app` and `/api/...`. Do not serve AIStack over plain HTTP on the public internet. Machine tokens, transfer links, dashboard links, and the dashboard's session cookie are bearer credentials, and anyone on the path could read them.

```text
AISTACK_PUBLIC_URL=https://aistack.example.com
```

A minimal Caddyfile:

```text
aistack.example.com {
    reverse_proxy 127.0.0.1:8000
}
```

**For one person** the cheapest dependable setup is the first pattern on a machine you already own that stays on (a desktop, a mini PC, a NAS), with SQLite and `tailscale serve` in front for HTTPS inside your tailnet. It costs nothing and nothing sleeps. A laptop does not work as the host, because it sleeps. Without such a machine, a single Fly.io Machine with a volume for SQLite costs a few dollars a month. [docs/research/free-personal-hosting.md](research/free-personal-hosting.md) compares the free databases and hosts, with sources.

`GET /health` answers `{"status": "ok"}` without a token when the server can reach its database, and 503 when it cannot. The container's own health check uses it.

## The dashboard

The dashboard is where people see their skills and manage teams, groups, and members. It needs nothing from you: it is served by the same process at `/app`, with its JSON API under `/api`, on the same port as everything else. There is no second service, no build step, and nothing to configure.

Nobody has a password. A user says "open my aistack dashboard" to their coding agent and gets a link that signs their browser in. The link works for five minutes and the session it starts lasts eight hours. Without a session, `/app` and `/api/...` answer 401.

The key that signs links and sessions is made at startup and kept in memory. **A restart signs every dashboard user out and voids every link and transfer URL not yet used.** Nothing is lost: a user asks their agent for a new link, and an agent that was mid-transfer calls the tool again. Machine tokens are not affected.

## Teams and invite codes

There are two kinds of invite code, and you manage only one.

- **The server's invite code** is `AISTACK_INVITE_CODE`. It lets a new person create an account on this server. Everyone who joins is in the team `everyone`, which has no code of its own and cannot be left.
- **A team's invite code** starts with `aistinv_`. A team's admin makes one from chat or the dashboard and sends it to someone who already has an account. The server stores only its hash, so there is nothing to read back out of the database. Making a new one stops the old one working.

Users create teams and groups themselves and administer them. Nothing in a team needs the operator.

## Admin operations

No tool and no dashboard page performs the server's own admin operations. These are the ones an operator needs, as short scripts that run inside the container. They use the server's own database setup, so they work the same on SQLite and PostgreSQL.

Save a script to a file, set the names at the top, and run it:

```bash
docker exec -i aistack python - < script.py
```

### List users and machines

```python
from sqlalchemy import text
from aistack.bootstrap.configuration.settings.settings_config import Settings
from aistack.db.engine import build_engine

with build_engine(Settings().database_url).begin() as connection:
    for row in connection.execute(text('''
        SELECT u.username, m.name, m.os, m.created_on
        FROM machine m JOIN "user" u ON u.user_id = m.user_id
        ORDER BY u.username, m.name
    ''')):
        print(*row)
```

### A laptop was lost or stolen: rotate its token

This is the answer to both "revoke the old one" and "let the user back in". The old token stops working on its next request, the machine keeps its name and its enabled skills, and you hand the user the new token.

```python
import hashlib, secrets
from sqlalchemy import text
from aistack.bootstrap.configuration.settings.settings_config import Settings
from aistack.db.engine import build_engine

USERNAME, MACHINE = "maria", "laptop"

token = "aist_" + secrets.token_urlsafe(32)
with build_engine(Settings().database_url).begin() as connection:
    changed = connection.execute(text('''
        UPDATE machine SET token_hash = :token_hash
        WHERE name = :machine
          AND user_id = (SELECT user_id FROM "user" WHERE username = :username)
    '''), {"token_hash": hashlib.sha256(token.encode()).hexdigest(),
           "machine": MACHINE, "username": USERNAME}).rowcount
print(f"Rotated {changed} machine. New token: {token}" if changed else "No such machine.")
```

The user then reconnects the replacement computer with that token:

```bash
claude mcp remove aistack --scope user
claude mcp add --transport http --scope user aistack https://aistack.example.com/mcp \
  --header "Authorization: Bearer <new token>"
```

The token is printed once, in your terminal. Send it to the user over something private.

### A machine is gone for good: delete it

```python
from sqlalchemy import text
from aistack.bootstrap.configuration.settings.settings_config import Settings
from aistack.db.engine import build_engine

USERNAME, MACHINE = "maria", "old-desktop"

with build_engine(Settings().database_url).begin() as connection:
    removed = connection.execute(text('''
        DELETE FROM machine
        WHERE name = :machine
          AND user_id = (SELECT user_id FROM "user" WHERE username = :username)
    '''), {"machine": MACHINE, "username": USERNAME}).rowcount
print(f"Removed {removed} machine.")
```

Its token is rejected from the next request on, and the record of which skills it had enabled goes with it. Do this through the script and not with a bare `sqlite3` shell: SQLite only cascades deletes when a per-connection setting is on, and the server's database setup turns it on.

### A user has no machine left

If their only machine was deleted, they cannot call `add_machine`, and joining again is refused because the username exists. Register a machine for them:

```python
from sqlalchemy import select
from aistack.bootstrap.configuration.settings.settings_config import Settings
from aistack.db.engine import build_engine, build_session_factory
from aistack.db.models.user import User
from aistack.services import onboarding_service

USERNAME, MACHINE, OS = "maria", "new-laptop", "MACOS"   # OS: MACOS, WINDOWS, or LINUX

with build_session_factory(build_engine(Settings().database_url)).begin() as session:
    user = session.scalar(select(User).where(User.username == USERNAME))
    added = onboarding_service.add_machine(session, user.user_id, MACHINE, OS)
print(f"Registered '{MACHINE}' for {USERNAME}. Token: {added.token}")
```

**Never delete a user.** Every skill and revision records who pushed it, and their teams and memberships point at them. Deleting someone either fails or destroys that record, and the record is how a team knows whose instructions their agents are running.

### Someone left: take them off the server

Delete each of their machines with the script above. With no machine they have no token, so they can reach neither the MCP endpoint nor the dashboard, and a dashboard session they still hold ends within eight hours, or at once if you restart. Their account, the skills they shared, and the `pushed_by` on each revision stay. Then rotate the server's invite code, below.

A team's admin removes a person from that team in the dashboard. Leaving the server altogether is this operation.

### List teams and who is in them

Personal teams are left out: each user has one, named after them, and it is their private space.

```python
from sqlalchemy import text
from aistack.bootstrap.configuration.settings.settings_config import Settings
from aistack.db.engine import build_engine

with build_engine(Settings().database_url).begin() as connection:
    for row in connection.execute(text('''
        SELECT t.name, t.kind, u.username, tm.role
        FROM team_member tm
        JOIN team t ON t.team_id = tm.team_id
        JOIN "user" u ON u.user_id = tm.user_id
        WHERE t.kind <> 'PERSONAL'
        ORDER BY t.name, u.username
    ''')):
        print(*row)
```

### Rotate the server's invite code

Change `AISTACK_INVITE_CODE` and restart the container. Everyone who already joined is unaffected: they authenticate with machine tokens, not the code. Rotate it when someone leaves, and whenever it has been shared somewhere less private than you meant. The restart signs dashboard users out, as any restart does.

## Backups

The database is one file in the volume. Copy it while the server runs with SQLite's own backup, which is safe under concurrent writes:

```bash
docker exec aistack python -c "
import sqlite3
source = sqlite3.connect('/data/aistack.db')
target = sqlite3.connect('/data/backup.db')
source.backup(target)
target.close()
"
docker cp aistack:/data/backup.db ./aistack-backup.db
```

A plain `cp` of the file can catch it mid-write. On PostgreSQL, use `pg_dump`.

## PostgreSQL

The same image runs against PostgreSQL. Nothing else changes:

```bash
docker run -d --name aistack -p 8000:8000 \
  -e AISTACK_INVITE_CODE="..." \
  -e DATABASE_URL="postgresql+psycopg://aistack:password@db.internal:5432/aistack" \
  ghcr.io/dchristopoulos/aistack:latest
```

It is the one image either way: there is no separate PostgreSQL build, and the volume is simply unused.

A managed PostgreSQL works, with two settings to get right. On **Supabase**, use the shared pooler in session mode (port 5432); transaction mode (port 6543) does not support the prepared statements psycopg uses. On **Neon**, use the direct endpoint, not the pooled one. Managed databases close idle connections; AIStack checks a pooled connection before using it, so a closed one is replaced rather than failing a request. A database that scales to zero is kept awake by the container's 30-second health check, which on Neon's free plan uses up the month's compute in about 17 days; turn the health check off there (`--no-healthcheck`) and let your platform's own check call `/health` less often.

SQLite is the default because one container is easier to run than two, and the write volume of people pushing skills is tiny. Move to PostgreSQL when you already run one and want AIStack's data with the rest of yours, not for performance. The test suite runs every service and HTTP test against both.

## Upgrading

Back up, then pull the new image (`docker pull ghcr.io/dchristopoulos/aistack:latest`, or rebuild a checkout) and recreate the container. At startup the server brings the database to the schema its release expects, before it accepts a request. Every pending change is applied in one transaction: either all of it lands or the database is exactly as it was.

If an upgrade fails, the server does not start and the log says which step failed. Nothing has been changed, so starting the previous image again is safe. A database created before this mechanism existed is recognized and carried forward without a manual step.

### The upgrade that introduces teams

Before it, a server was one vault everybody shared and installed from. The upgrade moves the data so that nothing anyone could see disappears and no computer loses a skill:

- Every existing skill moves into the server's team, `everyone`, and every user is a member. The server's admin is that team's admin.
- Every user gets a private space of their own, the Library.
- Every skill that one of a user's machines had enabled or disabled is copied, with its whole history, into that user's own space, and the machine follows the copy. Each copy remembers the `everyone` skill it came from.

The database grows by those copies. Skills are small text files, so this is rarely worth planning for, but it is why the upgrade takes longer than a later one will.

What changes for your users, and is worth telling them before you upgrade:

- A machine installs only from its user's own space. A push lands there and nobody else sees it. Putting a skill in front of others is a separate step: "share <skill> with everyone", or with a team they created.
- Sync backs up the skills it finds on a computer to that private space without asking.
- A change someone else makes to a shared skill no longer arrives by itself. Sync reports it as an offer and the user accepts or declines each time.
- The `sync-aistack` skill on each computer replaces itself with the new server's copy on the first sync after the upgrade.

### The upgrade that retires `everyone` (ADR-0019)

New accounts no longer join a server-wide team. If your server's `everyone` has members or skills, it becomes an ordinary team: you are its admin, everything in it stays where people see it, and anyone may now leave it. If it is empty, it is removed.

There is no downgrade. The way back from an upgrade you regret is the backup you took before it.

## What is in the logs

Who joined, which skill was pushed at which revision, what sync reported, and how long each call took. Never the server's invite code, a team's invite code, a machine token, a transfer link, or a dashboard link. The HTTP access log is off for the last two: both links carry their credential in the URL path.

At `DEBUG`, AIStack's own lines add arguments such as names. The third-party libraries that print raw protocol payloads stay at `INFO` regardless, because a `join` result is a token on the wire.
