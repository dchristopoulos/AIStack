# Operating AIStack

For whoever runs the server. Everything here is one container and one volume: the MCP endpoint, the routes that move skill files, and the web dashboard are one process on one port.

## Run it

Make the server's invite code once, into a file you keep, then start the container with it:

```bash
openssl rand -base64 24 > invite-code.txt && chmod 600 invite-code.txt
docker run -d --name aistack \
  -p 127.0.0.1:8000:8000 \
  --read-only --tmpfs /tmp --cap-drop ALL --security-opt no-new-privileges \
  --log-driver local --log-opt max-size=10m --log-opt max-file=3 \
  -e AISTACK_INVITE_CODE="$(cat invite-code.txt)" \
  -v aistack-data:/data \
  --restart unless-stopped \
  --stop-timeout 25 \
  ghcr.io/dchristopoulos/aistack:0.1
```

`--stop-timeout 25` gives the server time to finish its requests and close the database when the container stops. Docker's default of 10 seconds is shorter than the server's own 20.

The flags are deliberate:

- `-p 127.0.0.1:8000:8000` publishes the port on this computer only. Docker's published ports bypass host firewalls such as ufw and firewalld, so a bare `-p 8000:8000` puts plain HTTP on every interface, next to the HTTPS your proxy serves. "Reaching it from other machines" below says what to put in front.
- `--read-only`, `--tmpfs /tmp`, `--cap-drop ALL` and `--security-opt no-new-privileges` hold because the server writes nothing outside `/data` and needs no privilege. CI runs the image with them.
- The `local` log driver with a size limit keeps the logs from filling the disk; Docker's default keeps them without limit. To feed fail2ban instead, use `--log-driver journald`, which journald rotates on its own (see "Refused credentials, and fail2ban").

The image is published by CI, for `linux/amd64` and `linux/arm64`, only from commits that passed the tests. Its tags:

- `0.1` is the newest release of 0.1. Stay on it: every release it moves to works with the database the one before it left. A release that older ones cannot run beside starts a new minor, `0.2`, with upgrade notes in [CHANGELOG.md](../CHANGELOG.md), and you move to it by changing the tag.
- `0.1.0`, `0.1.1` and so on are one release each, and `latest` is the newest release of any version.
- `edge` is the newest commit on `main`, and `sha-<commit>` each such commit. They are for trying what is coming, not for a server a team relies on: a commit can change the database in a way no release has yet.

The startup log names what is running: `Starting AIStack 0.1.0 ...` for a release, `0.1.0+g1a2b3c4` for the `main` commit tagged `sha-1a2b3c4`. To build it yourself instead, `docker build -t aistack .` in a checkout and run `aistack` in place of the published name.

