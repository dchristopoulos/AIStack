## What this is

AIStack: a self-hosted, open-source control plane for AI dev configuration (skills first; rules, agents, hooks, MCPs later), synced across users, machines, and harnesses via MCP.

## Read before designing or implementing anything

- `docs/DESIGN.md` — the plan: MVP scope, seven MCP tools, flows, final DB schema, project structure, roadmap. Where anything conflicts with it, this document wins.
- `CONTEXT.md` — domain glossary. Use these terms exactly; respect the `_Avoid_` lists.
- `docs/adr/` — decisions already made (full sync not proxy, SQLite default, token auth, server-side desired state). Do not relitigate them; write a new ADR to reverse one.

## Tech stack

Python 3.13, Poetry, SQLAlchemy, FastMCP. SQLite by default, Postgres via `DATABASE_URL` (ADR-0002) — code must run identically on both. FastAPI arrives post-MVP with the dashboard; `src/aistack/api/` stays empty until then.

## Structure

Layered layout under `src/aistack/` (see `docs/DESIGN.md` §8): MCP tool handlers in `mcp/tools/` stay thin; business logic goes in `services/`; models in `db/models/`. Put code in its layer even while layers are thin.

## Conventions

- Keep the normal flow readable from top to bottom. Use short docstrings for contracts, and inline comments for non-obvious security, transaction, or portability constraints. Link to the ADR for longer reasoning instead of repeating it in each layer. Use one argument per line for multiline constructors and calls; avoid manual alignment under long names.
- Tests: pytest under `tests/`, mirroring `src/aistack/`. Services directly for rejection matrices; one in-process HTTP test per auth-bearing flow, because the in-memory transport does not exercise bearer verification. SQLite tests use a temp file, never `:memory:` — WAL and any two-connection test need a real file. Postgres tests read `TEST_DATABASE_URL` (never `DATABASE_URL`, so a test cannot reach a real database), skip locally with a message naming the variable, and CI fails setup when it is unset.
- `[project].dependencies` takes PEP 508 ranges, not Poetry carets; dev tools live in `[dependency-groups]`. `requires-python` carries a `<4.0` upper bound because a transitive dependency does and Poetry cannot resolve against an open floor. `fastmcp` is pinned exactly — the ticket #1 spike results are statements about one release, and a silent minor bump invalidates them. Everything else gets a compatible range and the lock file does the pinning.
- Trust boundaries are not optional: validate skill names and file paths at push exactly as the schema in `docs/DESIGN.md` specifies.
- Skill versions are immutable — never update a `SKILL_VERSION` row; a change is a new revision.
- Synchronous SQLAlchemy (ADR-0005): plain `def` tools — FastMCP threadpools them. Never write an `async def` tool that calls a blocking driver; that serializes every caller. Where an async signature is forced on you (the `TokenVerifier`), push the database work through `asyncio.to_thread`.
- The session factory lives in `db/`; `bootstrap/context/` holds the singleton. A tool opens exactly one session per call as `with session_factory.begin() as session:` and passes it down; services never open their own. One MCP call is one transaction. The single exception is the auth token verifier, which owns a short-lived read session because it runs before tool dispatch.
- SQLite engines pass `connect_args={"autocommit": False}` (ADR-0008) so savepoints participate in the outer transaction. The connect hook then applies WAL, an explicit 5s busy timeout, and `PRAGMA foreign_keys=ON` (cascades silently don't fire without it), flipping autocommit on for the duration — those pragmas are no-ops inside an open transaction.
- The engine module branches on dialect internally and exposes one `build_engine(database_url)`. Callers never learn which database they are on. No engine, connection, or `create_schema` at import time; `application_context` calls them during assembly.
- Every tool declares `auth=` explicitly. FastMCP's per-component authorization is opt-in, so a tool registered without it is listed and callable by any authenticated principal, including the bootstrap one whose bearer is a static code the whole team holds. `tests/mcp/test_tool_authorization.py` fails the build on a missing declaration; adding a name to `BOOTSTRAP_ONLY_TOOLS` there is a decision that a tool is reachable with nothing but the invite code.
- Caller-supplied values are escaped before they reach a log line or an error message. `commons/text.py`: `sanitized()` for a whole message, `loggable()` for one argument, which also caps its length. Both sinks read newlines as structure, so an unescaped one forges a log line for the operator and a turn for the agent, and these run on the rejection path, where nothing has validated the value yet. `AIStackError` sanitizes its own message, so a service cannot reintroduce this by forgetting.
- Authorization is FastMCP's `require_scopes` — `bootstrap` on `join`, `machine` on everything else — not custom middleware. Unauthorized tools are omitted from `tools/list`, not merely rejected on call. AIStack's `TokenVerifier` resolves the bearer and returns `machine_id` and `user_id` as claims, so no tool re-queries identity.
- Secrets: a token is `f"aist_{secrets.token_urlsafe(32)}"`, stored only as its sha256, and appears only in the `join`/`add_machine` result — never in logs, errors, or any other tool result. The invite code exists only as operator-supplied config and as the bootstrap `Authorization` bearer: never in logs, errors, tool arguments, tool results, or startup output. An invalid-auth error never echoes the presented bearer.
- Constant-time comparison applies to the invite code only (`hmac.compare_digest` over sha256 digests). A machine token is resolved by indexed lookup on `token_hash`, where nothing is compared in Python. Do not "fix" that asymmetry into a table scan.
- Tool results are flat facts in a TypedDict, and FastMCP structures them. No preformatted `message` field — the agent writes better chat prose than we can, and a second copy of the UX drifts. `add_machine` is the one exception: its paste-ready command is consumed by a human on a different computer.
- Constrain a tool parameter in the schema only when the agent benefits from seeing the options, as `os` does with three legal values. Length and format limits are validated in the service, where the message can say what was received.
- `mcp/tools/` holds three modules by area: `onboarding.py`, `skills.py`, `sync.py`.
- Provenance columns are `pushed_by` and mean exactly that — never render them as "author" or "created by".
- Trust-boundary work gets a diff review, not just a plan review: auth, push validation and hashing, sync, and anything destructive. Plans cannot reveal a missing authorization check, a path traversal, or a secret in a log line.
- Enforce column lengths in the application. SQLite accepts oversized `VARCHAR(n)`, Postgres rejects it, so unenforced lengths break "runs identically on both".
- Sync reconciliation is a pure function over `desired` and `observed` states, returning a policy action — no knowledge of skills, SQLAlchemy, paths, or adapters (ADR-0007). It is the seam a second resource type reuses.
- Services raise domain exceptions from `commons/exceptions/`; the MCP layer converts them to `ToolError` in one place, with `mask_error_details=True` always on — never env-gated. Never return an error payload from a tool: at the protocol level it reads as success.
- The error decorator logs the tool name and error, never reflected call arguments. Unexpected tracebacks are rendered and escaped before logging; `logger.exception()` would append the unescaped exception chain.
- Internal token-bearing models exclude the credential from repr. Keep the SDK's raw token field for authentication, and expose the machine token only in the authorized tool result.
- `AIStackError`, `ValidationError`, and `Conflict` are the exception types that exist. Add one when a rejection needs it, not in advance.
- Error text is agent-facing UX: say what to fix and what was received, not what class was raised. "What was received" covers non-secret validation values only — never a bearer, token, or invite code.
- The invite code is a pydantic `SecretStr`, and it is validated by a plain function called during context assembly, never by a pydantic validator: pydantic embeds the rejected input in its `ValidationError`, so a field validator on that value writes the secret into startup output.
- Third-party loggers that print raw protocol payloads (`mcp.client`, `mcp.server.streamable_http`, `sse_starlette`, `httpcore`, `httpx`) are floored at INFO in `bootstrap/__main__.py`. A tool result carrying a machine token goes over the wire in plaintext by definition, so at DEBUG those libraries write the token to the log file. Add to that list, never remove from it.
- Successful authentication logs at DEBUG, rejection at INFO: verification runs on every request, so a success is the unremarkable case.
- A test that pins a race proves nothing unless it fails without the enforcement. Drive concurrency with a `threading.Barrier` at the exact window, not with hope that N threads collide.

## Agent skills

### Issue tracker

Issues live in GitHub Issues via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Default five canonical labels (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `CONTEXT.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.
