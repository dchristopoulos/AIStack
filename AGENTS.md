## What this is

AIStack: a self-hosted, open-source control plane for AI dev configuration (skills first; rules, agents, hooks, MCPs later). The web dashboard is the product; MCP is the connector that links a person's coding agent to their account. Each user has a private space, the Library, that mirrors their machines, and shares with teams and groups from there (ADR-0015).

## Read before designing or implementing anything

- `docs/DESIGN.md` — the plan: scope, the thirteen MCP tools, flows, the sync contract, push validation, teams and groups, the dashboard, DB schema, project structure, roadmap. Where anything conflicts with it, this document wins.
- `docs/design-system.md` — read first for any work on the dashboard page: tokens, components, patterns, and what to avoid.
- `CONTEXT.md` — domain glossary. Use these terms exactly; respect the `_Avoid_` lists.
- `docs/adr/` — decisions already made (full sync not proxy, SQLite default, token auth, server-side desired state, signed transfer URLs, server-side hashing, personal space and teams, migrations, the dashboard). Do not relitigate them; write a new ADR to reverse one.

## Tech stack

Python 3.13, Poetry, SQLAlchemy, Alembic, FastMCP. SQLite by default, Postgres via `DATABASE_URL` (ADR-0002) — code must run identically on both. No FastAPI and no front-end build: the dashboard is one HTML file shipped as package data, and its JSON routes are Starlette routes on the app FastMCP already is (ADR-0017).

## Structure

Layered layout under `src/aistack/` (see `docs/DESIGN.md` §8): MCP tool handlers in `mcp/tools/`, the transfer, setup, and health routes in `mcp/routes/`, and the dashboard's routes in `api/dashboard.py` stay thin; business logic goes in `services/`; models in `db/models/`. Put code in its layer even while layers are thin.

## Conventions

### Code shape

- Keep the normal flow readable from top to bottom. Use short docstrings for contracts, and inline comments for non-obvious security, transaction, or portability constraints. Link to the ADR for longer reasoning instead of repeating it in each layer. Use one argument per line for multiline constructors and calls; avoid manual alignment under long names.
- `[project].dependencies` takes PEP 508 ranges, not Poetry carets; dev tools live in `[dependency-groups]`. `requires-python` carries a `<4.0` upper bound because a transitive dependency does and Poetry cannot resolve against an open floor. `fastmcp` is pinned exactly — the ticket #1 spike results are statements about one release, and a silent minor bump invalidates them. Everything else gets a compatible range and the lock file does the pinning.

### Database and transactions