Without Docker, the same server runs from PyPI with [uv](https://docs.astral.sh/uv/), which fetches Python 3.13 if it needs to. The database is a SQLite file in the current folder unless `DATABASE_URL` says otherwise:

```bash
AISTACK_INVITE_CODE_FILE=invite-code.txt uvx aistack-mcp serve
```

Or with Compose, which reads `AISTACK_INVITE_CODE` from a `.env` file next to `compose.yaml`:

```bash
echo "AISTACK_INVITE_CODE=$(openssl rand -base64 24)" > .env && chmod 600 .env
docker compose up -d
```

The file is where the code lives: the server never prints it, and there is no command that shows it afterwards. The startup log says only `Invite code: 'configured'`. The server refuses a code shorter than 24 characters, one with fewer than 10 different characters, and the examples printed in AIStack's documents, so a generated code is the only kind that starts it.

The volume at `/data` holds the SQLite database, which is every user, machine, team, group, skill, and revision. Stopping, removing, and recreating the container keeps all of it as long as the volume stays.

Then join with it yourself, as anyone would; the order does not matter. The first user to join is recorded as the server's admin (`is_admin`), but nothing reads that today: it grants no power in a tool or on the dashboard, and the server's own operations are the `aistack admin` commands below, which need access to the container, not an account. The README has the one-paste setup. After that, people usually arrive through a team's invite link, which creates their account; your own code is for admitting someone directly.

## Configuration

All of it is environment variables.

| Variable | Default | Meaning |
|---|---|---|
| `AISTACK_INVITE_CODE` | none, required | The shared secret new users join the server with. At least 24 characters, at least 10 of them different. The server refuses to start without one |
| `AISTACK_INVITE_CODE_FILE` | unset | A file holding the invite code, instead of `AISTACK_INVITE_CODE`, such as a mounted Docker secret. Set one or the other. The container's user, uid 10001, must be able to read it |
| `FORWARDED_ALLOW_IPS` | `127.0.0.1` | The addresses whose `X-Forwarded-For` the server believes. Behind a proxy on another host or container, set it to the proxy's address, or every client looks like the proxy and one person's wrong token turns everyone away |
| `AISTACK_PUBLIC_URL` | taken from each request | The address clients reach the server at, such as `https://aistack.example.com`. Set it behind a reverse proxy |
| `DATABASE_URL` | `sqlite:////data/aistack.db` | Any `postgresql+psycopg://` URL switches to PostgreSQL |
| `AISTACK_HOST` | `0.0.0.0` | Interface to bind |
| `AISTACK_PORT` | `8000` | Port to listen on |
| `AISTACK_MCP_PATH` | `/mcp` | Path of the MCP endpoint |
| `AISTACK_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL` |

### Why `AISTACK_PUBLIC_URL` matters

The server hands out URLs: the connection `add_machine` returns for another computer, the upload and download links that move skill files, and the link that signs a browser in to the dashboard. It builds them from its own address. Reached directly, it reads that address from the request. Behind a proxy that terminates TLS or rewrites the host, the request says `http://aistack:8000` and every URL it hands out is one nobody outside can open. Set the variable to the address people actually type. When it starts with `https://`, the dashboard's session cookie is marked `Secure`.

## Reaching it from other machines

AIStack ships a container and does not solve hosting. Whatever you choose, run **exactly one instance**: the key that signs dashboard links, sessions, and transfer URLs lives in that process's memory, so a second replica behind the same address refuses what the first one signed. Autoscaling platforms (Cloud Run, Azure Container Apps, Fly.io) need their maximum set to one. A platform that stops the container when idle restarts it on the next request, which signs the dashboard out each time.

Two patterns that work:

**A private network (Tailscale, WireGuard, a VPN).** Run the container on any machine in the network and use its private address. Nothing is exposed to the internet, and plain HTTP inside an encrypted tunnel is fine. This is the least work for a solo developer or a small team. Publish the port on the network's address rather than on every interface, with `-p 100.101.102.103:8000:8000` (the computer's tailnet address) or `AISTACK_BIND=100.101.102.103` with Compose, or keep `127.0.0.1` and put `tailscale serve` in front.

```text
AISTACK_PUBLIC_URL=http://aistack.your-tailnet.ts.net:8000
```

**A VPS behind a reverse proxy with TLS.** Put Caddy, nginx, or Traefik in front on the same host, terminate HTTPS there, and forward everything to `127.0.0.1:8000`, where the commands above publish the port. Forward all paths, not only `/mcp`: skill files travel over `/transfer/...`, setup is served from `/setup`, and the dashboard is `/app` and `/api/...`. Do not serve AIStack over plain HTTP on the public internet. Machine tokens, transfer links, dashboard links, and the dashboard's session cookie are bearer credentials, and anyone on the path could read them.

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

## Changing the server's address

Every computer's connection holds the address it was set up with, so moving the server (from a tailnet to a VPS, say, or to a new domain) leaves each one pointing at the old place. Tokens do not change with the address: each computer reconnects with the token it has.

Set `AISTACK_PUBLIC_URL` to the new address and start the server there. Then, on each computer, for Claude Code, `claude mcp get aistack` shows the token in its `Authorization` header; remove the connection and add it again with the new address and the same header:

```bash
claude mcp remove aistack --scope user
claude mcp add --transport http --scope user aistack https://new.example.com/mcp \
  --header "Authorization: Bearer <the same token>"
```

For Codex, change `url` in the `[mcp_servers.aistack]` block of `~/.codex/config.toml`. Restart the agent once. A computer whose token is lost gets a new one with `aistack admin rotate` instead.

## The dashboard

The dashboard is where people see their skills and manage teams, groups, and members. It needs nothing from you: it is served by the same process at `/app`, with its JSON API under `/api`, on the same port as everything else. There is no second service, no build step, and nothing to configure.

Nobody has a password. A user says "open my aistack dashboard" to their coding agent and gets a link that signs their browser in. The link works for five minutes and the session it starts lasts eight hours. Without a session, `/app` and `/api/...` answer 401.

