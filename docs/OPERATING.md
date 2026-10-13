# Operating AIStack

For whoever runs the server. Everything here is one container and one volume.

## Run it

```bash
docker build -t aistack .

docker run -d --name aistack \
  -p 8000:8000 \
  -e AISTACK_INVITE_CODE="$(openssl rand -base64 24)" \
  -v aistack-data:/data \
  --restart unless-stopped \
  aistack
```

Or with Compose, which reads `AISTACK_INVITE_CODE` from the environment or a `.env` file:

```bash
AISTACK_INVITE_CODE="$(openssl rand -base64 24)" docker compose up -d
```

Write the invite code down before you run either. You chose it, the server never prints it, and there is no command that shows it afterwards. The startup log says only `Invite code: 'configured'`.

The volume at `/data` holds the SQLite database, which is every user, machine, skill, and revision. Stopping, removing, and recreating the container keeps all of it as long as the volume stays.

Then join first, alone, before you share the code: the first user to join becomes the admin. The README has the one-paste setup.

## Configuration

All of it is environment variables.

| Variable | Default | Meaning |
|---|---|---|
| `AISTACK_INVITE_CODE` | none, required | The shared secret new users join with. At least 16 characters. The server refuses to start without one |
| `AISTACK_PUBLIC_URL` | taken from each request | The address clients reach the server at, such as `https://aistack.example.com`. Set it behind a reverse proxy |
| `DATABASE_URL` | `sqlite:////data/aistack.db` | Any `postgresql+psycopg://` URL switches to PostgreSQL |
| `AISTACK_HOST` | `0.0.0.0` | Interface to bind |
| `AISTACK_PORT` | `8000` | Port to listen on |
| `AISTACK_MCP_PATH` | `/mcp` | Path of the MCP endpoint |
| `AISTACK_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL` |

### Why `AISTACK_PUBLIC_URL` matters

The server hands out URLs: the `claude mcp add` command from `add_machine`, and the upload and download links that move skill files. It builds them from its own address. Reached directly, it reads that address from the request. Behind a proxy that terminates TLS or rewrites the host, the request says `http://aistack:8000` and every URL it hands out is one nobody outside can open. Set the variable to the address people actually type.

## Reaching it from other machines

AIStack ships a container and does not solve hosting. Two patterns that work:

**A private network (Tailscale, WireGuard, a VPN).** Run the container on any machine in the network and use its private address. Nothing is exposed to the internet, and plain HTTP inside an encrypted tunnel is fine. This is the least work for a solo developer or a small team.

```text
AISTACK_PUBLIC_URL=http://aistack.your-tailnet.ts.net:8000
```

**A VPS behind a reverse proxy with TLS.** Put Caddy, nginx, or Traefik in front, terminate HTTPS there, and forward everything to port 8000. Forward all paths, not only `/mcp`: skill files travel over `/transfer/...`. Do not serve AIStack over plain HTTP on the public internet. Machine tokens and transfer links are bearer credentials, and anyone on the path could read them.

```text
AISTACK_PUBLIC_URL=https://aistack.example.com
```

A minimal Caddyfile:

```text
aistack.example.com {
    reverse_proxy 127.0.0.1:8000
}
```

`GET /health` answers `{"status": "ok"}` without a token when the server can reach its database, and 503 when it cannot. The container's own health check uses it.

## Admin operations

The MVP has no admin tools. These are the operations an admin needs, as short scripts that run inside the container. They use the server's own database setup, so they work the same on SQLite and PostgreSQL.

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

**Never delete a user.** Every skill and revision records who pushed it. Deleting someone who has pushed anything either fails or destroys that record, and the record is how the team knows whose instructions their agents are running.

### Rotate the invite code

Change `AISTACK_INVITE_CODE` and restart the container. Everyone who already joined is unaffected: they authenticate with machine tokens, not the code. Rotate it when someone leaves, and whenever it has been shared somewhere less private than you meant.

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
  aistack
```

SQLite is the default because one container is easier to run than two, and the write volume of a team pushing skills is tiny. Move to PostgreSQL when you already run one and want AIStack's data with the rest of yours, not for performance. The test suite runs every service and HTTP test against both.

## Upgrading

Pull, rebuild, restart. The server creates any table that is missing at startup. It does not yet alter existing tables, so an upgrade that changes a table's shape will say so in its release notes and ship a migration step. Back up first.

## What is in the logs

Who joined, which skill was pushed at which revision, what sync reported, and how long each call took. Never the invite code, a machine token, or a transfer link. The HTTP access log is off for that last reason: a transfer link carries its credential in the URL path.

At `DEBUG`, AIStack's own lines add arguments such as names. The third-party libraries that print raw protocol payloads stay at `INFO` regardless, because a `join` result is a token on the wire.
