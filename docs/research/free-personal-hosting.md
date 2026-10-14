# Free or near-free hosting for one person's AIStack

Researched 2026-10-14. Every provider claim cites the provider's own page, read on that date. Where a page could not be read, it says so. Prices and free tiers change; re-check before relying on a number.

## Summary and recommendation

AIStack needs one process that every computer the person owns can reach over HTTPS (or over a private network), and one database. Five properties of AIStack decide where it can run:

1. **One instance only.** The key that signs dashboard links, sessions, and transfer URLs is made at startup and held in memory (`docs/OPERATING.md`, "The dashboard"). Two instances behind one URL have two keys, so a link minted by one fails on the other. With SQLite, two instances would also have two databases. Every autoscaling host must be pinned to a maximum of one instance.
2. **A restart signs the dashboard out** and voids unused transfer URLs. A host that sleeps when idle restarts on the next request. Nothing is lost (machine tokens survive), but each wake means asking the agent for a new dashboard link.
3. **SQLite needs a real local disk.** WAL and `BEGIN IMMEDIATE` (ADR-0014) need POSIX file locking. Network filesystems that lack locking (Cloud Run's Cloud Storage volumes, for example) are unsafe.
4. **PostgreSQL goes through plain psycopg 3 with SQLAlchemy's default pool**, with no `pool_pre_ping` and no connect arguments (`src/aistack/db/engine.py`). psycopg prepares a statement after its 5th execution on a connection (default `prepare_threshold=5`), so transaction-mode poolers that do not support prepared statements will break it. Migrations run at startup through the same URL, in one transaction (ADR-0016).
5. **`/health` runs `SELECT 1`**, and the image's Docker `HEALTHCHECK` calls it every 30 seconds. On a database that scales to zero after 5 minutes of no queries, that check keeps it awake around the clock.

Ranked for a solo developer:

1. **An always-on machine you already own, Tailscale, and SQLite. Cost: $0.** Run the container on a desktop, NAS, mini PC, or Raspberry Pi (the image is built for arm64 too), with `tailscale serve --bg` in front for tailnet-only HTTPS. There is no cold start and no third party holding the data. The server restarts only when you restart it, and the default SQLite setup is the one AIStack is built around. The cost is that every client must run Tailscale. If your employer will not let you install it on a work machine, `tailscale funnel` publishes the same server on the public internet with TLS ending on your own device. AIStack's bearer tokens are designed for exposure like that, but it is still exposure. A laptop does not work as the host, because it sleeps.
2. **Fly.io, one Machine, one volume, SQLite. Cost: about $2.34 to $3.84 a month.** Fly.io has no free tier for new organizations. In return you get a stable `*.fly.dev` HTTPS URL, a real disk for SQLite, no sleeping if you set it that way, and one provider instead of two. Use 256 MB ($2.19) if the process fits, 512 MB ($3.69) if it does not, plus $0.15 for a 1 GB volume. Deploy with `--ha=false` and disable auto-stop. This is the cheapest dependable option if you have no always-on machine.
3. **A free VM (Google Cloud e2-micro), SQLite on its disk, and Tailscale or Caddy. Cost: $0 for the VM, plus probably about $3.65 a month for its public IPv4 address (not confirmed).** It is a real always-on VM with a 30 GB disk and no sleeping. The catches: it needs a billing account, it runs only in three US regions, and Google lists an in-use external IPv4 charge whose interaction with the free tier its pages do not state. Oracle's Always Free VMs are bigger and include 10 TB of egress, but Oracle may reclaim an instance that is idle by its definition, and a personal AIStack would almost always meet that definition (below 20% p95 CPU over 7 days).

The combination of a free container host and a free PostgreSQL works only with degradations, so it is not in the top three. The least bad version is Google Cloud Run or Koyeb's free instance pinned to one instance, with Neon's direct (non-pooled) endpoint or Supabase's session-mode pooler. Each idle period restarts the server, which signs the dashboard out. Two free-tier policies have to hold at once. On Neon, one of two things happens. Either the scaled-to-zero compute closes pooled connections, and with AIStack's current engine the first request after each idle period fails. Or a frequent health check keeps the compute awake, and the 100 CU-hour monthly allowance runs out after about 16.7 days at 0.25 CU. Render's free tier is worse: its cold start of about a minute is longer than Claude Code's default 30-second MCP connection timeout.

Options that do not work for AIStack:

- **Hugging Face Spaces.** Docker Spaces now need a paid plan, Spaces block outbound traffic on every port except 80, 443, and 8080 (so 5432 and 6543 are blocked), and the disk is not persistent.
- **Render's free PostgreSQL.** It is deleted 30 days after creation, after a 14-day grace period.
- **Railway's Free plan.** Its $1 of monthly credit does not cover an always-on process: about 150 MB of RAM alone costs about $1.50 a month at the listed rate.
- **CockroachDB.** Its pricing page lists a 30-day trial and no free tier. Its schema changes inside a transaction are not atomic, which breaks AIStack's all-or-nothing migrations.
- **Cloudflare Quick Tunnels.** The hostname changes on every start, while AIStack embeds its URL in every machine's MCP configuration.
- **Xata.** It offers a 14-day trial, then pay as you go.

## What AIStack requires of a host

These facts come from the repository. They are the reasons behind the verdicts below.

| Requirement | Where it comes from | What it means for hosting |
|---|---|---|
| Exactly one process | Signing key in memory (OPERATING.md "The dashboard"; ADR-0017) | Set max instances to 1 on Cloud Run, Azure Container Apps (default max is 10), and Fly (default `fly launch` makes 2 Machines when no volume is mounted) |
| Restart signs the dashboard out | Same | Scale-to-zero hosts cost a dashboard sign-in after each idle period. Machine tokens and the MCP endpoint are unaffected (stateless, ADR-0013) |
| Stable public URL | Setup commands and `add_machine` embed `AISTACK_PUBLIC_URL` (OPERATING.md) | A URL that changes, such as a Quick Tunnel, strands every configured machine |
| HTTPS on the public internet | Tokens, transfer links, and cookies are bearer credentials (OPERATING.md) | Plain HTTP is acceptable only inside a private network such as a tailnet |
| SQLite on a local POSIX disk | WAL and `BEGIN IMMEDIATE` (ADR-0014) | Needs a block volume. Not object-storage FUSE, not ephemeral disk |
| psycopg 3.3.5 with bundled libpq 18, default `prepare_threshold=5` | `poetry.lock`, checked locally | Transaction poolers without prepared-statement support break it after a few requests. Session poolers and direct connections work |
| `pool_pre_ping=True` on PostgreSQL (added after this research; it had no options before) | `build_engine` | Connections that the server closes while idle (Neon suspend, provider idle timeouts) are replaced on checkout instead of failing the first request after idle |
| Health check runs `SELECT 1` every 30 s under Docker | `mcp/routes/health.py`, `Dockerfile` HEALTHCHECK | Keeps a scale-to-zero database permanently awake |
| Memory | Measured locally: about 136 MiB RSS idle (macOS arm64, Python 3.14 from the Poetry env, not the image's 3.13; a rough figure) | 256 MB is tight and 512 MB is comfortable |

Savepoints (`begin_nested`) are used in several services. They stay inside one transaction, so transaction-mode pooling does not affect them.

## PostgreSQL providers

| Provider | Free limits | Idle behaviour | Connections | Pooler caveats for AIStack | Region | SSL | Card |
|---|---|---|---|---|---|---|---|
| **Neon** | 100 projects; 1 GB storage per project; 100 CU-hours per project per month (400 h at 0.25 CU); 5 GB egress | Compute suspends after 5 min with no active queries, fixed on Free. Wakes in a few hundred ms. Idle connections are closed on suspend. Running out of CU-hours suspends compute until the next month; data is not deleted | Direct: 104 `max_connections` at 0.25 CU (97 usable). Pooled: up to 10,000 clients | Pooler is PgBouncer in transaction mode with `max_prepared_statements=1000`, so psycopg's protocol-level prepared statements work. Neon still recommends the direct endpoint for migrations. Use the direct endpoint: one server needs at most about 15 connections | 8 AWS regions (US, EU Frankfurt and London, Singapore, Sydney, São Paulo). Docs do not restrict Free | Required; `verify-full` recommended | Not required |
| **Supabase** | 2 active projects; 500 MB database; shared CPU, 500 MB RAM (Nano); 5 GB egress; no automatic backups | Paused after 1 week of too little activity; email warning first. Restorable from the dashboard for up to 1 year | Nano: 60 direct, 200 pooler clients | Direct connection is IPv6-only on Free. Shared pooler session mode (port 5432, IPv4) supports prepared statements: **use this one**. Transaction mode (port 6543) does not support prepared statements and breaks psycopg's defaults | 17 specific AWS regions plus 3 general areas. Docs do not say Free is restricted | `sslmode=require`; `verify-full` with the downloaded root certificate | Not stated on pricing page |
| **Aiven** | 1 node, 1 CPU, 1 GB RAM, 1 GB disk; one free service per type | Powered off after no ongoing activity, with notice; can be powered on again. May also be powered off if unused in the first hours | `max_connections` 20; no connection pooling | No pooler, so no pooler caveat. 20 connections is enough if the pool stays at SQLAlchemy's default 5 plus 10 overflow | **Cannot choose**; Aiven may change cloud or region at any time | Not stated on the pages read | Not required |
| **Prisma Postgres** | 50 databases; 1.01 GB; 200k operations per month | Not stated for databases. Connection idle timeout is 60 min | 10 direct, 10 pooled | Direct host `db.prisma.io:5432` accepts standard clients. The pooled string gives "prepared statement errors" for migrations per Prisma's docs, so use direct. Whether direct TCP queries count as "operations" is not stated; a 30-second health check alone is about 86k queries a month | Not checked | `sslmode=require`, mandatory | Not checked |
| **Xata** | 14-day trial only, then pay as you go | Scale-to-zero on idle branches | n/a | n/a | n/a | n/a | Card after trial |
| **CockroachDB** | No free tier on the pricing page: 30-day trial with $400 credit, then clusters pause and are deleted after 30 days without payment | n/a | n/a | Schema changes in explicit transactions are not atomic and can fail at COMMIT, leaving the transaction partly committed. AIStack applies every migration in one transaction, so this breaks its upgrade guarantee. It also needs a different SQLAlchemy dialect | n/a | n/a | Not needed for trial |
| **Koyeb Postgres** | "Free 5h" instance: 0.25 vCPU, 1 GB RAM, 1 GB storage; meaning of "5h" not explained | Scale-to-zero | Not stated | Not evaluated further | Washington, Frankfurt, Singapore | Not checked | See Koyeb below |
| **Render Postgres** | Free databases expire 30 days after creation, then a 14-day grace period before deletion | n/a | n/a | Does not work as a permanent store | n/a | n/a | n/a |

### Neon in detail

- What counts as idle: "no active queries for 5 minutes". An idle-in-transaction connection counts as active. Connections that are "truly inactive" are closed when the compute suspends, and session state is lost ([compute lifecycle](https://neon.com/docs/introduction/compute-lifecycle)).
- Consequence for AIStack's engine: with SQLAlchemy's default optimistic disconnect handling, the first statement on a connection the server closed raises a `DBAPIError` with `connection_invalidated=True`. The pool is then recreated, so later requests work ([SQLAlchemy pooling, "Dealing with Disconnects"](https://docs.sqlalchemy.org/en/20/core/pooling.html)). Expect one failed tool call, health check, or dashboard request after each idle period. `pool_pre_ping=True` in `build_engine` prevents it, and a PostgreSQL test now closes a pooled connection from the server side to prove it. Not tested against Neon itself.
- CU-hour arithmetic: 100 CU-hours at 0.25 CU is 400 hours, about 16.7 days. If anything queries the database at least every 5 minutes, such as the image's 30-second Docker health check or a platform health check pointed at `/health`, the compute never suspends, and the month's allowance runs out around day 17. After that the compute stays suspended until the next billing period ([plans](https://neon.com/docs/introduction/plans)). Without such a check, a personal workload is a few short bursts a day and stays far under the limit.
- The pooled endpoint should work: protocol-level prepared statements are supported since PgBouncer 1.22, `max_prepared_statements` is 1000, and the bundled libpq is 18, which meets psycopg's libpq 17 requirement for PgBouncer ([Neon pooling](https://neon.com/docs/connect/connection-pooling); [psycopg prepare](https://www.psycopg.org/psycopg3/docs/advanced/prepare.html)). It gives a single server nothing, though, and Neon recommends direct connections for migrations, which AIStack runs at every startup.
- Example: `DATABASE_URL=postgresql+psycopg://user:pass@ep-xxx.eu-central-1.aws.neon.tech/neondb?sslmode=verify-full`. `verify-full` needs a CA bundle that libpq can find. `require` encrypts without verifying the server. Not tested here.

### Supabase in detail

- Inactivity is judged over 7 days; "a few user requests to the database each day" is typically enough to avoid a pause ([free plan pausing](https://supabase.com/docs/guides/platform/free-plan-pausing)). Daily AIStack use, or the health check, keeps it active. A week away from every computer with the server stopped could pause it, and resuming is a click in the Supabase dashboard.
- Use the shared pooler in session mode: `postgresql+psycopg://postgres.<ref>:<pass>@aws-<n>-<region>.pooler.supabase.com:5432/postgres?sslmode=require`. Supabase's own recommendation for persistent servers on IPv4-only networks is session mode, and it says to use the direct connection for migrations ([connecting](https://supabase.com/docs/guides/database/connecting-to-postgres)). Direct is IPv6-only on Free. Whether a given container host can make outbound IPv6 connections was not checked.
- Do not use port 6543 (transaction mode). Prepared statements are "Not supported" there, and psycopg prepares after 5 executions.

## Places to run the container

| Host | Free allowance | Sleep and cold start | Signing key | Volume for SQLite | HTTPS and stable URL | Card | Fit for AIStack |
|---|---|---|---|---|---|---|---|
| **Own always-on machine + Tailscale** | $0. Personal plan: up to 6 users, unlimited user devices | None: runs as long as the machine does | Survives until you restart | Local disk | `https://<machine>.<tailnet>.ts.net` via Serve (tailnet only) or Funnel (public; ports 443, 8443, 10000 only). TLS ends on your device | Not stated | **Best.** Every client needs Tailscale unless you use Funnel |
| **Own machine + Cloudflare Tunnel** | Tunnel "Available on all plans" | None | Survives | Local disk | Needs a domain active on Cloudflare (a registered domain costs money). Outbound-only. Free plan terms restrict serving "video and other large files"; skill archives are at most 1 MiB | Not checked | Works if you already have a domain on Cloudflare |
| **Cloudflare Quick Tunnel** | Free, no account | n/a | Survives | Local disk | Hostname changes each time; "for testing and development"; no uptime guarantee | No | **Does not work**: URL changes break every machine's config |
| **Fly.io** | No free tier for new orgs. Trial: 2 h of Machine runtime or 7 days. 256 MB $2.19/mo, 512 MB $3.69/mo, volume $0.15/GB/mo, shared IPv4 free, first 10 certificates free | Your choice: auto-stop is on by default for new apps, so turn it off for an always-on server | Survives if auto-stop is off | Yes: a block volume on one server, attached to one Machine, with daily snapshots kept 5 days by default | `*.fly.dev` with TLS | Required after trial | **Good, not free.** Use `--ha=false`; a volume also forces a single Machine |
| **Render free** | 750 instance-hours per workspace per month | Spins down after 15 min without inbound traffic; spin-up "about one minute" | Lost at every spin-down; Render "may restart a free web service at any time" | No: free services cannot attach disks | `*.onrender.com`, custom domains with TLS | Not required for free instances | **Poor.** One-minute cold start exceeds Claude Code's 30 s `MCP_TIMEOUT` default. Needs external Postgres. Render: "Do not use them for production applications" |
| **Railway** | Free plan: $1 of credit per month; 0.5 GB RAM; 0.5 GB volume. Trial: one-time $5. RAM $10/GB/mo, vCPU $20/vCPU/mo | Opt-in "Serverless" sleeps after 5 to 10 min without outbound packets; first request may get a 502 | Lost on sleep | 0.5 GB volume on Free | Not stated for Free | Post-paid card required | **Does not fit in $1** if always on. Hobby is $5/mo |
| **Koyeb free instance** | One per org: 512 MB, 0.1 vCPU, 2 GB SSD | Scales to zero after 1 h without traffic; cold-start time not stated | Lost after each hour of idleness | No volumes on free | `*.koyeb.app` (not verified) | FAQ: "We require a credit card to prevent fraud and abuse" | **Workable with Neon or Supabase** (Frankfurt or Washington only). Untested |
| **Google Cloud Run** | Request-based billing: 2M requests, 180,000 vCPU-s, 360,000 GiB-s per month | Min instances 0 by default; idle instance kept up to 15 min | Lost after up to 15 min idle | Cloud Storage FUSE has no file locking and is "not a fully POSIX-compliant file system": not safe for SQLite | `*.run.app` with TLS | Billing account required | **Workable with Postgres**, with `--max-instances=1`. Free-tier regions could not be confirmed (pricing page did not render) |
| **Google Compute Engine e2-micro** | One e2-micro per month in us-west1, us-central1, or us-east1; 30 GB-months standard disk; 1 GB egress from North America | None | Survives | Yes, persistent disk | Bring your own: Tailscale or Caddy with a domain | Billing account required | **Good if the IPv4 cost is acceptable.** Google lists an in-use external IPv4 at $0.005 per hour (about $3.65/month by my arithmetic); its free-tier page does not say whether that is waived |
| **Oracle Cloud Always Free** | 2 AMD micro VMs (1/8 OCPU, 1 GB) or Ampere A1 up to 2 OCPU / 12 GB; 200 GB block storage; 10 TB egress | None, but idle instances "may be reclaimed": p95 CPU below 20%, network below 20%, and (A1 only) memory below 20% over 7 days | Survives unless reclaimed | Yes | Bring your own | Card required for verification (hold, not charged) | **Risky.** A personal AIStack is idle by that definition. Home region is fixed at signup, and "out of host capacity" errors are documented |
| **Azure Container Apps** | 180,000 vCPU-s, 360,000 GiB-s, 2M requests per subscription per month | Default min replicas 0, max 10; scale to zero after a 300 s cool-down | Lost on scale-to-zero. Extra replicas can appear during platform maintenance | Azure Files (SMB/NFS) only; the docs give no locking guarantee for databases. Treat as unsafe for SQLite | `*.azurecontainerapps.io` (not verified) | Azure account; card not checked | Like Cloud Run but more setup. Must set max replicas to 1 |
| **Hugging Face Spaces** | Docker Spaces need a paid plan (PRO) | Free hardware sleeps when unused | Lost | Disk not persistent | `*.hf.space` | n/a | **Does not work**: paid, and outbound traffic is limited to ports 80, 443, and 8080, so Postgres on 5432 or 6543 is unreachable |

### Notes on the hosts

**Tailscale.** `tailscale serve --bg` "runs persistently in the background until you disable it" and resumes after a reboot ([Serve CLI](https://tailscale.com/kb/1242/tailscale-serve)). With Serve, the server is reachable only from devices in your tailnet. Set `AISTACK_PUBLIC_URL=https://<machine>.<tailnet>.ts.net`, which also marks the dashboard cookie `Secure`. This is an improvement on the `http://...:8000` example in `docs/OPERATING.md`. Turning on HTTPS publishes the machine's full name in public Certificate Transparency logs, so do not put anything sensitive in the machine name ([enabling HTTPS](https://tailscale.com/kb/1153/enabling-https)). Funnel is available on all plans. It uses `<tailnet>.ts.net` names only and ports 443, 8443, and 10000, has non-configurable bandwidth limits, and ends TLS on your device, so the relay cannot read the traffic ([Funnel](https://tailscale.com/kb/1223/funnel)).

**Fly.io.** Without a volume, `fly launch` "creates and starts two Machines for process groups with services", with auto-stop on and minimum running Machines at zero. With a volume it creates one ([availability](https://docs.fly.io/apps/app-availability)). For AIStack, mount a volume at `/data`, keep the default SQLite URL, set `auto_stop_machines = "off"` (or `min_machines_running = 1`), and set `AISTACK_PUBLIC_URL=https://<app>.fly.dev`. A volume lives on one physical server and is not replicated, and Fly warns that a single Machine with a single volume risks downtime and data loss ([volumes](https://docs.fly.io/volumes/overview)). Keep the SQLite backup from `docs/OPERATING.md` running somewhere off the host.

**Render.** The 15-minute spin-down and one-minute spin-up ([free](https://render.com/docs/free)) clash with Claude Code. `MCP_TIMEOUT`, the MCP server startup timeout, defaults to 30 seconds ([env vars](https://code.claude.com/docs/en/env-vars)). A Claude Code session that starts while the service is asleep will probably fail to connect to AIStack. Render's page says only that browsers see a loading page meanwhile, and does not say what non-browser clients receive.

**Cloud Run.** The free-tier numbers and the billing-account requirement come from [Google's free features page](https://docs.cloud.google.com/free/docs/free-cloud-features). The [pricing page](https://cloud.google.com/run/pricing) returned only its title to the fetcher, so the free tier's region list and its treatment of instance-based billing are unconfirmed. Idle instances are kept "up to 15 minutes", and the default minimum is 0 ([autoscaling](https://docs.cloud.google.com/run/docs/about-instance-autoscaling)). With request-based billing and AIStack's light traffic, usage should stay well inside the allowance. Setting min instances to 1 would keep the signing key alive but is billed as idle time, which was not costed here.

**Oracle.** The reclamation rule, the home-region rule, and the capacity errors are on [Always Free resources](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm). The payment verification step and the fixed home region are on [Sign up](https://docs.oracle.com/en-us/iaas/Content/GSG/Tasks/signingup_topic-Sign_Up_for_Free_Oracle_Cloud_Promotion.htm). The Free Tier FAQ (`oracle.com/cloud/free/faq/`) and `oracle.com/cloud/free/` returned HTTP 403, so the idle-account rules in the FAQ were not read first-hand.

## Changes worth making in AIStack

These came out of this research. The first two are done, and the third is documented as a workaround in `docs/OPERATING.md`.

- Add `pool_pre_ping=True` to the PostgreSQL branch of `build_engine`. Without it, the first request after the database closes idle connections fails. That happens with Neon's scale-to-zero, Prisma's 60-minute idle timeout, and any provider restart.
- Document in `docs/OPERATING.md` that AIStack must run as exactly one instance (`--max-instances=1`, `--ha=false`, max replicas 1), and that the Tailscale example can use `tailscale serve` for HTTPS.
- Consider whether the Docker `HEALTHCHECK` should touch the database. Its 30-second `SELECT 1` keeps a scale-to-zero database permanently awake, which on Neon's free plan uses up the month's compute in about 17 days.

## Sources

All read 2026-10-14.

PostgreSQL
- Neon pricing: https://neon.com/pricing
- Neon plans: https://neon.com/docs/introduction/plans
- Neon scale to zero: https://neon.com/docs/introduction/scale-to-zero
- Neon compute lifecycle: https://neon.com/docs/introduction/compute-lifecycle
- Neon connection pooling: https://neon.com/docs/connect/connection-pooling
- Neon secure connections: https://neon.com/docs/connect/connect-securely
- Neon regions: https://neon.com/docs/introduction/regions (`/docs/manage/regions` returned 404)
- Supabase pricing: https://supabase.com/pricing
- Supabase free plan pausing: https://supabase.com/docs/guides/platform/free-plan-pausing
- Supabase connecting to Postgres: https://supabase.com/docs/guides/database/connecting-to-postgres
- Supabase compute and disk: https://supabase.com/docs/guides/platform/compute-and-disk
- Supabase connection management: https://supabase.com/docs/guides/database/connection-management (no limits listed)
- Supabase regions: https://supabase.com/docs/guides/platform/regions
- Aiven free plan: https://aiven.io/docs/platform/concepts/free-plan
- Aiven PostgreSQL free tier: https://aiven.io/docs/products/postgresql/concepts/pg-free-tier (`/docs/platform/concepts/free-tier` returned 404)
- Prisma pricing: https://www.prisma.io/pricing
- Prisma Postgres direct connections: https://www.prisma.io/docs/postgres/database/direct-connections
- Xata pricing: https://xata.io/pricing
- CockroachDB pricing: https://www.cockroachlabs.com/pricing/
- CockroachDB PostgreSQL compatibility: https://docs.cockroachlabs.com/docs/stable/postgresql-compatibility
- CockroachDB online schema changes: https://docs.cockroachlabs.com/docs/stable/online-schema-changes
- Koyeb pricing: https://www.koyeb.com/pricing
- psycopg prepared statements: https://www.psycopg.org/psycopg3/docs/advanced/prepare.html
- psycopg connection API (`prepare_threshold` default 5): https://www.psycopg.org/psycopg3/docs/api/connections.html
- SQLAlchemy pooling, disconnects: https://docs.sqlalchemy.org/en/20/core/pooling.html

Hosts
- Fly.io pricing: https://docs.fly.io/about/pricing
- Fly.io app availability: https://docs.fly.io/apps/app-availability
- Fly.io volumes: https://docs.fly.io/volumes/overview
- Render free: https://render.com/docs/free
- Railway plans: https://docs.railway.com/reference/pricing/plans
- Railway app sleeping: https://docs.railway.com/reference/app-sleeping
- Koyeb instances: https://www.koyeb.com/docs/reference/instances
- Koyeb pricing FAQ: https://www.koyeb.com/docs/faqs/pricing
- Google Cloud free features: https://docs.cloud.google.com/free/docs/free-cloud-features
- Cloud Run pricing: https://cloud.google.com/run/pricing (did not render; title only)
- Cloud Run instance autoscaling: https://docs.cloud.google.com/run/docs/about-instance-autoscaling
- Cloud Run Cloud Storage volume mounts: https://docs.cloud.google.com/run/docs/configuring/services/cloud-storage-volume-mounts
- Google external IPv4 price change: https://cloud.google.com/vpc/pricing-announce-external-ips (`/vpc/network-pricing` did not render)
- Azure Container Apps pricing: https://azure.microsoft.com/en-us/pricing/details/container-apps/
- Azure Container Apps scaling: https://learn.microsoft.com/en-us/azure/container-apps/scale-app
- Azure Container Apps storage mounts: https://learn.microsoft.com/en-us/azure/container-apps/storage-mounts
- Oracle Always Free resources: https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm
- Oracle sign-up: https://docs.oracle.com/en-us/iaas/Content/GSG/Tasks/signingup_topic-Sign_Up_for_Free_Oracle_Cloud_Promotion.htm (FAQ and landing page returned 403)
- Hugging Face Spaces overview: https://huggingface.co/docs/hub/spaces-overview
- Hugging Face Docker Spaces: https://huggingface.co/docs/hub/spaces-sdks-docker
- Tailscale pricing: https://tailscale.com/pricing
- Tailscale Funnel: https://tailscale.com/kb/1223/funnel
- Tailscale Serve: https://tailscale.com/kb/1312/serve and https://tailscale.com/kb/1242/tailscale-serve
- Tailscale HTTPS certificates: https://tailscale.com/kb/1153/enabling-https
- Cloudflare Tunnel: https://developers.cloudflare.com/tunnel/
- Cloudflare Tunnel get started: https://developers.cloudflare.com/tunnel/get-started/
- Cloudflare Tunnels FAQ: https://developers.cloudflare.com/cloudflare-one/faq/cloudflare-tunnels-faq/
- Cloudflare Quick Tunnels: https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/
- Claude Code environment variables (`MCP_TIMEOUT` default 30000 ms): https://code.claude.com/docs/en/env-vars