The key that signs links and sessions is made at startup and kept in memory. **A restart signs every dashboard user out and voids every link and transfer URL not yet used.** Nothing is lost: a user asks their agent for a new link, and an agent that was mid-transfer calls the tool again. Machine tokens are not affected.

## Teams and invite codes

There are two kinds of invite code, and you manage only one.

- **The server's invite code** is `AISTACK_INVITE_CODE`. It lets a new person create an account on this server, in no team. It is for you and the people you hand it to yourself; everyone else usually arrives through a team's invite link.
- **A team's invite code** starts with `aistinv_`. A team's admin, or a member the admin lets invite, makes one from chat or the dashboard. Each one lets one person in and lasts seven days, making another cancels none, and any pending one can be cancelled from the team's settings. Its link, `/invite/<code>`, tells someone new to the server what to paste, and the same code then creates their account. The server stores only its hash, so there is nothing to read back out of the database.

Users create teams and groups themselves and administer them. An admin can delete a team, and the last member leaving deletes it. The operator steps in only when a team's admins are all gone: see "Name a team's admin" below.

## Admin operations

No tool and no dashboard page performs the server's own admin operations. They are `aistack admin` commands, run inside the container. Each one is a single transaction on the server's own database setup, so it works the same on SQLite and PostgreSQL, and a name that does not exist answers with a sentence and changes nothing. `docker exec aistack aistack admin --help` lists them.

### List users and machines

```bash
docker exec aistack aistack admin machines
docker exec aistack aistack admin machines maria
```

Each line is a user, a computer, its operating system, when it was added, and when each of its coding agents last synced.

### A laptop was lost or stolen

The person can do this themselves while they still have another computer: on the dashboard, open the lost computer and choose Remove this computer. Its token, sessions and transfer URLs end at once, and the computers it added say "added from a computer since removed". The rest of this section is for when you act for them, or when the lost laptop was their only computer.

### Rotate a lost laptop's token

This is the answer to both "revoke the old one" and "let the user back in". The old token stops working on its next request, the machine keeps its name and its enabled skills, and the user gets a new token. Every dashboard session that laptop opened, and every transfer URL it was given, ends with the old token (ADR-0027).

```bash
docker exec aistack aistack admin rotate maria laptop
```

It prints the new token inside what the user pastes on the replacement computer: the Claude Code commands that remove the old connection and add the new one, and the Codex block. It builds them from `AISTACK_PUBLIC_URL`; without it, add `--url https://aistack.example.com`, the address people type. The token is printed once, in your terminal, and never logged. Send it to the user over something private.

Whoever holds the laptop may have used it before you rotated. Then:

- **Computers it added.** List the user's machines. Any added after the loss that the user does not recognise was added with `add_machine` from the laptop: remove it, below. Its token, sessions and URLs end with it.
- **Skills it changed.** A machine installs its user's newest revision without asking. Have the user look over their Library on the dashboard and push their own copy back over anything they did not write.
- **Invites it made.** If the user is a team admin or may invite, the team's admins check the team's pending invites on the dashboard and cancel any the user did not make.

### A machine is gone for good: remove it

```bash
docker exec aistack aistack admin remove-machine maria old-desktop
```

Its token is rejected from the next request on, and the record of which skills it had enabled goes with it. Unlike the dashboard, this removes a user's last computer too. Do this through the command and not with a bare `sqlite3` shell: SQLite only cascades deletes when a per-connection setting is on, and the server's database setup turns it on.

### A user has no machine left

If their only machine was removed, or their first join went through but its answer never reached them, they cannot call `add_machine`, and joining again is refused because the username exists. Register a machine for them:

```bash
docker exec aistack aistack admin register-machine maria new-laptop --os macos
```

`--os` is `macos`, `windows` or `linux`. It prints the token and what to paste, as `rotate` does.

**Never delete a user.** Every skill and revision records who pushed it, and their teams and memberships point at them. Deleting someone either fails or destroys that record, and the record is how a team knows whose instructions their agents are running.

### Rename a user

A username is what teammates see beside each skill, and nothing but this command changes it:

```bash
docker exec aistack aistack admin rename-user maria maria.k
```

Their computers, sessions and teams keep working, and every revision they pushed shows the new name, because revisions record who pushed them by id. A name a user or a team already has is refused.

### Someone left: take them off the server

```bash
docker exec aistack aistack admin offboard maria
```