- Synchronous SQLAlchemy (ADR-0005): plain `def` tools — FastMCP threadpools them. Never write an `async def` tool that calls a blocking driver; that serializes every caller. Where an async signature is forced on you (the `TokenVerifier`), push the database work through `asyncio.to_thread`.
- The session factory lives in `db/`; `bootstrap/context/` holds the singleton. A tool opens exactly one session per call as `with session_factory.begin() as session:` and passes it down; services never open their own. One MCP call is one transaction, and one transfer request is one transaction. The single exception is the auth token verifier, which owns a short-lived read session because it runs before tool dispatch.
- On SQLite the driver opens no transactions (`isolation_level = None`) and SQLAlchemy opens each one with `BEGIN IMMEDIATE` (ADR-0014). That is what makes a second writer wait instead of failing with "database is locked", and what keeps savepoints inside the outer transaction. The connect hook applies WAL, an explicit 5s busy timeout, and `PRAGMA foreign_keys=ON` (cascades silently don't fire without it).
- Every SQLite transaction holds the write lock from its first statement, so nothing slow may happen inside one: no archive parsing, no network call, no sleeping. Validate before the first query. A transaction held open across slow work blocks every other request for as long as it lasts.
- The engine module branches on dialect internally and exposes one `build_engine(database_url)`. Callers never learn which database they are on. No engine, connection, or `migrate_schema` at import time; `application_context` calls them during assembly.
- Read a stored timestamp through `as_utc()` in `db/models/timestamps.py` before doing arithmetic on it. SQLite returns naive datetimes and Postgres aware ones; `.timestamp()` on a naive value silently assumes local time.
- Enforce column lengths in the application. SQLite accepts oversized `VARCHAR(n)`, Postgres rejects it, so unenforced lengths break "runs identically on both".

### Migrations

- A schema change is a new numbered file in `src/aistack/db/migrations/versions/` plus the model change, in the same commit (ADR-0016). `migrate_schema` is the only thing that creates or alters a table, tests included, and a test fails when models and migrations disagree. Never edit a migration that has shipped, the baseline above all. No downgrades.
- Every migration sets `older_releases_compatible` (ADR-0024). `True` only when a release that knows the schema before it still works after it: a new table, a nullable or defaulted column, an index. Anything that removes, renames, or reshapes is `False`, and is split expand-then-contract across releases, so the release that adds the new shape stays compatible and a later one removes the old. Computers on one shared database update at different times.
- A migration never imports a model. The model describes the newest schema and the migration runs against an older one, so it declares the columns it touches with `sa.table`.
- Every pending migration runs in one transaction opened by `migrate_schema`, so a migration never commits, and a failure stops the server with the database as it was.
- Read a generated migration before keeping it. Autogenerate renders an index predicate as text in whichever dialect produced it, so `is_admin IS 1` reaches PostgreSQL as a syntax error; write predicates as expressions. Run the suite against PostgreSQL before committing a migration, because SQLite alone will not show this.
- On SQLite a batch migration drops and rebuilds the table, and with foreign keys on that drop cascades into every table that references it. `migrate_schema` turns enforcement off for the upgrade and runs `PRAGMA foreign_key_check` before commit. Do not run a migration any other way.

### Authorization

- Tools declare no authorization of their own. One `AuthMiddleware` holds the whole rule, so a new tool is covered by default and forgetting falls closed — FastMCP's per-component `auth=` is opt-in, and a tool registered without it carries no check at all, which makes it listed and callable by any authenticated principal, including the bootstrap one whose bearer is a static code everyone on the server holds. Reaching the invite-code half is `tags={ONBOARDING_TAG}` on the tool, and adding a name to `BOOTSTRAP_ONLY_TOOLS` in `tests/mcp/test_tool_authorization.py` is the decision that a tool is reachable with nothing but the invite code.
- Authorization is one `AuthMiddleware(auth=authorize)` on the server, where `authorize` is the single branch in `mcp/auth/policy.py` — `bootstrap` on anything tagged `onboarding`, `machine` on everything else. It is keyed on the tag and not the tool name so a rename cannot silently reclassify a tool. Unauthorized tools are omitted from `tools/list`, not merely rejected on call. AIStack's `TokenVerifier` resolves the bearer and returns `machine_id` and `user_id` as claims, so no tool re-queries identity.
- A machine-scope tool learns its caller from `current_machine()` in `mcp/auth/principal.py`, never from an argument and never from a query. A tool that takes a `user_id` or `machine_id` parameter is a bug: the caller could name someone else.

### Secrets and logs

- Caller-supplied values are escaped before they reach a log line or an error message. `commons/text.py`: `sanitized()` for a whole message, `loggable()` for one argument, which also caps its length. Both sinks read newlines as structure, so an unescaped one forges a log line for the operator and a turn for the agent, and these run on the rejection path, where nothing has validated the value yet. `AIStackError` sanitizes its own message, so a service cannot reintroduce this by forgetting.
- Secrets: a token is `f"aist_{secrets.token_urlsafe(32)}"`, stored only as its sha256, and appears only in the `join`/`add_machine` result — never in logs, errors, or any other tool result. The server's invite code exists only as operator-supplied config and as the bootstrap `Authorization` bearer: never in logs, errors, tool arguments, tool results, or startup output. An invalid-auth error never echoes the presented bearer.
- A team's invite code is `aistinv_` plus random text, made by the server, stored only as its sha256 in `invite.code_hash`, and returned once by `invite_to_team`. It is never logged, and a rejected one is never echoed: a near-miss of a real code is still a secret. Each invite is its own row (ADR-0022): one use, seven days, cancellable on its own. A used, cancelled, expired and unknown code all answer alike, and the update that uses one is conditional on it still being pending.
- Constant-time comparison applies to the server's invite code only (`hmac.compare_digest` over sha256 digests). A machine token and a team invite code are resolved by indexed lookup on their hash, where nothing is compared in Python. Do not "fix" that asymmetry into a table scan.
- The error decorator logs the tool name and error, never reflected call arguments. Unexpected tracebacks are rendered and escaped before logging; `logger.exception()` would append the unescaped exception chain.
- Internal token-bearing models exclude the credential from repr. Keep the SDK's raw token field for authentication, and expose the machine token only in the authorized tool result.
- The invite code is a pydantic `SecretStr`, and it is validated by a plain function called during context assembly, never by a pydantic validator: pydantic embeds the rejected input in its `ValidationError`, so a field validator on that value writes the secret into startup output.
- Third-party loggers that print raw protocol payloads (`mcp.client`, `mcp.server.streamable_http`, `sse_starlette`, `httpcore`, `httpx`) are floored at INFO in `bootstrap/__main__.py`. A tool result carrying a machine token goes over the wire in plaintext by definition, so at DEBUG those libraries write the token to the log file. Add to that list, never remove from it.
- Successful authentication logs at DEBUG, rejection at INFO: verification runs on every request, so a success is the unremarkable case.

### Errors

- Services raise domain exceptions from `commons/exceptions/`; the MCP layer converts them to `ToolError` in one place, with `mask_error_details=True` always on — never env-gated. Never return an error payload from a tool: at the protocol level it reads as success.
- `AIStackError`, `ValidationError`, `Conflict`, `NotFound`, `InvalidTicket`, and `SignedOut` are the exception types that exist. Add one when a rejection needs it, not in advance. A new type also needs a status code in `mcp/routes/route_error_handler.py`, or a transfer or dashboard route answers it with 400.
- Error text is agent-facing UX: say what to fix and what was received, not what class was raised. "What was received" covers non-secret validation values only — never a bearer, token, or invite code.

### MCP tools

- Tool results are flat facts in a TypedDict, and FastMCP structures them. No preformatted `message` field — the agent writes better chat prose than we can, and a second copy of the UX drifts. `add_machine` is the one exception: its paste-ready command is consumed by a human on a different computer.
- Constrain a tool parameter in the schema only when the agent benefits from seeing the options, as `os` does with three legal values. Length and format limits are validated in the service, where the message can say what was received.
- `mcp/tools/` holds four modules by area: `onboarding.py`, `skills.py`, `sync.py`, `teams.py`, plus `local.py` for local mode. A tool is added only when saying it in chat beats clicking it; anything with many typed parameters is a dashboard action.
- Local mode (ADR-0020) is `aistack` over stdio, `aistack dashboard` serves the page on 127.0.0.1, and `aistack serve` is the server. Its `open_dashboard` starts the same localhost page inside the stdio process (`mcp/local_dashboard.py`), alive as long as the agent session. The localhost dashboard serves only `LOCAL_ROUTES` in `api/dashboard.py`: a team route is registered with `local=False`, because a team needs a server everyone reaches. Its server in `mcp/local.py` has no authentication, because the caller is whoever could start the process, so it registers only tools about the one person's own Library: never a team or onboarding tool. Its caller comes from `get_local_principal()`. Its tools read a skill folder before the transaction and write one after it commits, and an install writes only what passed push validation and re-hashed to the stored hash (`services/local_skills.py`). Setup installs local mode with `uv tool install aistack-mcp` and the agent starts that command by its full path, so it starts offline; `bootstrap/self_update.py` upgrades it in the background once a day, only when it runs from a uv tool environment, and ADR-0024 keeps computers on different releases safe meanwhile. Never point an agent at `uvx aistack-mcp@latest`: it cannot start without a network. Every change local mode makes is also recorded as an event in the same transaction (`services/library_log.py`, ADR-0025), and `apply` replays it through the same service call: a new local write path that skips either is lost from a GitHub Library and from a rebuilt copy, and `tests/mcp/test_library_log.py` replays random sequences to catch it. Git work (`services/library_repo.py`) happens outside transactions, and a failed push leaves events unpublished for the next one. `LocalSettings` reads `AISTACK_`-prefixed variables only and no `.env`: the agent starts it inside somebody's project, whose `DATABASE_URL` belongs to that project.
- File content never crosses MCP (ADR-0010). A tool that moves skill bytes returns a signed transfer URL, and the route behind it does the work. Do not add a `content` field to a tool argument or result.
- The MCP endpoint is stateless (ADR-0013). Do not add a feature that needs a server-initiated message — progress, elicitation, a subscription — without reversing that ADR first; it will work in a test with one client and fail behind a restart.

### HTTP routes

- Any URL the server hands out is built from `server_base_url()` in `mcp/server_url.py`. `AISTACK_PUBLIC_URL` wins; otherwise the address comes from the request, and anything that is not a plain http(s) URL is refused, because it ends up in a command a person pastes into a shell.
- A transfer route is an `async def` Starlette handler, because FastMCP's `custom_route` requires one. It reads the body, then runs everything else — ticket verification aside — in one `asyncio.to_thread` call that opens one session, exactly as a tool would. Its rejections are JSON `{"error": ...}` with the same agent-facing sentence a `ToolError` would carry.
- A transfer ticket is a credential for five minutes. It is never logged, and uvicorn's access log stays off because the ticket is in the URL. It is a JWT verified by PyJWT with the algorithm list pinned to HS256 and `exp`, `aud`, and `sub` required; the audience is the purpose, so a download ticket cannot upload. `TicketSigner` is the only code that touches the key.
- A dashboard link and a dashboard session are tickets from the same `TicketSigner`, each with its own audience, so a link cannot be replayed as a cookie nor a cookie as a link (ADR-0017). The link is a credential for five minutes: returned by `open_dashboard`, never logged. The key lives in memory, so a restart signs every browser out; do not persist it to fix that.
- A transfer URL is checked again when it is used, because it outlives the call that minted it: `push` requires the ticket's machine to still be registered to its user, and `archive_of` requires the revision to be one of that machine's user's own skills.
- A dashboard route lives in `api/dashboard.py` and is as thin as a tool: it takes the `user_id` from the session cookie and from nowhere else, runs one service call in one transaction through `asyncio.to_thread`, and returns what that call returned. A new action is one `@_action` function calling the service a tool would call; what the page shows is assembled in `services/dashboard_service.py`. `/app` and `/api/*` refuse without a valid session, and a request that changes state must also carry the `X-AIStack-Request` header, which a cross-site form cannot send. The API returns only what `visibility` allows; nothing is filtered in JavaScript.
- `/setup` and `/health` are the only routes that answer with no credential, besides `/`, which only redirects to `/app`, and the signed-out page `/app` answers with. Nothing secret may be reachable from any of them: the setup page and the signed-out page are assembled from static text and the server's own address. Transfer routes and the dashboard sign-in link carry their credential as a ticket in the URL, and the invite page (`/invite/<code>`) carries a team's invite code there: it shows the team's name and the sentence to paste, never logs the code, and answers a wrong one like any other.
- The uvicorn configuration comes from `http_server_config()` in `mcp/mcp.py`, for the real server and the test server alike. Do not build a `uvicorn.Config` anywhere else: the settings in it are security decisions, and a second copy is one that can disagree.
- The health route says `ok` or `unavailable` and nothing else. It answers without a credential, so it carries no version, no counts, and no error text; the failure reason goes to the log.

### Skills, sync, and teams

- Trust boundaries are not optional: validate skill names and file paths at push exactly as the schema in `docs/DESIGN.md` specifies.
- Skill versions are immutable — never update a `SKILL_VERSION` row; a change is a new revision.
- Push validation is pure: `services/` functions that take bytes and return values or raise `ValidationError`, with no session. The archive is read in memory and never extracted to disk.
- The canonical content hash has one implementation, `services/content_hash.py` (ADR-0011). Push and sync both call it; nothing else frames a hash.
- Provenance columns are `pushed_by` and mean exactly that — never render them as "author" or "created by".
- A machine installs only from its user's personal team (ADR-0015). `get_skill`, `sync`, and the download route never read a team's copy; a team skill reaches a machine by being taken into the Library first. That is why leaving a team, or an admin removing a team's skill, takes nothing off anybody's computer.
- A teammate's change is an offer. Sync lists it under `team_updates` and never applies it; accepting is `get_skill(name, team)`, a deliberate call. A skill is instructions to an agent, so somebody else's edit does not reach a machine without its owner saying yes.
- Who may see what is decided in `services/visibility.py` and nowhere else. The caller's own skill comes from `required_my_skill`, a team's from `team_skill` or `team_skills`, a team from `membership`, and group rules from `group_access`. A lookup by `team_id` outside that module is legitimate only after `membership` has placed the caller in that team.
- A team, group, or skill the caller may not see is answered with the same exception and the same sentence as one that does not exist. A different message for "hidden" tells the caller it is there.
- Every function in `services/team_service.py` takes the caller's `user_id` and begins with `visibility.membership` (or `_as_admin`, which calls it) before reading anything else about the team. A function that looks the team up first has already leaked whether it exists.
- Sharing into a group takes belonging to it or to a group above it (`GroupAccess.writable`). Seeing a group, including through `sees_all_groups`, does not make it writable.
- Code asks a team's `kind`, never its name. A team's name is its creator's choice and can change, and a personal team is never reachable by name at all.
- A skill removed from the Library keeps its row with `archived = true`. Without the row, sync would take the folder still on a computer for a new skill and back it up again.
- Installs stage under `<skills>/.aistack-staging/` and finish with a rename. A dot-folder two levels deep is neither loaded by Claude Code as a skill nor reported by sync, and it is on the same filesystem as the target, so the rename is atomic.
- Sync reconciliation is a pure function over `desired` and `observed` states, returning a policy action — no knowledge of skills, SQLAlchemy, paths, or adapters (ADR-0007). It is the seam a second resource type reuses. `services/reconciliation.py` holds the table and `services/sync_service.py` computes the two facts for skills; a change to what sync may do silently is a change to the table and its invariant tests, never an `if` in the service.
- `sync` never changes desired state. It reports and the agent acts through `get_skill`, `push_skill`, or `disable_skill`; the one thing it writes is that a harness synced, and when (`machine_harness`). A skill on disk that is not in the Library is listed under `backup` and pushed without asking, because that space is private. A local copy the server cannot hash (a malformed digest, two spellings of one path) is `unknown`, not an error: the safe answer to anything unrecognized is to ask.
- `src/aistack/bundled/` holds the files AIStack serves as they are: the setup instructions, the `sync-aistack` skill, and the dashboard page, plus `local/`: local mode's setup and sync skill, which `aistack setup` and `aistack sync-skill` print because there is no server to fetch them from. They are package data so the image carries them. A test runs the skill through push validation, because setup writes it to disk before the server could have checked it, and the container job fetches both from the built image.

### Tests and review

- Tests: pytest under `tests/`, mirroring `src/aistack/`. Services directly for rejection matrices; one in-process HTTP test per auth-bearing flow, because the in-memory transport does not exercise bearer verification. SQLite tests use a temp file, never `:memory:` — WAL and any two-connection test need a real file. Postgres tests read `TEST_DATABASE_URL` (never `DATABASE_URL`, so a test cannot reach a real database), skip locally with a message naming the variable, and CI fails setup when it is unset.
- A new machine-scope tool is added to `OUTSIDER_VIEW` in `tests/mcp/test_teams_over_http.py`, which is the decision about what it shows a user outside a team. The test fails until it is there.
- The page is tested in a real browser under `tests/ui/` (Playwright, the in-process server, data from `scripts/demo_seed.py`). Find elements by role and by the words a user reads, never by a class or an id: the look will change and what a person can do must not. A change to the page that renames a control changes its test in the same commit. Confirm an action against `/api/state`, not against what the page then draws. They run in Chromium by default; `AISTACK_UI_BROWSER=firefox` or `webkit` runs them there, and CI runs all three.
- Trust-boundary work gets a diff review, not just a plan review: auth, push validation and hashing, sync, and anything destructive. Plans cannot reveal a missing authorization check, a path traversal, or a secret in a log line.
- A captured-log assertion cannot prove uvicorn's access log is off. pytest attaches its handler to non-propagating loggers, so the access logger looks alive under test. Assert on the configuration instead.
- A test that pins a race proves nothing unless it fails without the enforcement. Drive concurrency with a `threading.Barrier` at the exact window, not with hope that N threads collide.

### Operations

- `docs/OPERATING.md` is for whoever runs the server. An admin operation documented there is a script that goes through `build_engine`, never a bare `sqlite3` shell: SQLite only cascades deletes with a per-connection pragma that the engine sets. Run a documented script against a real database before committing a change to it.
- The image is published to `ghcr.io/dchristopoulos/aistack` only by the `publish` job in `tests.yaml`, which needs every test job and runs only on a push to `main` or a version tag. Never push an image by hand: `latest` must only ever be a commit that passed.
- The package is published to PyPI as `aistack-mcp` (the name `aistack` belongs to another project) only by the `pypi` job in `tests.yaml`, on a `v<version>` tag that matches `pyproject.toml`. Never upload by hand: PyPI never takes a version back.
- CI builds the image and drives it with `scripts/container_smoke.py`: a fresh volume, a restart, the unprivileged uid, a grep of the container's logs for every kind of secret, and the same image against PostgreSQL. A change to the Dockerfile is verified there, not by reading it.

## Running tests

The commands are in the README. What it does not say:

- In a git worktree, `poetry run` builds a new, empty virtualenv. Use the main checkout's and put the worktree's code first: `PYTHONPATH=src "$(cd <main checkout> && poetry env info -p)/bin/python" -m pytest -q`.
- The PostgreSQL half needs `docker compose -f compose.test.yaml up -d` and `TEST_DATABASE_URL=postgresql+psycopg://aistack:aistack@localhost:5433/aistack_test`. Run it for any migration, query, or concurrency change: SQLite alone hides dialect bugs.
- The browser tests need `poetry run playwright install chromium` once. CI also runs Firefox and WebKit.

## Agent skills

### Issue tracker

Issues live in GitHub Issues via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Default five canonical labels (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Shipping a change

Commit, open the PR, decide whether it waits for a human diff review, and land it (stacks included) with the `ship-a-change` skill in `.agents/skills/`.

### Domain docs

Single-context: `CONTEXT.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.
