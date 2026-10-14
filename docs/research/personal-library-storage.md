# Where a solo user's Library can live

Researched 2026-10-14. Every provider claim cites the provider's own documentation, pricing page, API reference, or library repository, and every source was read on that date. Where a page did not answer a question, this report says so instead of guessing. It builds on [free-personal-hosting.md](free-personal-hosting.md), which covers free container hosts and free PostgreSQL (Neon, Supabase, Aiven, Prisma) for a single AIStack server. That ground is not repeated here.

The question: one person, several computers, one Library. As little setup as possible, ideally free, ideally with no computer that has to stay on. Something has to run AIStack's logic (validation, hashing, reconciliation, the dashboard). Either one server runs it and only its storage moves (family A), or every computer runs it locally and only the storage is shared (family B).

## Recommendation

**Offer three answers to "Where should your Library live?"**

| Choice | One-line guidance for the dashboard |
|---|---|
| **A computer that stays on** (today's server: your desktop, NAS, or mini PC with Tailscale, or about $3 a month on Fly.io) | "Free on a computer you already own, but it must stay on. The only choice that works for teams." |
| **Your GitHub account** (a private repository, AIStack running on each computer) | "Free, nothing to keep switched on, nothing pauses, and you can see every change on GitHub. Just for you: teams need a server." |
| **A free Neon or Supabase database** (AIStack running on each computer) | "Free and nothing to keep on, but you paste a database password into every computer. Supabase pauses after about a week unused (one click to wake). Neon wakes by itself. Just for you." |

**Teams fit only the first answer.** A team needs one trusted place that decides who sees what (`services/visibility.py`) and who pushed what. In every family-B option each computer holds a credential with full read and write access to the shared store, so a teammate given that store could read every private group and write any `pushed_by`. Teams stay a server feature. A solo user who later joins a team moves their Library onto that team's server. That needs an export and import path, which does not exist yet.

Rejected as chooser options, with the reason:

- **A plain synced folder (iCloud Drive, Dropbox, Google Drive desktop, OneDrive, Syncthing) holding the SQLite file.** SQLite's WAL mode needs every process on one host, and a sync program copying the database or its `-wal` file mid-transaction is a documented way to corrupt it ([WAL](https://www.sqlite.org/wal.html), [how to corrupt](https://www.sqlite.org/howtocorrupt.html)). Two computers writing between syncs produce two diverged files and a conflict copy, with no merge possible. A files-only layout in a synced folder can be made safe (see B3), and it needs no credential at all. It is the best candidate for a fourth choice later. It is not in the first three because sync programs give no ordering or atomicity, so a correct reader is more work than the Git version of the same layout, and iCloud may evict files from disk.
- **Turso.** As the server's database it solves nothing that Neon or Supabase does not already solve with today's driver. Read directly from each computer, its SQLAlchemy dialect depends on `libsql-experimental`, which publishes no Windows wheels, and the dialect's own README says "Linux and macOS" only ([PyPI](https://pypi.org/pypi/libsql-experimental/json), [libsql-sqlalchemy](https://github.com/tursodatabase/libsql-sqlalchemy)). AIStack supports Windows machines.
- **Cloudflare D1.** It is reachable from Workers or through a REST API that Cloudflare describes as interacting "primarily" with the control plane ([query D1](https://developers.cloudflare.com/d1/best-practices/query-d1/)). It has no Python SQLAlchemy path.
- **Google Drive API.** It is feasible, but Drive v3 has no compare-and-swap on files (the file `etag` is "n/a" in v3, per [v2-to-v3 reference](https://developers.google.com/workspace/drive/api/guides/v2-to-v3-reference)), so concurrent writers silently overwrite each other. It also needs an OAuth client that AIStack registers and maintains, and gives nothing the GitHub option does not.
- **Supabase Edge Functions as the server.** They run TypeScript on Deno ([functions](https://supabase.com/docs/guides/functions)). Running AIStack there means a second implementation of push validation and the content hash, which ADR-0011 exists to prevent. Python cannot run inside Supabase's Postgres either (below).
- **Firebase.** The Spark plan is free with no payment method, but Cloud Functions are not available on it, and Firestore's Python library bypasses Security Rules entirely ([pricing](https://firebase.google.com/pricing), [client libraries](https://firebase.google.com/docs/firestore/client/libraries)). It is the same trade as a Postgres password, with a new data model to write.

**Build order, if this goes ahead.** The cheapest family-B option to build is Neon or Supabase read directly from each computer. AIStack's services already run against PostgreSQL with concurrent writers, so the storage code does not change. What is new is a local entrypoint (stdio MCP plus a localhost dashboard), local machine identity in place of machine tokens, direct file I/O in place of transfer URLs, a migration lock, and a guard against version skew between computers. GitHub is the better product: no password to paste, no pause, visible history. But it needs a second storage backend, a files-only layout behind the same services, and that is a large piece of work. Building the files-only layout once also yields the synced-folder option almost for free.

## Comparison

"Off" means every one of the user's computers is switched off.

| Option | Setup a non-expert faces | Cost and free limits | Trial? | When every computer is off | Two computers writing at once | Who holds what credential | What AIStack must build | Verdict |
|---|---|---|---|---|---|---|---|---|
| **Own always-on machine + Tailscale** (existing) | Docker, Tailscale on every client, invite code | $0 | No | Nothing happens; the server is on | Server transactions (ADR-0014) | One machine token per computer | Nothing | **Offer.** Only option for teams |
| **Fly.io, one Machine** (existing) | Fly account, card, `fly deploy` | about $2.34 to $3.84 a month | 2 h or 7 days, then paid | Server stays up | Server transactions | One token per computer | Nothing | Offer as the paid variant of "a computer that stays on" |
| **A1. Free host + Supabase or Neon** | Two accounts, connection string, host config | $0 | No | Host sleeps; dashboard signs out on each wake | Server transactions | Tokens; DB password on the host only | Nothing (works with degradations) | Covered by the earlier report; not offered |
| **A2. Turso as the server's DB** | Turso account, token, URL | Free: 100 DBs, 5 GB, 500M rows read, 10M rows written a month, no card | No | Same as the host it sits behind | `BEGIN IMMEDIATE` over the network, 5 s interactive-transaction limit | Turso token on the host | New dialect; `libsql-experimental` has no Linux arm64 wheel, so the arm64 image breaks | Reject: adds nothing over Postgres |
| **A3. Cloudflare D1** | Cloudflare account | Free: 5M rows read and 100k written a day, 500 MB per DB | No | n/a | Batches are transactions; no interactive transactions stated | Cloudflare API token | A Workers rewrite, or the control-plane REST API | Reject |
| **B1. Private GitHub repository** | Sign in with a device code on each computer, install AIStack's GitHub App on one private repo | $0; unlimited private repos; 5,000 API requests an hour | No | Library sits on GitHub, untouched | Git rejects a non-fast-forward push; retry after fetch | A GitHub user token limited to that repo, on each computer | Files-only storage backend, local mode | **Offer** |
| **B2. Google Drive API** | Google sign-in on each computer | Free (user's Drive quota) | No | Library sits in Drive | No compare-and-swap in v3: last writer wins | Google OAuth refresh token on each computer | Files-only backend, OAuth client (non-sensitive scopes need no verification) | Reject for now |
| **B2. Dropbox API** | Dropbox sign-in on each computer | Free (user's quota) | No | Library sits in Dropbox | `update` mode with `rev` is a per-file compare-and-swap | Dropbox refresh token on each computer | Files-only backend, app registration, production approval past 50 users | Possible later |
| **B2. OneDrive (Microsoft Graph)** | Microsoft sign-in on each computer | Free (user's quota) | No | Library sits in OneDrive | `if-match` with eTag on update; 412 on mismatch | Microsoft refresh token | Files-only backend, Entra app registration | Possible later |
| **B3. Synced folder, SQLite file inside** | Pick the folder | $0 beyond the sync service | No | Folder sits in the cloud | Corruption or a forked file plus a conflict copy | None | Little code, but unsafe | **Reject** |
| **B3. Synced folder, files-only layout** | Pick the folder on each computer | $0 beyond the sync service | No | Folder sits in the cloud (Syncthing: only on devices that are on) | Write-once files and one writer per mutable file, so no conflicts by construction | None | Files-only backend, same as B1 | Strong later candidate |
| **B4. Neon or Supabase from each computer** | Create a project, copy a connection string, paste it on each computer | $0. Neon: 100 CU-hours a month, compute sleeps after 5 min, wakes itself. Supabase: 500 MB, paused after a week of low activity | No | Data sits in the database. Supabase may pause it | Postgres transactions, as today | The database password on every computer | Local mode only; storage code unchanged | **Offer** |
| **B4. Turso from each computer** | Turso account, token per DB | Free tier as A2 | No | Data sits in Turso. Docs disagree on archiving after 10 days | As A2 | Turso token on every computer | Local mode, a new dialect | Reject: no Windows support |
| **B5. Cloudflare R2** | Cloudflare account, R2 checkout step, API token | 10 GB-month, 1M Class A and 10M Class B operations a month | No | Data sits in R2 | Not researched in depth | S3 key on every computer | Files-only backend over S3 | Not credible for non-experts |
| **B5. Firebase Firestore (Spark)** | Firebase project, service account key | 1 GiB, 50k reads and 20k writes a day, no payment method | No | Data sits in Firestore | Firestore transactions | Service account key (full access) on every computer | A new data model | Reject |

## What changes when no server runs

These consequences hold for every family-B option. They are why family B is a second product mode, not a configuration switch.

**Something must start AIStack on each computer.** Claude Code starts local MCP servers itself over stdio: "Stdio servers run as local processes on your machine", added with `claude mcp add ... -- <command>` and given credentials with `--env` ([Claude Code MCP](https://code.claude.com/docs/en/mcp)). FastMCP uses stdio by default, and "the client spawns a new server process for each session" ([FastMCP running](https://gofastmcp.com/deployment/running-server)). Python is the obstacle. `uvx` runs a tool "without installing it" in an isolated environment ([uv tools](https://docs.astral.sh/uv/guides/tools/)), and uv "will automatically download Python versions if they cannot be found" ([uv Python versions](https://docs.astral.sh/uv/concepts/python-versions/)). So setup is "install uv, then `claude mcp add aistack -- uvx aistack`", one command more than today's paste.

**Several server mechanisms become unnecessary.** A local process can read and write the skills directory itself, so transfer URLs and tickets (ADR-0010) are not needed. File bytes still never pass through the model. There is no invite code and no machine token: whoever can start the process on that computer is the user. A machine needs a locally stored id instead.

**The dashboard has nowhere to live.** FastMCP's custom routes are "served by the same web server as your MCP endpoint", and a stdio server has no web server ([FastMCP running](https://gofastmcp.com/deployment/running-server)). The page would be served on `127.0.0.1` by a separate command (`uvx aistack dashboard`), or by a listener the stdio process opens while a session runs. It works only on the computer it runs on, and only while that process is up.

**Validation and hashing stop happening in one trusted place.** Each computer runs the same `services/` code, so the rules are identical as long as every computer runs the same AIStack version. But anything holding the storage credential can write without validating: an old AIStack version, a script, or the user by hand. The mitigation is cheap: validate and re-hash on read as well as on write. The install path would run push validation and `content_hash` over what it downloaded before writing to disk. For a single user this is an acceptable loss, because the only writer to fear is a buggy copy of AIStack.

**Version skew between computers becomes a correctness problem.** Today one server migrates its own database at startup (ADR-0016). With a shared PostgreSQL, the first computer to upgrade migrates the schema for every computer. A computer still on the older release then meets a schema whose revision its migration scripts do not contain, and must refuse to start rather than run against it (Alembic behaviour, not tested here). `migrate_schema` also takes no lock (`src/aistack/db/schema.py`), so two computers starting at once against an empty or outdated database would both try to migrate. On PostgreSQL that needs a `pg_advisory_xact_lock` before upgrading. Whether the current code fails cleanly without one was not tested.

**Teams do not work** (see Recommendation), and ADR-0015's Library-as-personal-team model assumes the team and the Library share one database. Mixing a family-B Library with a server-hosted team would need a cross-store take.

## Family A: one server, its storage elsewhere

### A1. Supabase, answered plainly

**Is the Free plan free indefinitely?** As far as the pages say, yes. It is listed at $0 a month with no trial period ([pricing](https://supabase.com/pricing)), and the cost-control page says "you will not be charged while using the Free Plan" ([cost control](https://supabase.com/docs/guides/platform/cost-control)). Free has no overage rates, so there is no pay-as-you-go surprise. **Whether signup needs a credit card is not stated** on the pricing, billing, or billing-FAQ pages read ([billing](https://supabase.com/docs/guides/platform/billing-on-supabase), [billing FAQ](https://supabase.com/docs/guides/platform/billing-faq)).

**Limits.** 500 MB database per project, 5 GB egress plus 5 GB cached egress, 1 GB file storage, 500,000 Edge Function invocations, two active projects ([pricing](https://supabase.com/pricing)). AIStack's data is small text: 500 MB is far beyond a personal Library.

**What happens at the limits.**

- Database size: "Free Plan projects enter read-only mode when your database size exceeds 500 MB", and writes fail with "cannot execute INSERT in a read-only transaction" ([database size](https://supabase.com/docs/guides/database/database-size)).
- Other quotas: exceeding them starts a grace period and an email. After that, the Fair Use Policy may apply: "Pausing projects, Switching databases to read-only mode, Disabling new project launches/transfers, Responding with a 402 status code for all API requests", generally across every project in the organization. The restrictions lift when the quota refills next billing cycle ([billing FAQ](https://supabase.com/docs/guides/platform/billing-faq)). **The grace period's length is not stated.**

**Inactivity pause.** Projects with "low activity over a 7-day period" are paused. "Typically a few user requests to the database each day over the previous week is enough" to avoid it. A warning email arrives "roughly one week before the pause takes effect", and visiting the project or generating traffic prevents it. A paused project can be restored "for up to 1 year after it was paused", to "its previous state, including data and configurations". The page's own heading says "90-day window", which contradicts its text ([pausing](https://supabase.com/docs/guides/platform/free-plan-pausing)). **How the API answers while a project is paused, and how long a restore takes, are not stated.** For a family-B user who stops coding for a fortnight, the likely experience is an email, then a failed sync until they click Restore.

**Can Supabase run server-side logic itself?** Only in TypeScript or SQL.

- Edge Functions use "Supabase Edge Runtime (Deno compatible runtime with TypeScript first)" and support WASM ([functions](https://supabase.com/docs/guides/functions)). They are limited to 256 MB of memory, "2 seconds" of CPU time per request, and a 150-second wall clock on Free ([limits](https://supabase.com/docs/guides/functions/limits)).
- Python is not available inside the database. Supabase removed `plpython3u` because "Untrusted extensions have unfettered access to the filesystem, networking" ([supabase/postgres PR #31](https://github.com/supabase/postgres/pull/31)). A January 2026 feature request still asks for native Python execution ([discussion #41990](https://github.com/orgs/supabase/discussions/41990)).

**Does it matter that AIStack is Python?** Yes. Running AIStack's logic on Supabase means rewriting push validation, the canonical content hash, reconciliation, and visibility in TypeScript. That gives two implementations of the rules whose single implementation ADR-0009 and ADR-0011 insist on. Supabase is useful to AIStack only as a PostgreSQL database.

### A2. Turso (hosted libSQL)

- **Free tier:** 100 databases, 5 GB, 500 million rows read and 10 million rows written a month, 3 GB of syncs, 1 day of point-in-time restore. "Start free, no credit card required" ([pricing](https://turso.tech/pricing)). What happens over the free limits is not stated.
- **Idle behaviour: the docs disagree.** The CLI reference says "Databases get archived after 10 days of inactivity for users on a free plan", restored with `turso group unarchive` ([unarchive](https://docs.turso.tech/cli/group/unarchive)). The March 2025 plan announcement says the Free plan has "No more cold starts!" and that databases "stay responsive at all times, regardless of how long they've been inactive" ([blog](https://turso.tech/blog/turso-cloud-debuts-the-new-developer-plan)). Which one holds today is unknown.
- **SQLAlchemy dialect:** `sqlalchemy-libsql` 0.2.0, classified "Development Status :: 4 - Beta", released 2025-05-30. It depends on `libsql-experimental>=0.0.53` ([PyPI](https://pypi.org/pypi/sqlalchemy-libsql/json)). `libsql-experimental` 0.0.55 ships wheels only for macOS and manylinux x86_64: no Windows and no Linux arm64 ([PyPI](https://pypi.org/pypi/libsql-experimental/json)). The repository README says "The package currently only supports Linux and macOS" and shows remote, local, and embedded-replica URLs ([libsql-sqlalchemy](https://github.com/tursodatabase/libsql-sqlalchemy)). Turso's own Python quickstart now recommends a different package, `pyturso`, and does not mention SQLAlchemy ([Python quickstart](https://docs.turso.tech/sdk/python/quickstart)).
- **Transactions:** Turso's client reference maps a `write` transaction to `BEGIN IMMEDIATE`. Interactive transactions "lock the database for writing until committed or rolled back, with a 5-second timeout" ([TS reference](https://docs.turso.tech/sdk/ts/reference)). So ADR-0014's semantics hold in principle. But every statement in an AIStack transaction becomes a network round trip under that write lock, and a push writes up to 100 file rows, so the 5-second ceiling is a real risk. Not measured.
- **WAL and pragmas:** Turso's PRAGMA reference lists `foreign_keys` as supported and off by default, and WAL as the supported journal mode ([pragmas](https://docs.turso.tech/sql-reference/pragmas)). Turso's issue tracker reports that PRAGMA names are case-sensitive, so `PRAGMA FOREIGN_KEYS = ON` is silently ignored ([issue #8736](https://github.com/tursodatabase/turso/issues/8736)). AIStack's connect hook sets WAL, the busy timeout, and foreign keys on every connection. Whether those statements are accepted on a remote libSQL connection, and whether `foreign_keys` holds across the client's streams, is untested. AIStack's cascades depend on it.
- **Embedded replicas** read locally and forward writes to the primary. Other replicas see a change only after `sync()`, and "Do not open the local database while the embedded replica is syncing" ([embedded replicas](https://docs.turso.tech/features/embedded-replicas/introduction)). That is a poor fit for several AIStack processes or threads sharing one file.
- **Tokens** can be read-only and can expire, but invalidation revokes "all tokens for a database", and the group's tokens too ([create](https://docs.turso.tech/cli/db/tokens/create), [invalidate](https://docs.turso.tech/cli/db/tokens/invalidate)). There is no per-computer revocation.

Verdict for family A: a server still has to run somewhere, and for that server Neon or Supabase over the existing psycopg driver are simpler and proven in CI. Turso adds a beta dialect, a missing arm64 wheel, and untested pragma behaviour.

### A3. Cloudflare D1

- **Free limits:** 5 million rows read and 100,000 rows written a day, 5 GB in total, reset at 00:00 UTC. Over the limit, "D1 API will return errors" until the reset ([pricing](https://developers.cloudflare.com/d1/platform/pricing/)). Free accounts get 10 databases of at most 500 MB each, and 50 queries per Worker invocation ([limits](https://developers.cloudflare.com/d1/platform/limits/)).
- **Reachability:** from a Worker binding, or the REST API, which "primarily interacts with the control plane" ([query D1](https://developers.cloudflare.com/d1/best-practices/query-d1/)). Requests to the Cloudflare API "must resolve in 30 seconds" ([limits](https://developers.cloudflare.com/d1/platform/limits/)).
- **Transactions:** "D1 operates in auto-commit", and a batch is "SQL transactions" that roll back as a whole on failure ([D1 database API](https://developers.cloudflare.com/d1/worker-api/d1-database/)). The page does not mention interactive `BEGIN`/`COMMIT`. AIStack's services read, decide, and write inside one transaction, so they cannot be expressed as batches without restructuring.
- **Python Workers** exist and name FastAPI and Pydantic among supported packages ([Python Workers](https://developers.cloudflare.com/workers/languages/python/)). The page does not say whether a synchronous SQLAlchemy driver could run there, and the Free plan's "10 milliseconds of CPU time per invocation" ([Workers pricing](https://developers.cloudflare.com/workers/platform/pricing/)) is far below what tar parsing and validation need.

Verdict: not reachable from AIStack as it is built.

## Family B: AIStack on every computer, only storage shared

### B1. A private Git repository on GitHub (or GitLab)

**Cost and limits.** GitHub Free is "$0 per month forever" with unlimited private repositories ([pricing](https://github.com/pricing)). Recommended limits are a 10 GB repository, at most 3,000 entries per directory, and 1 MB per object (100 MB enforced) ([repository limits](https://docs.github.com/en/repositories/creating-and-managing-repositories/repository-limits)). Skills are at most 1 MiB, so none of this binds. The REST API allows 5,000 requests an hour for a user token, plus a secondary limit of 80 content-creating requests a minute and 500 an hour ([rate limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api)). A sync is a few requests, and a push of one skill is one commit, so a person never comes close. GitLab.com Free gives each project 10 GiB, after which it becomes read-only, and allows 5 users per private top-level group ([storage](https://docs.gitlab.com/user/storage_usage_quotas/), [pricing](https://about.gitlab.com/pricing/)).

**Authentication, from best to worst for a non-expert.**

1. **AIStack's own GitHub App with the device flow.** The computer shows a code, and the user enters it at `github.com/login/device`. "The `client_secret` is not needed for the device flow" ([OAuth device flow](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps)), and refreshing a token needs no secret either: the secret is "Required unless the user access token was generated using the device flow" ([refreshing](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/refreshing-user-access-tokens)). The token "can only access resources that both the user and app can access", so if the user installs the app on one repository, the token on each laptop reaches only that repository. It expires after 8 hours, and its refresh token after 6 months ([user access tokens](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-a-user-access-token-for-a-github-app)). An open-source project can publish the app's client id, because the device flow needs nothing secret. The cost is that the AIStack project must own and maintain a GitHub App.
2. **A fine-grained personal access token.** It can be limited to "Only select repositories" with Contents read and write, and its lifetime can be up to 366 days or none, unless a policy blocks that. Creating one takes 14 numbered steps in the web UI ([PATs](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens)). That is too many for the target user.
3. **Reusing `gh`'s login.** The `gh` CLI stores its token in the system credential store, or falls back to a plain-text file, and its minimum scopes are `repo`, `read:org`, and `gist` ([gh auth login](https://cli.github.com/manual/gh_auth_login)). `repo` "Grants full access to public and private repositories", and no OAuth scope narrows to one repository ([scopes](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/scopes-for-oauth-apps)). Convenient, but it gives AIStack every repository the user has.

**Git or the REST API.** Plain `git` is not guaranteed on Windows: Git for Windows is optional for Claude Code ([Claude Code setup](https://code.claude.com/docs/en/setup)). The REST API avoids that dependency. The Contents API is a poor fit, because concurrent create or update calls "will conflict" and "You must use these endpoints serially" ([contents](https://docs.github.com/en/rest/repos/contents)). The Git database API fits: create blobs, a tree, and a commit, then update the branch ref with `force` false, which by default "make[s] sure you're not overwriting work" ([refs](https://docs.github.com/en/rest/git/refs)). That ref update is a compare-and-swap over the whole Library. The status code for a rejected non-fast-forward is not named on the page. With `git` itself, a push that is not a fast-forward is rejected by default ([git-push](https://git-scm.com/docs/git-push)).

**Concurrency between two computers.** At most one commit wins a race, and the loser retries on top of the new head. With the files-only layout below, no two computers ever write the same path, so the retry never meets a textual conflict. History is free: every revision is a commit the user can browse on github.com.

**When every computer is off:** the Library sits on GitHub, and nothing sleeps or pauses.

**Security:** each computer holds a token scoped to one repository. A stolen laptop is handled by revoking that authorization in GitHub's settings, which also signs out the user's other computers when they share the same app authorization. Not checked in detail.

**Cost to AIStack:** a second storage backend behind the services, the files-only layout, the device-flow sign-in, and local mode. Reconciliation (`services/reconciliation.py`), push validation, and `content_hash` are pure functions and carry over unchanged. Everything that queries SQLAlchemy does not.

### B2. Google Drive, and briefly Dropbox and OneDrive

**Google Drive API v3.**

- **Scopes:** `drive.file` and `drive.appdata` are non-sensitive, while `drive` and `drive.readonly` are restricted, and restricted scopes on a server need a security assessment ([scopes](https://developers.google.com/workspace/drive/api/guides/api-specific-auth)). With only non-sensitive scopes, "it is not mandatory for your app to complete the app verification process", though showing a name and logo needs a lighter brand verification ([verification](https://support.google.com/cloud/answer/13463073)). So an open-source AIStack could ship one Google OAuth client using non-sensitive scopes without Google's review. For installed apps "the client secret is obviously not treated as a secret". An app left in Testing status gets refresh tokens that expire in 7 days, and each account is limited to 100 refresh tokens per client ([OAuth 2.0](https://developers.google.com/identity/protocols/oauth2)).
- **`appDataFolder`** is hidden from the user, reachable only by "the application that created the data", cannot be shared, moved, or trashed, and is deleted when the user uninstalls the app ([appdata](https://developers.google.com/workspace/drive/api/guides/appdata)). A Library the user cannot see in Drive is a poor match for "your data is yours". `drive.file`, which shows the files in the user's Drive, fits better.
- **Quotas:** 1,000,000 quota units a minute per project and 325,000 per user, with an update costing 50 units and a download 200 ([limits](https://developers.google.com/workspace/drive/api/guides/limits)). There is plenty of headroom.
- **Concurrency:** a file is identified by "A unique, opaque ID" ([files](https://developers.google.com/workspace/drive/api/guides/about-files)). The page does not say whether names are unique within a folder, so two computers creating the same name may produce two files. Drive v3 has no file ETag ([v2-to-v3](https://developers.google.com/workspace/drive/api/guides/v2-to-v3-reference)), and `files.update` documents no precondition parameter ([files.update](https://developers.google.com/workspace/drive/api/reference/rest/v3/files/update)). Overwrites are last-writer-wins with no detection.
- **Revisions:** for blob files, older revisions are "typically preserved for 30 days" or purged once there are 100. Up to 200 revisions can be kept forever ([revisions](https://developers.google.com/workspace/drive/api/guides/manage-revisions)). That is unusable as AIStack's history, which must keep every revision.

**Dropbox.** An "App folder" permission confines the app to its own folder, and PKCE replaces the client secret for open-source and desktop apps ([OAuth guide](https://docs.dropboxapi.com/dropbox-api/docs/oauth)). Uploads in `update` mode carry the file's last known `rev`, and with `strict_conflict` a mismatch is always a conflict. With `autorename` the server saves a "conflicted copy" instead ([SDK CommitInfo](https://dropbox.github.io/dropbox-sdk-java/api-docs/v5.4.3/com/dropbox/core/v2/files/CommitInfo.html)). That is a real per-file compare-and-swap, better than Drive. A new app is in development status for up to 500 users. Once 50 users link it, it has two weeks to win production approval or new links freeze ([developer guide](https://www.dropbox.com/developers/reference/developer-guide)). An open-source project would need to own that approval.

**OneDrive (Microsoft Graph).** `Files.ReadWrite.AppFolder` grants a folder under `Apps` in the user's OneDrive, and the user can see, rename, or move it ([app folder](https://learn.microsoft.com/en-us/onedrive/developer/rest-api/concepts/special-folders-appfolder)). Updating an item accepts `if-match`, and a stale eTag returns `412 Precondition Failed` ([driveItem update](https://learn.microsoft.com/en-us/graph/api/driveitem-update)). The content-upload page does not list `if-match` ([put content](https://learn.microsoft.com/en-us/graph/api/driveitem-put-content)), so whether content writes can be conditional is not confirmed.

**Verdict:** all three need AIStack to own a registered OAuth client per provider. None offers a whole-Library compare-and-swap the way a Git ref does. Drive offers no compare-and-swap at all. They would only make sense behind the same files-only layout as B1, which is designed not to need compare-and-swap. If one is added later, Dropbox's `rev` semantics make it the safest.

### B3. A plain synced folder

**Why the SQLite file corrupts or forks.**

- WAL needs every process on one host: "WAL does not work over a network filesystem", because the wal-index is shared memory ([WAL](https://www.sqlite.org/wal.html)). Two computers each open their own local copy of the synced file, so neither sees the other's lock.
- A sync program copying the database "while it is in the middle of a transaction" can produce a copy with "some old and some new content, and thus be corrupt". Separating the database from its `-wal` or journal, or replacing one file without the other, also corrupts it ([how to corrupt](https://www.sqlite.org/howtocorrupt.html)). Sync programs move the two files independently.
- SQLite's own advice for data shared across machines is "a client/server database engine", or a proxy on the machine that holds the file ([SQLite over a network](https://www.sqlite.org/useovernet.html)).
- Two computers writing between syncs is a conflict for the sync program. Dropbox adds "conflicted copy" to one of them ([Dropbox](https://help.dropbox.com/organize/conflicted-copy)). Syncthing renames the one with the older modification time to `<name>.sync-conflict-<date>-<time>-<modifiedBy>.<ext>`, and a modification against a deletion is handled the same way ([Syncthing](https://docs.syncthing.net/users/syncing.html)). Neither can merge two SQLite files, so one computer's writes are stranded in the copy.

**Would a files-only layout be safe?** Yes, if it follows three rules. Each rule removes a conflict the sync program cannot resolve.

1. **Every revision is write-once and content-addressed.** For example, `skills/<name>/revisions/<content_hash>/` holds the files plus a `manifest.json` written last, listing each path, its sha256, its executable bit, `pushed_by` (the machine), and the time. Two computers pushing identical content write identical bytes to the same path, so that is not a conflict. Two computers pushing different content write different paths. A reader trusts a revision only when every file is present and `content_hash` recomputes to the folder name. Partial arrival, which sync programs allow because they guarantee no ordering, then looks like "not there yet" rather than a corrupt skill.
2. **Every mutable file has exactly one writer.** `machines/<machine_id>.json` holds that machine's enabled and disabled decisions and is written only by that machine. A change made on another computer's dashboard ("put this skill on my laptop") is written as a new request file in `machines/<target>/requests/`, which the target applies and deletes at its next sync. Library-level state (archived, origin) lives in per-machine append-only event files, merged by reading all of them.
3. **Nothing needs a global counter.** Server revisions are integers allocated in a transaction. Here, the order comes from the manifests' timestamps with the machine id as a tie-break. Two near-simultaneous pushes of one skill both survive as revisions, and the later one is latest. That is what the server does today when two machines push one after the other: the earlier pusher's next sync finds an older revision and updates silently. The losing content stays in history.

Under those rules a conflict copy can only appear if the user edits a file inside the store by hand. The reader ignores names it did not write, such as `*.sync-conflict-*` and `* (conflicted copy)*`, and can report them.

**Remaining risks:**

- iCloud's Optimize Mac Storage stores "older documents" only in iCloud when space is needed, unless a folder is marked "Keep Downloaded" ([Apple: iCloud Drive on Mac](https://support.apple.com/guide/mac-help/store-files-in-icloud-drive-mchle5a61431/mac)). Whether a plain `read()` of an evicted file blocks and downloads it, or fails, was not established.
- Syncthing moves data only between devices that are on at the same time, so "every computer off" means nothing moves (no cloud copy exists).
- A work laptop often cannot run a personal sync client.

**Credentials:** none in AIStack at all. That is the option's real appeal. **Cost to AIStack:** the same files-only backend as B1, plus a filesystem transport.

### B4. Neon, Supabase, or Turso from each computer, with the user's own credentials

**What works today.** AIStack's services already run on PostgreSQL with several concurrent writers: the suite runs against both databases, and concurrency is handled by `BEGIN`/savepoints, the unique `(skill_id, revision)` retry, and ADR-0008's partial index. Several local processes against one Neon or Supabase database is therefore the configuration AIStack already supports, with the processes moved onto laptops. The earlier report's connection advice holds: Supabase through the session pooler on port 5432 (direct is IPv6-only on Free), Neon on its direct endpoint ([free-personal-hosting.md](free-personal-hosting.md)).

**Neon or Supabase for this.** In family B nothing pings the database between syncs.

- Neon's compute suspends after 5 minutes idle and wakes on the next connection. Running out of CU-hours suspends compute "until the next billing period", and "None of these limits delete your data". Neon's plans page mentions archiving of inactive branches only, not projects ([Neon plans](https://neon.com/docs/introduction/plans)).
- Supabase pauses after a week of low activity and needs a click to restore (A1).

For a user who may not code for a week, Neon is the gentler choice. Supabase gives more of everything else.

**The security trade-off that remains.** There is one user, so there is no multi-tenant authorization problem. But every laptop holds the database password, which is full read and write access to the Library: every table, with no per-machine scope. Losing a laptop means changing the password and pasting the new connection string on every other computer. Today it means rotating one machine token. Supabase's alternative does not help a Python client:

- The publishable (formerly anon) key is "Safe to expose" but only reaches data through Row Level Security and Supabase Auth sessions ([API keys](https://supabase.com/docs/guides/api/api-keys)). That means writing RLS policies for all eleven tables and going through PostgREST instead of SQLAlchemy. RLS also requires care: "A table in an exposed schema without RLS is readable and writable by any role with a grant on it" ([RLS](https://supabase.com/docs/guides/database/postgres/row-level-security)).
- The secret (formerly service_role) key "bypasses every Row Level Security policy" and must never go in "a shipped application" ([API keys](https://supabase.com/docs/guides/api/api-keys)).
- Either way, the Postgres password is the honest equivalent: simplest, and as powerful as a secret key.

**Turso from each computer** would give one token per database, which can be read-only and can expire, but which is revoked only all at once ([create](https://docs.turso.tech/cli/db/tokens/create), [invalidate](https://docs.turso.tech/cli/db/tokens/invalidate)). The dialect's Linux-and-macOS-only driver excludes Windows computers (A2). Rejected.

**Cost to AIStack:** local mode only (see "What changes when no server runs"), plus the migration lock and version-skew guard. Storage code is unchanged.

### B5. Others

- **Cloudflare R2:** 10 GB-month, 1 million Class A and 10 million Class B operations a month, free egress ([R2 pricing](https://developers.cloudflare.com/r2/pricing/)). But "You need a Cloudflare account with an R2 subscription", added through a checkout flow ([R2 get started](https://developers.cloudflare.com/r2/get-started/)). Whether that checkout needs a payment method is not stated. Each computer would hold an S3-style key for the bucket. It would work behind the files-only layout. For a non-expert it is an account, a checkout, and a key to paste, which is worse than GitHub's device code. Durable Objects with SQLite storage are on the Workers Free plan (100,000 requests and 100,000 rows written a day) ([Workers pricing](https://developers.cloudflare.com/workers/platform/pricing/)), but using them means writing AIStack's server in a Worker. Not credible as a near-zero-config option.
- **Firebase (Spark):** "No payment method needed". Firestore Standard gives 1 GiB stored, 50,000 reads and 20,000 writes a day, and Cloud Functions and Cloud Storage are "Not applicable" on Spark ([pricing](https://firebase.google.com/pricing)). Security Rules protect only the Android, iOS, and web SDKs. The Python library runs where "requests are not evaluated against your Firebase security rules" ([client libraries](https://firebase.google.com/docs/firestore/client/libraries)), so every laptop would hold a service account key with full access. It is the B4 trade with a new data model to write. Rejected.

## Open questions this research could not close

- Whether Supabase's Free signup requires a card, how long its quota grace period lasts, how a paused project answers API calls, and how long a restore takes.
- Whether Turso's free databases are archived after 10 days (CLI docs) or never go cold (March 2025 announcement), and what happens over Turso's free limits.
- Whether AIStack's SQLite pragmas are accepted, and hold, on a remote libSQL connection.
- Whether two AIStack processes migrating one PostgreSQL database at the same moment fail cleanly without an advisory lock.
- Whether reading an iCloud-evicted file blocks and downloads it, or fails.
- Whether OneDrive content uploads honour `if-match`, and which status GitHub returns for a rejected non-fast-forward ref update.
- Whether revoking a GitHub App authorization can be done per computer.

## Sources

All read 2026-10-14.

Repository
- `AGENTS.md`, `CONTEXT.md`, `docs/DESIGN.md`, `docs/OPERATING.md`, `docs/research/free-personal-hosting.md`, `src/aistack/db/schema.py`

Supabase
- Pricing: https://supabase.com/pricing
- About billing: https://supabase.com/docs/guides/platform/billing-on-supabase
- Billing FAQ (Fair Use Policy, restrictions): https://supabase.com/docs/guides/platform/billing-faq
- Cost control ("you will not be charged while using the Free Plan"): https://supabase.com/docs/guides/platform/cost-control
- Free plan pausing: https://supabase.com/docs/guides/platform/free-plan-pausing
- Database size (read-only over 500 MB): https://supabase.com/docs/guides/database/database-size
- Edge Functions overview: https://supabase.com/docs/guides/functions
- Edge Functions limits: https://supabase.com/docs/guides/functions/limits
- Extensions: https://supabase.com/docs/guides/database/extensions (lists no languages)
- plpython3u removal: https://github.com/supabase/postgres/pull/31
- Native Python request: https://github.com/orgs/supabase/discussions/41990
- API keys: https://supabase.com/docs/guides/api/api-keys
- Row Level Security: https://supabase.com/docs/guides/database/postgres/row-level-security

Neon
- Plans: https://neon.com/docs/introduction/plans

Turso
- Pricing: https://turso.tech/pricing
- Free plan announcement (March 2025): https://turso.tech/blog/turso-cloud-debuts-the-new-developer-plan
- Group unarchive (10-day archiving): https://docs.turso.tech/cli/group/unarchive
- Embedded replicas: https://docs.turso.tech/features/embedded-replicas/introduction
- TypeScript SDK reference (transaction modes): https://docs.turso.tech/sdk/ts/reference
- Python quickstart: https://docs.turso.tech/sdk/python/quickstart
- PRAGMA reference: https://docs.turso.tech/sql-reference/pragmas
- PRAGMA case-sensitivity issue: https://github.com/tursodatabase/turso/issues/8736
- Token create: https://docs.turso.tech/cli/db/tokens/create
- Token invalidate: https://docs.turso.tech/cli/db/tokens/invalidate
- libsql-sqlalchemy: https://github.com/tursodatabase/libsql-sqlalchemy
- PyPI JSON for `sqlalchemy-libsql`, `libsql-experimental`, `libsql`: https://pypi.org/pypi/sqlalchemy-libsql/json, https://pypi.org/pypi/libsql-experimental/json, https://pypi.org/pypi/libsql/json

Cloudflare
- D1 pricing: https://developers.cloudflare.com/d1/platform/pricing/
- D1 limits: https://developers.cloudflare.com/d1/platform/limits/
- Query D1: https://developers.cloudflare.com/d1/best-practices/query-d1/
- D1 database API: https://developers.cloudflare.com/d1/worker-api/d1-database/
- Python Workers: https://developers.cloudflare.com/workers/languages/python/
- Workers pricing: https://developers.cloudflare.com/workers/platform/pricing/
- R2 pricing: https://developers.cloudflare.com/r2/pricing/
- R2 get started: https://developers.cloudflare.com/r2/get-started/

GitHub, GitLab, Git
- GitHub pricing: https://github.com/pricing
- REST rate limits: https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api
- Repository contents API: https://docs.github.com/en/rest/repos/contents
- Git references API: https://docs.github.com/en/rest/git/refs
- Repository limits: https://docs.github.com/en/repositories/creating-and-managing-repositories/repository-limits
- Authorizing OAuth apps (device flow): https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps
- OAuth scopes: https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/scopes-for-oauth-apps
- GitHub App user access tokens: https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-a-user-access-token-for-a-github-app
- Refreshing user access tokens: https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/refreshing-user-access-tokens
- Personal access tokens: https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens
- gh auth login: https://cli.github.com/manual/gh_auth_login
- git-push: https://git-scm.com/docs/git-push
- GitLab storage quotas: https://docs.gitlab.com/user/storage_usage_quotas/
- GitLab pricing: https://about.gitlab.com/pricing/

Google
- Drive appDataFolder: https://developers.google.com/workspace/drive/api/guides/appdata
- Drive scopes: https://developers.google.com/workspace/drive/api/guides/api-specific-auth
- Drive usage limits: https://developers.google.com/workspace/drive/api/guides/limits
- Drive revisions: https://developers.google.com/workspace/drive/api/guides/manage-revisions
- Drive files overview: https://developers.google.com/workspace/drive/api/guides/about-files
- Drive v2 to v3 reference: https://developers.google.com/workspace/drive/api/guides/v2-to-v3-reference
- Drive files.update: https://developers.google.com/workspace/drive/api/reference/rest/v3/files/update
- OAuth app verification: https://support.google.com/cloud/answer/13463073
- OAuth 2.0 overview: https://developers.google.com/identity/protocols/oauth2

Dropbox and Microsoft
- Dropbox OAuth guide: https://docs.dropboxapi.com/dropbox-api/docs/oauth
- Dropbox SDK CommitInfo (update mode, strict_conflict, autorename): https://dropbox.github.io/dropbox-sdk-java/api-docs/v5.4.3/com/dropbox/core/v2/files/CommitInfo.html
- Dropbox developer guide (development and production status): https://www.dropbox.com/developers/reference/developer-guide
- Dropbox conflicted copies: https://help.dropbox.com/organize/conflicted-copy
- OneDrive app folder: https://learn.microsoft.com/en-us/onedrive/developer/rest-api/concepts/special-folders-appfolder
- Graph driveItem update (if-match): https://learn.microsoft.com/en-us/graph/api/driveitem-update
- Graph upload small files: https://learn.microsoft.com/en-us/graph/api/driveitem-put-content

Synced folders and SQLite
- SQLite WAL: https://www.sqlite.org/wal.html
- How to corrupt an SQLite database: https://www.sqlite.org/howtocorrupt.html
- SQLite over a network: https://www.sqlite.org/useovernet.html
- Syncthing syncing and conflicts: https://docs.syncthing.net/users/syncing.html
- Apple, iCloud Drive on Mac: https://support.apple.com/guide/mac-help/store-files-in-icloud-drive-mchle5a61431/mac

Firebase
- Pricing: https://firebase.google.com/pricing
- Firestore client libraries: https://firebase.google.com/docs/firestore/client/libraries

Local mode
- Claude Code MCP (stdio servers): https://code.claude.com/docs/en/mcp
- Claude Code setup (Git for Windows optional): https://code.claude.com/docs/en/setup
- FastMCP running a server (stdio default, custom routes on HTTP): https://gofastmcp.com/deployment/running-server
- uv tools (`uvx`): https://docs.astral.sh/uv/guides/tools/
- uv Python versions (automatic downloads): https://docs.astral.sh/uv/concepts/python-versions/