This takes them out of every team, then removes every computer of theirs. A team they were the only admin of needs someone to take it over, and the command refuses, changing nothing, until you name one: `--successor acme=dimitris`, once per team. A team they were the only member of is deleted. Their pending invites stop working: an invite works only while its maker is on the server and may still invite into its team.

With no machine they have no token, so they can reach neither the MCP endpoint nor the dashboard, and a dashboard session they still hold ends with the machine that opened it. Their account, the skills they shared, and the `pushed_by` on each revision stay. Then rotate the server's invite code, below.

A team's admin removes a person from that team in the dashboard. That cancels the invites the person made into the team, as leaving it does, and as losing the right to invite does. Leaving the server altogether is this operation.

### Name a team's admin

For a team whose admins are all gone, for instance because one was taken off the server before `offboard` handed teams over. The person must already be in the team.

```bash
docker exec aistack aistack admin name-admin acme dimitris
```

### List teams and who is in them

```bash
docker exec aistack aistack admin teams
```

Personal teams are left out: each user has one, named after them, and it is their private space.

### Rotate the server's invite code

Write a new code to the file and recreate the container, which reads its environment only when it is created: `docker restart` keeps the old code working.

```bash
openssl rand -base64 24 > invite-code.txt
docker rm -f aistack
```

Then run the `docker run` command from the top of this page again; the volume keeps every account and skill. With Compose, put the new code in `.env` and run `docker compose up -d`, which recreates the container because its environment changed. With `AISTACK_INVITE_CODE_FILE`, a plain restart is enough: the file is read each time the server starts.

Everyone who already joined is unaffected: they authenticate with machine tokens, not the code. Rotate it when someone leaves, and whenever it has been shared somewhere less private than you meant. Recreating the container signs dashboard users out, as any restart does.

## Backups

The SQLite database is `aistack.db` in the volume. While the server runs, SQLite keeps the latest writes in `aistack.db-wal` beside it, with `aistack.db-shm` as its index: the three files together are the database, and a copy of `aistack.db` alone can be missing anything. A server that stopped cleanly folds everything back into `aistack.db` and leaves it alone.

Take a backup with the server running. It is one file that holds everything, made from a consistent read, so writes during it are safe:

```bash
docker exec aistack aistack backup /data/aistack-backup.db
docker cp aistack:/data/aistack-backup.db ./aistack-backup-$(date +%F).db
docker exec aistack rm /data/aistack-backup.db
```

`aistack backup` never replaces a file; name a new one each time. Keep the copies somewhere other than the server. For continuous backup to object storage, [Litestream](https://litestream.io) works with the same file.

On PostgreSQL, `aistack backup` says what to run instead: `pg_dump --format=custom`, and `pg_restore --clean` to restore.

Every upgrade that changes the schema also keeps a copy of its own, before it changes anything: `aistack-before-<schema>-<time>.db` in the volume, the newest three of them. That is the copy to go back to after an upgrade you regret, if you did not take one.

## Restore

Stop the server, restore with a container of the same image that shares the volume, then start the release that made the backup, or a newer one:

```bash
docker stop aistack
docker run --rm -v aistack-data:/data -v "$PWD":/backup:ro \
  ghcr.io/dchristopoulos/aistack:0.1 aistack restore /backup/aistack-backup-2026-10-15.db
docker start aistack
```

`aistack restore` checks that the file is an intact AIStack database, refuses while anything still has the database open, removes the `-wal` and `-shm` files that would otherwise be replayed over the restored data, and keeps the database it replaced beside it as `aistack.db.replaced-<time>`. Delete that once the restored server looks right.

Never restore by copying a file over `aistack.db`: the old `-wal` next to it brings back exactly what the restore was meant to undo.

### Upgrade rollback

An older release refuses to start on a database that a newer one changed in a way it cannot use, and says which release made the change (ADR-0024). To go back to the older release, restore the copy from before the upgrade with the newer image, which has `aistack restore`, then start the older image by its version tag:

```bash
docker stop aistack && docker rm aistack
docker run --rm -v aistack-data:/data ghcr.io/dchristopoulos/aistack:0.1 \
  sh -c 'ls -t /data/aistack-before-*.db'
docker run --rm -v aistack-data:/data ghcr.io/dchristopoulos/aistack:0.1 \
  aistack restore /data/aistack-before-<schema>-<time>.db
```

Then start the older release with the `docker run` from the top of this page, naming its version, such as `0.1.0`, instead of `0.1`. Anything written after the upgrade is lost, which is why the newer release's data is kept beside it as `aistack.db.replaced-<time>`.

## PostgreSQL

The same image runs against PostgreSQL. Nothing else changes:

```bash
docker run -d --name aistack -p 127.0.0.1:8000:8000 \
  --read-only --tmpfs /tmp --cap-drop ALL --security-opt no-new-privileges \
  -e AISTACK_INVITE_CODE="..." \
  -e DATABASE_URL="postgresql+psycopg://aistack:password@db.internal:5432/aistack" \
  ghcr.io/dchristopoulos/aistack:0.1
```

It is the one image either way: there is no separate PostgreSQL build, and the volume is simply unused.

A managed PostgreSQL works, with two settings to get right. On **Supabase**, use the shared pooler in session mode (port 5432); transaction mode (port 6543) does not support the prepared statements psycopg uses. On **Neon**, use the direct endpoint, not the pooled one. Managed databases close idle connections; AIStack checks a pooled connection before using it, so a closed one is replaced rather than failing a request. A database that scales to zero is kept awake by the container's 30-second health check, which on Neon's free plan uses up the month's compute in about 17 days; turn the health check off there (`--no-healthcheck`) and let your platform's own check call `/health` less often.

SQLite is the default because one container is easier to run than two, and the write volume of people pushing skills is tiny. Move to PostgreSQL when you already run one and want AIStack's data with the rest of yours, not for performance. The test suite runs every service and HTTP test against both.

## Upgrading

Back up, then pull the new image (`docker pull ghcr.io/dchristopoulos/aistack:0.1`, or rebuild a checkout) and recreate the container. With Compose, which keeps every flag in a file, that is `docker compose pull && docker compose up -d`. At startup the server brings the database to the schema its release expects, before it accepts a request. On SQLite it first keeps a copy of the database as it was (see [Backups](#backups)). Every pending change is applied in one transaction: either all of it lands or the database is exactly as it was.

A server still on an older release keeps working after another process upgraded the database, as long as every change since only added something; after a change that removed or reshaped something, it refuses to start and says which release to run (ADR-0024). A server that was already running when another process made such a change refuses each call from then on with the same sentence, and changes nothing, until it is restarted on the new release (ADR-0031). With several replicas, upgrade them all.

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

There is no downgrade. The way back from an upgrade you regret is the backup you took before it, or the copy the upgrade kept: see [Upgrade rollback](#upgrade-rollback).

## What is in the logs

Who joined, which skill was pushed at which revision, what sync reported, and how long each call took. Never the server's invite code, a team's invite code, a machine token, a transfer link, or a dashboard link. The HTTP access log is off for the last two: both links carry their credential in the URL path.

At `DEBUG`, AIStack's own lines add arguments such as names. The third-party libraries that print raw protocol payloads, FastMCP among them, stay at `INFO` regardless, because a `join` result is a token on the wire and a `join_team` call carries a team's invite code.

### Refused credentials, and fail2ban

A wrong machine token, server or team invite code, invite link, or dashboard link is logged at `INFO` with the address it came from, never with what was sent:

```
2026-10-15 19:20:01,512 INFO     [aistack.mcp.auth.aistack_token_verifier.verify_token] Bearer rejected: not an invite code that works and no machine holds it. Client: '203.0.113.7'. Elapsed: '3ms'.
```

After 20 refusals within a minute, the address is answered `429` with `Retry-After` until the minute has passed, before anything reaches the database, and one `WARNING` line says so: `Client throttled: ... Client: '203.0.113.7'`. A refused `join` for a name already taken is limited separately, to 5 an hour per address and per team code, because each one says whether a name exists. Both counts are in memory and a restart forgets them.

The address is the one uvicorn resolved, so behind a proxy set `FORWARDED_ALLOW_IPS` (above). To ban a repeated guesser at the firewall, a fail2ban filter matches the throttle line:

```ini
# /etc/fail2ban/filter.d/aistack.conf
[Definition]
failregex = Client throttled: .* Client: '<HOST>'
```

```ini
# /etc/fail2ban/jail.d/aistack.conf
[aistack]
enabled  = true
filter   = aistack
backend  = systemd
journalmatch = CONTAINER_NAME=aistack
maxretry = 3
findtime = 1h
bantime  = 1d
```

`journalmatch` assumes Docker's `journald` log driver (`--log-driver journald`, or `driver: journald` in `compose.yaml`); the `local` driver the commands above use writes a format fail2ban cannot read. With a log file, use `logpath` instead.
