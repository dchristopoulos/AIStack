# Security

Sign-in, authorization, secrets, and the build and dependency chain. For local mode and a GitHub Library, only what the review behind commit 3027697 missed. Every reproduction ran against a throwaway server started for it, with demo data; the probe scripts are described in each finding and were not committed.

How far this was checked: each finding below was reproduced or traced line by line by the auditor who raised it, and **Confirmed** means exactly that. The independent second pass that tries to refute each finding ran only for the authorization and UX findings: the account's weekly limit stopped the rest. Where the main session re-checked a finding itself, its entry says so. Treat **Suspected** findings, and anything marked High or Critical without a second pass, as needing a reproduction before the fix lands; the reproduction is described in each.

| Id | Finding | Severity | Status | Effort |
|---|---|---|---|---|
| [AUTHZ-01](#authz-01-removing-demoting-or-offboarding-an-inviter-leaves-their-invite-links-working-so-the-person-can-rejoin-the-team-or-create-a-new-account-on-the-server) | Removing, demoting or offboarding an inviter leaves their invite links working, so the person can rejoin the team or create a new account on the server | High | Confirmed | S |
| [SEC-01](#sec-01-a-stolen-machine-token-outlives-the-documented-revocation-sibling-tokens-dashboard-sessions-and-upload-urls-keep-working) | A stolen machine token outlives the documented revocation: sibling tokens, dashboard sessions and upload URLs keep working | High | Confirmed | M |
| [AUTHZ-02](#authz-02-a-member-who-can-only-see-a-group-an-open-groups-non-member-or-a-sees-all-groups-member-can-push-a-new-revision-into-that-groups-skill-by-sharing-without-a-group) | A member who can only see a group (an open group's non-member, or a 'sees all groups' member) can push a new revision into that group's skill by sharing without a group | Medium | Confirmed | S |
| [AUTHZ-03](#authz-03-the-team-member-list-leaks-private-group-names-through-the-paths-of-open-subgroups-under-them) | The team member list leaks private group names through the paths of open subgroups under them | Medium | Confirmed | S |
| [AUTHZ-V01](#authz-v01-offboarding-a-teams-only-admin-as-docsoperatingmd-says-leaves-the-team-with-an-admin-nobody-can-reach-and-no-way-to-name-a-new-one) | Offboarding a team's only admin as docs/OPERATING.md says leaves the team with an admin nobody can reach, and no way to name a new one | Medium | Confirmed | S |
| [PUSH-01](#push-01-the-jobs-that-hold-publishing-credentials-run-third-party-actions-by-moving-tags-and-an-unpinned-poetry) | The jobs that hold publishing credentials run third-party actions by moving tags and an unpinned Poetry | Medium | Confirmed | S |
| [SEC-02](#sec-02-no-rate-limit-or-lockout-on-any-credential-check-and-the-invite-code-strength-check-accepts-trivially-guessable-codes) | No rate limit or lockout on any credential check, and the invite-code strength check accepts trivially guessable codes | Medium | Confirmed | M |
| [SEC-03](#sec-03-fastmcp-logs-malformed-tool-arguments-verbatim-at-warning-so-a-team-invite-code-can-reach-the-server-log-and-the-log-leak-test-cannot-see-it) | FastMCP logs malformed tool arguments verbatim at WARNING, so a team invite code can reach the server log, and the log-leak test cannot see it | Medium | Confirmed | S |
| [AUTHZ-04](#authz-04-the-team-keeps-an-admin-check-counts-first-and-writes-later-without-a-lock-on-postgresql-two-simultaneous-leaves-or-demotions-leave-a-team-with-no-admin) | The 'team keeps an admin' check counts first and writes later without a lock; on PostgreSQL two simultaneous leaves or demotions leave a team with no admin | Low | Confirmed | S |
| [AUTHZ-05](#authz-05-the-only-member-of-a-team-can-never-leave-it-and-no-team-can-be-deleted-the-pages-own-demo-lets-them) | The only member of a team can never leave it, and no team can be deleted; the page's own demo lets them | Low | Confirmed | M |
| [AUTHZ-07](#authz-07-a-private-group-that-exists-answers-slower-than-one-that-does-not-so-a-member-can-probe-private-group-names-by-timing) | A private group that exists answers slower than one that does not, so a member can probe private group names by timing | Low | Confirmed | S |
| [AUTHZ-08](#authz-08-outsider_view-checks-only-that-each-tool-has-a-label-most-labels-are-never-exercised-and-there-is-no-matrix-for-a-member-who-sees-but-cannot-write-or-cannot-see-a-private-group) | OUTSIDER_VIEW checks only that each tool has a label; most labels are never exercised, and there is no matrix for a member who sees but cannot write, or cannot see a private group | Low | Confirmed | M |
| [SEC-04](#sec-04-unauthenticated-requests-take-sqlites-write-lock-token-checks-health-and-the-invite-page-all-run-begin-immediate) | Unauthenticated requests take SQLite's write lock: token checks, /health and the invite page all run BEGIN IMMEDIATE | Low | Confirmed | S |
| [SEC-05](#sec-05-signing-out-does-not-end-the-session-a-copied-cookie-keeps-working-for-the-rest-of-its-8-hours) | Signing out does not end the session; a copied cookie keeps working for the rest of its 8 hours | Low | Confirmed | S |
| [SEC-06](#sec-06-on-postgresql-an-admins-cancel-can-report-success-while-the-person-it-was-meant-to-stop-joins) | On PostgreSQL an admin's cancel can report success while the person it was meant to stop joins | Low | Confirmed | S |
| [SEC-07](#sec-07-a-used-team-invite-code-still-authenticates-as-a-bearer-so-used-and-unknown-codes-answer-differently) | A used team invite code still authenticates as a bearer, so used and unknown codes answer differently | Low | Confirmed | S |
| [SEC-08](#sec-08-one-team-invite-link-or-the-server-code-is-an-unlimited-oracle-for-every-username-and-team-name-on-the-server) | One team invite link, or the server code, is an unlimited oracle for every username and team name on the server | Low | Confirmed | S |
| [SEC-09](#sec-09-dashboard-actions-buffer-the-whole-request-body-before-applying-the-16-kib-limit) | Dashboard actions buffer the whole request body before applying the 16 KiB limit | Low | Confirmed | S |
| [SEC-10](#sec-10-a-sign-in-link-silently-replaces-the-browsers-existing-session-login-csrf) | A sign-in link silently replaces the browser's existing session (login CSRF) | Low | Confirmed | S |
| [SEC-11](#sec-11-setup-fills-its-urls-from-the-host-header-and-sends-no-cache-control-so-a-caching-proxy-could-serve-a-poisoned-copy) | /setup fills its URLs from the Host header and sends no Cache-Control, so a caching proxy could serve a poisoned copy | Low | Suspected | S |
| [SEC-12](#sec-12-the-documented-run-commands-expose-the-plain-http-port-the-quick-start-on-every-interface-with-a-public-code-and-the-tls-proxy-pattern-still-publishing-8000) | The documented run commands expose the plain-HTTP port: the quick-start on every interface with a public code, and the TLS proxy pattern still publishing 8000 | Low | Confirmed | S |
| [SEC-13](#sec-13-local-mode-on-a-shared-computer-aistack_home-is-world-readable-and-the-one-use-sign-in-link-is-visible-on-the-browsers-command-line) | Local mode on a shared computer: AISTACK_HOME is world-readable, and the one-use sign-in link is visible on the browser's command line | Low | Confirmed | S |
| [SEC-14](#sec-14-a-rejected-bearer-gets-fastmcps-oauth-text-telling-the-client-to-re-register-which-aistack-cannot-do) | A rejected bearer gets FastMCP's OAuth text telling the client to 're-register', which AIStack cannot do | Low | Confirmed | S |

## Sign-in, sessions and secrets

Sign-in and secrets hold up well where they are explicitly designed. The server's invite code is compared in constant time. Machine tokens (256 bits) and team invite codes (192 bits) are stored only as hashes. Transfer and dashboard tickets pin HS256 with separate audiences, and a full DEBUG-level run through join, add_machine, push, get_skill, open_dashboard, invite and join_team logged no token, code, link or ticket. The gaps are around those designs. A stolen machine token outlives the operator's documented rotation: it can mint sibling machines, and dashboard sessions and upload URLs survive. No credential check anywhere has a rate limit or lockout: one client made about 180 bearer guesses a second and about 330 invite-page guesses a second, and the weak-code check accepts 'aaaaaaaaaaaaaaaa'. FastMCP itself logs malformed tool arguments verbatim, so a team invite code can reach the log. Unauthenticated requests take SQLite's write lock. Sign-out does not end a session, and an admin's cancel can lose a race to a join on PostgreSQL. The other findings are smaller hardening items for docs, local mode on shared computers, and error text.

### SEC-01: A stolen machine token outlives the documented revocation: sibling tokens, dashboard sessions and upload URLs keep working

**Confirmed.** Severity **High**, effort **M**. Hurts: Someone with two computers whose laptop is lost or stolen. Also a team admin, whose team the thief can keep inviting accounts into. The operator follows a runbook that gives false assurance.

**Where.** src/aistack/mcp/tools/onboarding.py:121-149 (add_machine); docs/OPERATING.md:127-158 (lost or stolen laptop runbook); src/aistack/services/dashboard_service.py:86-95 (require_a_machine); src/aistack/services/transfer_ticket.py:99-128 (link/session claims carry only user_id); src/aistack/api/dashboard.py:311-319

**What is wrong.** A machine token is a full, permanent account credential.
- Any machine-scope caller can call add_machine and receive a fresh permanent token for another machine of the same user.
- open_dashboard links and the 8-hour session they start are bound only to user_id. require_a_machine only checks that the user still has some machine.
- Upload tickets are bound to machine_id, which a rotation keeps.

The OPERATING.md runbook for a lost or stolen laptop only rewrites that one machine's token_hash. After the operator follows it, the thief still has:
- (a) every sibling token they minted, forever;
- (b) every dashboard session, for up to 8 hours;
- (c) every upload URL, for 5 minutes.

DESIGN.md:545 says a machine updates to the latest revision of its user's own skill without confirmation. So a sibling token can push a hostile revision of any Library skill, and every other computer of the victim installs it on its next sync. If the victim is a team admin or can_invite, the thief can also mint 7-day team invites that create new accounts inside the team. The runbook never mentions:
- machines added since the loss;
- restarting to end sessions;
- checking pending invites.

**How it was confirmed.** Script: &lt;scratch&gt;/security-signin/session_probe.py, run against my own server (SQLite, port 8110) with DATABASE_URL pointing at that server's file.

Steps with the joined user's token T1:
- add_machine 'thiefs-box' returned T2.
- open_dashboard signed an httpx browser in.
- push_skill returned an upload URL.
- Ran the OPERATING.md rotation script verbatim (UPDATE machine SET token_hash ... WHERE name='laptop').

Output after rotation:
- T1: 401.
- T2: list_skills works.
- The session: GET /api/state 200, and POST /api/skills/probe-skill/remove 200.
- The pre-rotation upload URL: PUT 200, which stored a new revision.

**Proposed fix.** (1) Bind tickets to the machine and its current token. Add claims 'mid' and 'tkh' (the first 16 hex characters of machine.token_hash) in TicketSigner.sign_dashboard_link, sign_dashboard_session, sign_upload and sign_download. Check them in dashboard_service.require_a_machine (it becomes 'require its machine'), skill_service._require_registered_machine and archive_of. Rotating or deleting a machine then ends everything minted through its token. ADR-0017's 'a session ends with its user's last machine' becomes 'with the machine that opened it'. This refines ADR-0017 and does not reverse it.
(2) Record where a machine came from: add a nullable machine.added_by_machine_id column in a new migration (older_releases_compatible=True), set it in onboarding_service.add_machine, and show 'added from &lt;machine&gt; on &lt;date&gt;' on the dashboard's computer page.
(3) Rewrite the OPERATING.md runbook to:
- list the user's machines with created_on and added_by;
- delete those added after the loss;
- restart the server until (1) lands;
- review Library revisions pushed since the loss;
- have team admins check pending invites.

**Done when.** New tests in tests/api/test_dashboard_over_http.py and tests/mcp/test_push_over_http.py: after the documented rotation of machine A, a dashboard session opened through A gets 401, and an upload URL minted by A gets 403. OPERATING.md names the add_machine check and the restart. session_probe.py prints 401/403 for its last three checks.

Related: [AUTO-02](automation.md#auto-02-on-a-server-a-person-cannot-cut-off-their-own-lost-or-stolen-computer), [AUTO-20](automation.md#auto-20-computers-cant-be-renamed-or-removed-and-a-reinstall-leaves-vm-and-vm-2-forever), [IMP-06](improvements.md#imp-06-the-dashboard-cannot-say-when-a-computer-last-synced-or-which-revision-it-holds), [IMP-09](improvements.md#imp-09-a-person-cannot-retire-revoke-or-rename-their-own-computer-only-the-operator-can), [PH-13](plot-holes.md#ph-13-owners-cannot-rename-or-remove-a-computer-and-nothing-shows-when-a-computer-last-synced), [SEC-05](#sec-05-signing-out-does-not-end-the-session-a-copied-cookie-keeps-working-for-the-rest-of-its-8-hours), [SEC-10](#sec-10-a-sign-in-link-silently-replaces-the-browsers-existing-session-login-csrf), [STD-03](industry-standards.md#std-03-a-dashboard-session-cannot-be-ended-not-by-signing-out-and-not-by-deleting-the-machine-that-opened-it), [STD-04](industry-standards.md#std-04-a-person-cannot-see-when-each-computer-last-connected-or-remove-a-lost-one-and-a-stolen-tokens-push-lands-silently-on-their-other-computers).

### SEC-02: No rate limit or lockout on any credential check, and the invite-code strength check accepts trivially guessable codes

**Confirmed.** Severity **Medium**, effort **M**. Hurts: The operator who chose a memorable server invite code, or kept the README's example. Every user of a server under a guessing flood, because their calls slow down and the log grows.

**Where.** src/aistack/mcp/auth/aistack_token_verifier.py:35-79; src/aistack/mcp/routes/invite.py:39-54; src/aistack/bootstrap/configuration/settings/settings_config.py:162-178; README.md:39

**What is wrong.** Nothing anywhere counts failures. There is no limiter, backoff, lockout or per-address counter on:
- the bootstrap bearer;
- aistinv_ bearers;
- /invite/&lt;code&gt;;
- join_team codes;
- dashboard sign-in links.

validate_invite_code only requires 16 characters and rejects 'change-me'. It accepts 'aaaaaaaaaaaaaaaa' and the README's public 'try-it-out-locally-1234'. Every rejection:
- writes one INFO line (176 bytes);
- runs a database lookup through asyncio.to_thread's default executor (min(32, CPUs+4) threads), which every real request also needs to authenticate.

What an attacker gets: guessing machine tokens (256 bits), team codes (192 bits) or an openssl-generated server code (144 bits) is hopeless. A human-chosen server code that passes the 16-character rule is not: one client can try about 15 million guesses a day. Success is an account, unlimited further accounts, and the enumeration in SEC-08. Win or lose, the flood costs about 2.7 GB of log a day per client and makes real users' calls about 7x slower.

**How it was confirmed.** Script &lt;scratch&gt;/security-signin/guess_rate.py, run as `guess_rate.py http://127.0.0.1:8110 10 16`: one client, 16 connections, 10 seconds per kind, on this shared 4-CPU machine.
- Random bearers: 183 per second, all 401.
- aistinv_ bearers: 171 per second, all 401.
- /invite/&lt;code&gt;: 334 per second, all 404.
- No 429 at any point.

Script flood_vs_legit.py (same folder): list_skills had a median of 110 ms alone, and a median of 735 ms (p95 980 ms) while 32 connections sent random bearers.

One 'Bearer rejected' INFO line measured 176 bytes. Starting a server with AISTACK_INVITE_CODE=aaaaaaaaaaaaaaaa succeeded.

**Proposed fix.** Add a small in-process failure limiter, for example mcp/auth/failure_limiter.py. Key it on request.client.host (uvicorn's proxy_headers already resolves trusted X-Forwarded-For) with a sliding window: for example, after 20 failures a minute, answer 429 with Retry-After. Consult it:
- where AIStackTokenVerifier.verify_token is about to return None;
- in the invite route on NotFound;
- in the join_team tool and dashboard action on NotFound;
- in sign_in on InvalidTicket.

Log one summary line per address per window instead of one line per guess. In-memory state fits the one-process rule from ADR-0010 and ADR-0017.

Tighten validate_invite_code: at least 24 characters and at least 10 distinct characters, and reject the README example, without echoing the value. Make the README quick-start bind 127.0.0.1 (see SEC-12).

**Done when.** A test in tests/mcp/test_join_over_http.py sends 30 wrong bearers and gets 429 on the later ones, while a valid machine token from another client still works. guess_rate.py shows 429s once past the threshold. Starting with AISTACK_INVITE_CODE=aaaaaaaaaaaaaaaa fails with a message that does not repeat the code.

Related: [SEC-08](#sec-08-one-team-invite-link-or-the-server-code-is-an-unlimited-oracle-for-every-username-and-team-name-on-the-server), [STD-05](industry-standards.md#std-05-failed-authentication-is-never-throttled-and-never-logged-with-a-client-address).

### SEC-03: FastMCP logs malformed tool arguments verbatim at WARNING, so a team invite code can reach the server log, and the log-leak test cannot see it

**Confirmed.** Severity **Medium**, effort **S**. Hurts: A team admin whose invite code ends up in the log, which is often shipped to a log service with wider access; whoever reads it can join the team as that one person. Also the operator, who relies on the README promise that invite codes never reach a log line or an error.

**Where.** fastmcp/server/server.py:1325 (fastmcp 3.4.7, pinned exactly); src/aistack/bootstrap/__main__.py:36-43 (WIRE_LOGGERS and configure_logging); src/aistack/mcp/tools/teams.py:146-150 (join_team(code)); tests/api/test_dashboard_over_http.py:356-359

**What is wrong.** When a tool call's arguments fail schema validation, FastMCP calls logger.warning("Invalid arguments for tool %r: %s") with pydantic's errors, and those include the raw 'input'.
- The 'fastmcp' logger has propagate=False and two RichHandlers of its own.
- So the line reaches stderr and the log file at the default level, whatever AISTACK_LOG_LEVEL says, and WIRE_LOGGERS does not cover it.
- It is Rich-wrapped across several lines and never passes through sanitized().

join_team's 'code' is a team invite code. A plausible agent mistake writes the code into the server log and into the returned error:
- calling join_team(invite_code=...);
- wrapping the code in an object or a list.

The existing guard, test_no_link_session_or_invite_code_reaches_a_log_line, filters records named 'fastmcp*'. Those records never reach caplog's root handler, because propagation stops at 'fastmcp'. The test also never makes a malformed call.

**How it was confirmed.** Script &lt;scratch&gt;/security-signin/argument_echo_probe.py, run against my server. It calls join_team with {"code": {"value": M}}, {"code": [M]} and {"cod": M}, where M is a marker that starts with aistinv_.
- Each returned error text contained M.
- `grep M server.log` found 4 hits inside Rich-formatted 'WARNING Invalid arguments for tool 'join_team': [{... 'input': {...M...}}]' blocks.
- A Python check after importing aistack.mcp.mcp: logging.getLogger('fastmcp').propagate is False, with handlers [RichHandler, RichHandler].

**Proposed fix.** (1) In bootstrap/__main__.configure_logging:
- remove fastmcp's RichHandlers and set propagate=True, so its records use LOG_FORMAT;
- attach a logging.Filter on 'fastmcp' that rewrites 'Invalid arguments for tool' records to keep only the tool name and the failing field names and types.
(2) In mcp/mcp.py, register a FastMCP middleware next to AuthMiddleware. Its on_call_tool catches fastmcp.exceptions.ValidationError and raises a ToolError that names the expected parameters with no input values, for example "join_team takes one argument, code: the aistinv_ code as text".
(3) Add a test that calls join_team with {"invite_code": marker} over HTTP and asserts the marker is absent from capfd stderr and from the tool result.

**Done when.** argument_echo_probe.py prints 'echoes the code: False' for every shape, and grep of the server log for the marker finds nothing. The new capfd test fails on main today and passes after the fix.

### SEC-04: Unauthenticated requests take SQLite's write lock: token checks, /health and the invite page all run BEGIN IMMEDIATE

**Confirmed.** Severity **Low**, effort **S**. Hurts: Everyone on a SQLite server (the default). The operator, whose container health check reports unhealthy whenever a write runs long.

**Where.** src/aistack/db/engine.py:27-28 and 64-71; src/aistack/mcp/auth/aistack_token_verifier.py:81-92; src/aistack/mcp/routes/health.py:33-35; src/aistack/mcp/routes/invite.py:70-72

**What is wrong.** The engine's 'begin' listener emits BEGIN IMMEDIATE for every transaction. That includes the transaction autobegun by the verifier's `with self._session_factory() as session` read, the /health ping, and the invite-page lookup.
- Every request with any bearer, even a random one, takes SQLite's single write lock before it is rejected. AGENTS.md describes this as a short-lived read session.
- When a writer holds the lock past the 5 s busy timeout, authentication itself fails for every caller with an unhandled 500. uvicorn logs it as 'Exception in ASGI application'.
- /health answers 503 at the same time, so the Dockerfile's health check marks the container unhealthy.
- An unauthenticated flood (SEC-02) competes with real writers for the lock instead of reading alongside them, as WAL would allow.

**How it was confirmed.** Script &lt;scratch&gt;/security-signin/write_lock_probe.py &lt;db file&gt; &lt;base url&gt;. It holds BEGIN IMMEDIATE from a second sqlite3 connection and times one request of each kind, unlocked and then locked:
- POST /mcp with a random bearer: 401 in 14 ms unlocked; 500 'Internal Server Error' after 5042 ms locked.
- GET /health: 200 in 5 ms; 503 after 5017 ms.
- GET /invite/&lt;wrong code&gt;: 404 in 4 ms; 500 'invite failed unexpectedly.' after 5030 ms.

The server log shows sqlalchemy OperationalError 'database is locked' with [SQL: BEGIN IMMEDIATE] under uvicorn.error.run_asgi.

**Proposed fix.** In db/engine.py, have _begin_immediate skip BEGIN IMMEDIATE when the connection carries an execution option such as aistack_read_only=True. Pysqlite in autocommit then reads under WAL without the lock.

In application_context, build a read-only sessionmaker bound to engine.execution_options(aistack_read_only=True). Use it for:
- the verifier's _find_machine and _is_team_invite;
- the health ping;
- the invite page lookup, which only reads.

Catch OperationalError in verify_token and answer 503 instead of an unhandled 500. Writers keep ADR-0014's behavior unchanged.

**Done when.** A new test in tests/db/test_sqlite_write_lock.py holds BEGIN IMMEDIATE on the database file and asserts that verify_token for an unknown bearer returns None in under 1 s, and that /health answers 200. write_lock_probe.py shows the unlocked timings in both columns.

Related: [DB-01](schema.md#db-01-dashboard-list_skills-and-sync-count-every-revision-and-file-on-the-whole-server-for-each-request-under-sqlites-write-lock), [ENT-04](concurrency-and-reliability.md#ent-04-on-sqlite-every-read-waits-for-the-global-write-lock-past-5-s-auth-fails-with-a-bare-http-500-tools-fail-as-failed-unexpectedly-and-health-returns-503), [STD-06](industry-standards.md#std-06-health-checks-bearer-checks-and-the-invite-page-take-sqlites-write-lock-so-one-slow-write-turns-them-into-503-and-500).

### SEC-05: Signing out does not end the session; a copied cookie keeps working for the rest of its 8 hours

**Confirmed.** Severity **Low**, effort **S**. Hurts: A member who signs out on a shared or borrowed computer, or whose cookie value was copied: by a browser extension, from devtools in a screenshot, or by a proxy on the plain-HTTP tailnet pattern.

**Where.** src/aistack/api/dashboard.py:145-151 (sign_out); src/aistack/services/transfer_ticket.py:122-128 (sessions carry no jti)

**What is wrong.** POST /api/logout only asks the browser to delete its cookie. The session is a stateless JWT with no id, and the server keeps no record that it ended, so the same value works until exp (8 hours).

The existing test, test_signing_out_ends_the_session_in_that_browser, only proves the browser forgets the cookie. Links already have the needed machinery: the in-memory _used_links set.

**How it was confirmed.** session_probe.py (same folder as above):
- captured the aistack_session value after sign-in;
- POST /api/logout returned 200 with Set-Cookie clearing it;
- GET /api/state with the captured value returned 200.

Re-traced by the main session: `sign_out` in src/aistack/api/dashboard.py:145-151 only deletes the cookie; nothing records the session as ended, and `_signed_in` accepts any unexpired session ticket.

**Proposed fix.** Add {"jti": uuid4} in sign_dashboard_session. Add TicketSigner.end_session(token), which verifies the token and remembers its jti until exp, the same way as _used_links, and check that set in verified_dashboard_session. sign_out calls end_session before deleting the cookie. Keeping it in memory matches ADR-0017, since a restart already ends every session.

**Done when.** A test in tests/api/test_dashboard_over_http.py copies the cookie, signs out, then sends the copy to /api/state and gets 401. It fails today.

Related: [SEC-01](#sec-01-a-stolen-machine-token-outlives-the-documented-revocation-sibling-tokens-dashboard-sessions-and-upload-urls-keep-working), [SEC-10](#sec-10-a-sign-in-link-silently-replaces-the-browsers-existing-session-login-csrf), [STD-03](industry-standards.md#std-03-a-dashboard-session-cannot-be-ended-not-by-signing-out-and-not-by-deleting-the-machine-that-opened-it).

### SEC-06: On PostgreSQL an admin's cancel can report success while the person it was meant to stop joins

**Confirmed.** Severity **Low**, effort **S**. Hurts: A team admin who cancels a link that reached the wrong person.

**Where.** src/aistack/services/team_service.py:214-231 (cancel_invite), compared with admit at 180-189

**What is wrong.** cancel_invite reads the invite, checks that used_on is None, then sets cancelled_on with an unconditional ORM update. Under PostgreSQL READ COMMITTED, a join_team that commits between that read and that write is admitted, and the cancel still returns success. The row ends with both used_on and cancelled_on set and is shown as ACCEPTED.

admit already uses the right pattern, a conditional UPDATE, but cancel does not. SQLite serializes the two through BEGIN IMMEDIATE.

**How it was confirmed.** Script &lt;scratch&gt;/security-signin/cancel_race.py &lt;url&gt;, run against my own PostgreSQL 16 database on port 8112.
- Thread A (cancel_invite) is held by events at its utc_now() call: after the used_on check, before the write.
- Thread B (join_team with the same code) commits inside that window.
- Then A continues.

Result: {'join': 'joined', 'cancel': 'reported success', 'invite row': 'used_on=set cancelled_on=set status shown=ACCEPTED', 'joiner is a member': True}.

On SQLite, the cancel committed first and the joiner was not admitted.

**Proposed fix.** Make the cancel conditional, the way admit is:

session.execute(update(Invite).where(Invite.invite_id == invite.invite_id, Invite.used_on.is_(None)).values(cancelled_on=func.coalesce(Invite.cancelled_on, now)))

When rowcount is 0, raise the existing 'already used' ValidationError. Keep the PostgreSQL barrier test in tests/db, next to test_admin_race_postgres.py.

**Done when.** The PostgreSQL barrier test (cancel held after its read, join commits) fails today. After the fix, the cancel answers 'That invite was already used'.

Related: [AUTHZ-01](#authz-01-removing-demoting-or-offboarding-an-inviter-leaves-their-invite-links-working-so-the-person-can-rejoin-the-team-or-create-a-new-account-on-the-server), [DB-06](schema.md#db-06-a-team-invite-outlives-its-makers-right-to-invite-offboarding-by-deleting-machines-removal-from-the-team-and-revoking-can_invite-all-leave-it-working), [ENT-09](concurrency-and-reliability.md#ent-09-an-admin-is-told-an-invite-was-cancelled-while-the-same-invite-admits-its-holder), [PH-02](plot-holes.md#ph-02-invites-outlive-the-person-who-made-them-so-removed-members-and-people-taken-off-the-server-keep-letting-new-accounts-in), [SEC-07](#sec-07-a-used-team-invite-code-still-authenticates-as-a-bearer-so-used-and-unknown-codes-answer-differently).

### SEC-07: A used team invite code still authenticates as a bearer, so used and unknown codes answer differently

**Confirmed.** Severity **Low**, effort **S**. Hurts: A team admin. The invariant 'a used, cancelled, expired and unknown code all answer alike' does not hold, and a used code stays a live bearer that reaches join for up to seven days.

**Where.** src/aistack/services/team_service.py:153-162 (is_open_invite accepts ACCEPTED); src/aistack/mcp/auth/aistack_token_verifier.py:46-57

**What is wrong.** is_open_invite treats PENDING and ACCEPTED invites alike, so a used code passes bearer verification:
- a used code: 200 on /mcp, and tools/list shows join;
- a cancelled, expired or unknown code: 401.

That tells anyone holding a code whether it was a real invite that has been used. The harm is small with 192-bit codes, but it breaks a rule AGENTS.md states explicitly.

**How it was confirmed.** Script &lt;scratch&gt;/security-signin/invite_probe.py, run against my server. tools/list status for:
- the used code: 200;
- the cancelled code: 401;
- a random aistinv_ code: 401.

join with the used code was refused with the shared sentence.

**Proposed fix.** Either:
- accept only PENDING in is_open_invite, and verify with a fastmcp Client test that the extra request after join tolerates the 401; or
- treat every aistinv_-prefixed bearer as a bootstrap principal with the invite='team' claim, so all four reach join and get the same sentence.

Add a four-way status assertion to tests/mcp/test_invite_over_http.py.

**Done when.** invite_probe.py prints the same bearer status for used, cancelled and unknown codes.

Related: [AUTHZ-01](#authz-01-removing-demoting-or-offboarding-an-inviter-leaves-their-invite-links-working-so-the-person-can-rejoin-the-team-or-create-a-new-account-on-the-server), [DB-06](schema.md#db-06-a-team-invite-outlives-its-makers-right-to-invite-offboarding-by-deleting-machines-removal-from-the-team-and-revoking-can_invite-all-leave-it-working), [ENT-09](concurrency-and-reliability.md#ent-09-an-admin-is-told-an-invite-was-cancelled-while-the-same-invite-admits-its-holder), [PH-02](plot-holes.md#ph-02-invites-outlive-the-person-who-made-them-so-removed-members-and-people-taken-off-the-server-keep-letting-new-accounts-in), [SEC-06](#sec-06-on-postgresql-an-admins-cancel-can-report-success-while-the-person-it-was-meant-to-stop-joins).

### SEC-08: One team invite link, or the server code, is an unlimited oracle for every username and team name on the server

**Confirmed.** Severity **Low**, effort **S**. Hurts: Members of private teams, whose team names leak to people outside them. Every user, whose username can be listed by anyone who ever received an invite link.

**Where.** src/aistack/services/onboarding_service.py:54-68 (join Conflict); src/aistack/services/team_service.py:95-104 (create_team Conflict)

**What is wrong.** join with a taken username answers "Username 'x' is already taken".
- The refusal rolls back, so a pending team code is not used up and can be replayed with any number of candidate names.
- A personal team shares the team namespace, so a username equal to an existing team name is refused the same way. Team names are enumerable through join as well.
- Any account can also probe team names with create_team ("already taken by a team or a user").

AGENTS.md says a team the caller may not see must read like one that does not exist. A global namespace makes some disclosure inherent, but here it is unthrottled and undocumented.

**How it was confirmed.** invite_probe.py, with one pending team code:
- join as 'dimitris', 'maria' and 'alex' each answered 'already taken';
- the same code then admitted a fresh name;
- create_team 'aistack' from an unrelated account answered "The name 'aistack' is already taken by a team or a user."

**Proposed fix.** Count refused joins per bearer and per address in the SEC-02 limiter, for example 5 per code per hour. State in DESIGN.md's Security posture that usernames and team names are server-wide and discoverable by any account or invite holder, so a private team's name should not itself be sensitive. Making team names unique per scope would need a new ADR.

**Done when.** A test makes 6 refused joins with one team code and gets the rate-limit answer on the 6th. DESIGN.md names the disclosure.

Related: [SEC-02](#sec-02-no-rate-limit-or-lockout-on-any-credential-check-and-the-invite-code-strength-check-accepts-trivially-guessable-codes), [STD-05](industry-standards.md#std-05-failed-authentication-is-never-throttled-and-never-logged-with-a-client-address).

### SEC-09: Dashboard actions buffer the whole request body before applying the 16 KiB limit

**Confirmed.** Severity **Low**, effort **S**. Hurts: Everyone on the server. One request from any signed-in account can exhaust the single process's memory on the small hosts OPERATING.md recommends, and a restart signs everyone out.

**Where.** src/aistack/api/dashboard.py:328-331 (_json_body)

**What is wrong.** _json_body awaits request.body(), which reads the entire body into memory, and only then compares its length with _MAX_BODY_BYTES. Elsewhere this is already handled:
- transfer.py's _bounded_body exists to avoid exactly this;
- the MCP endpoint refuses large bodies early with 413.

Accounts are cheap to get: the server's code or any team link creates one.

**How it was confirmed.** Script &lt;scratch&gt;/security-signin/body_size_probe.py, which reads VmRSS/VmHWM from the server's /proc status.
- A 200 MB POST to /api/teams, with a valid session and the request header, answered 400 'larger than 16384 bytes'. Peak memory rose from 127 to 527 MB.
- The same 200 MB POST to /mcp with the invite code answered 413 with no growth.

**Proposed fix.** Move transfer._bounded_body into a shared helper that takes a size limit, and use it in dashboard._json_body. Or check Content-Length first and stop reading the stream after _MAX_BODY_BYTES.

**Done when.** body_size_probe.py shows the /api/teams case refused with no memory growth. A unit test streams more than 16 KiB in chunks and asserts the refusal comes before the stream is drained.

### SEC-10: A sign-in link silently replaces the browser's existing session (login CSRF)

**Confirmed.** Severity **Low**, effort **S**. Hurts: A member tricked into opening someone else's link. A team admin, if the victim then pastes the team's invite code into what they think is their own dashboard.

**Where.** src/aistack/api/dashboard.py:88-115 (sign_in)

**What is wrong.** GET /app/login/&lt;ticket&gt; verifies only the link and sets the session cookie unconditionally. Anyone can mint links for their own account, and a top-level navigation can set a Lax cookie. So:
- a page or chat message that sends a victim to the attacker's link signs the victim's browser in as the attacker;
- if the victim then uses 'Join a team' with a code meant for them, the attacker's account joins that team and the invite is used up.

The only signal is the username in the breadcrumb. In server mode the cookie has no __Host- prefix, so a sibling subdomain can also set it.

**How it was confirmed.** Code trace of dashboard.py:96-113: verified_dashboard_link, then response.set_cookie, with no read of request.cookies. Existing tests cover link reuse but not switching users.

**Proposed fix.** In sign_in, if a valid session for a different user is present, answer a small page: 'You are signed in as X. This link signs you in as Y.' Its button calls a POST route that carries the request header and switches using a short-lived second ticket. Name the cookie __Host-aistack_session when _served_over_https is true.

**Done when.** A test opens user B's link in a browser signed in as A and gets the confirmation page. /api/state still answers as A until the switch is confirmed.

Related: [SEC-01](#sec-01-a-stolen-machine-token-outlives-the-documented-revocation-sibling-tokens-dashboard-sessions-and-upload-urls-keep-working), [SEC-05](#sec-05-signing-out-does-not-end-the-session-a-copied-cookie-keeps-working-for-the-rest-of-its-8-hours), [STD-03](industry-standards.md#std-03-a-dashboard-session-cannot-be-ended-not-by-signing-out-and-not-by-deleting-the-machine-that-opened-it).

### SEC-11: /setup fills its URLs from the Host header and sends no Cache-Control, so a caching proxy could serve a poisoned copy

**Suspected.** Severity **Low**, effort **S**. Hurts: A newcomer on a server run without AISTACK_PUBLIC_URL behind a cache. Their agent would send the invite code to another host and install that host's sync skill.

**Where.** src/aistack/mcp/routes/setup.py:21-32; src/aistack/mcp/server_url.py:16-37

**What is wrong.** With AISTACK_PUBLIC_URL unset, {server_url} and {mcp_url} come from the request's Host, and the response carries no Cache-Control and no Vary. The setup text tells the agent to:
- POST the invite code as a bearer to {mcp_url};
- download sync-aistack/SKILL.md from {server_url}.

A shared cache that does not key on Host could be poisoned once with Host: attacker.example. OPERATING.md already says to set AISTACK_PUBLIC_URL behind a proxy, which lowers the likelihood.

**How it was confirmed.** session_probe.py: GET /setup with Host: attacker.example:9999 answered 200 with 6 lines naming http://attacker.example:9999, and its headers had no cache-control. The cache step itself was not reproduced, hence Suspected.

**Proposed fix.** Send Cache-Control: no-store and Vary: Host from setup() and sync_skill(), as the dashboard and invite pages already do.

**Done when.** tests/mcp/test_setup_over_http.py asserts Cache-Control: no-store on /setup.

### SEC-12: The documented run commands expose the plain-HTTP port: the quick-start on every interface with a public code, and the TLS proxy pattern still publishing 8000

**Confirmed.** Severity **Low**, effort **S**. Hurts: A newcomer trying the README on café or office Wi-Fi. An operator following the VPS-plus-proxy pattern, whose machines may keep talking to the server in clear text.

**Where.** README.md:39 together with src/aistack/bootstrap/configuration/settings/settings_config.py:39-43; docs/OPERATING.md:8-13 and 66-78; compose.yaml:12-13

**What is wrong.** (a) 'Try it in two minutes' runs aistack serve with the default host 0.0.0.0 and the invite code printed in the public README. Anyone on the same network can join that person's server and run the SEC-02 and SEC-08 probes.
(b) OPERATING's docker run and compose.yaml publish 8000:8000 on every interface, while its TLS pattern proxies to 127.0.0.1:8000.
- The plain-HTTP port stays reachable from the internet, because Docker's published ports bypass ufw.
- A machine first connected at http://&lt;ip&gt;:8000 keeps sending its token in clear text.
- Guessing can skip whatever the proxy enforces.

**How it was confirmed.** Read the docs. /proc/net/tcp shows the running demo server listening on 00000000:1F40 (0.0.0.0:8000). Settings.host defaults to '0.0.0.0'.

**Proposed fix.** README quick-start: `AISTACK_HOST=127.0.0.1 AISTACK_INVITE_CODE=... poetry run aistack serve`. OPERATING reverse-proxy pattern: use `-p 127.0.0.1:8000:8000` (plus a compose override), and note that published ports bypass host firewalls. The container's own default of 0.0.0.0 stays, because it is needed inside the container.

**Done when.** The README and OPERATING commands bind loopback for those two patterns, and a docs test greps for it, in the style of test_dashboard_routes_are_documented.

### SEC-13: Local mode on a shared computer: AISTACK_HOME is world-readable, and the one-use sign-in link is visible on the browser's command line

**Confirmed.** Severity **Low**, effort **S**. Hurts: Someone using local mode on a multi-user Linux host, such as a shared dev box or a lab machine.

**Where.** src/aistack/bootstrap/context/application_context.py:92 (settings.home.mkdir with default mode); src/aistack/bootstrap/__main__.py:100 and src/aistack/mcp/tools/local.py:300-302 (webbrowser.open(link))

**What is wrong.** AISTACK_HOME is created with mkdir's default mode, and SQLite creates its files 0644. With umask 022, every other account can read the whole Library: aistack.db and its -wal and -shm files, plus the GitHub copy and clone.

Both `aistack dashboard` and the local open_dashboard tool pass the sign-in link to webbrowser.open, which launches the browser with the URL in its argv. Another account polling /proc/*/cmdline can use the one-use link first and hold an 8-hour session on the person's 127.0.0.1 dashboard.

The local-mode review (3027697, a47a636, 8baf315) did not cover this.

**How it was confirmed.** stat on the provided local2 run: AISTACK_HOME 755; aistack.db, -wal, -shm and machine-id 644 (umask 0022). Ran webbrowser.open with BROWSER set to a stub script, then read /proc/&lt;pid&gt;/cmdline from another process: the full /app/login/&lt;ticket&gt; URL was there.

**Proposed fix.** In build_local_context, create settings.home with mode 0o700 and chmod an existing one to 0o700 (POSIX only). Open the browser on a 0600 HTML file in AISTACK_HOME that redirects to the link, so argv shows only a file path, then delete the file.

**Done when.** After `aistack check` on Linux, stat shows 700 on AISTACK_HOME. The launched browser's /proc cmdline contains no /app/login/.

### SEC-14: A rejected bearer gets FastMCP's OAuth text telling the client to 're-register', which AIStack cannot do

**Confirmed.** Severity **Low**, effort **S**. Hurts: A person whose machine token was rotated after a loss (SEC-01's runbook), and whose agent is told something that cannot work. Also a newcomer with a mistyped invite code.

**Where.** FastMCP's bearer middleware, used by src/aistack/mcp/mcp.py:47 (mcp.http_app)

**What is wrong.** A wrong, rotated or deleted bearer gets: 'Authentication failed... To resolve: clear authentication tokens in your MCP client and reconnect. Your client should automatically re-register and obtain new tokens.'
- AIStack has no OAuth: /.well-known/oauth-protected-resource answers 404, and nothing re-registers.
- Nothing tells the person to ask the operator for the new token.

AGENTS.md calls error text agent-facing UX.

**How it was confirmed.** curl POST /mcp with a wrong bearer: 401 with that body and the same WWW-Authenticate error_description. GET /.well-known/oauth-protected-resource: 404. Neither echoes the bearer.

**Proposed fix.** Wrap the /mcp app's 401 in mcp.http_server_config (a small ASGI wrapper) and answer AIStack's own sentence, without the bearer: 'This bearer is not an invite code that works or a machine token this server knows. A computer that was connected before may have had its token replaced: ask whoever runs the server, then reconnect with the new one.'

**Done when.** tests/mcp/test_join_over_http.py asserts the 401 body carries AIStack's sentence and does not contain 're-register'.

## Authorization: who may see and change what

I verified the security-authz findings on my own server (port 8420, fresh SQLite, now stopped) and with service-level scripts. My scripts and outputs are in &lt;scratch&gt;/verify-security-authz/ (v_probe.py, v_services.py, v_timing.py, v_orphan.py, v_race_admin.py, each with a .out file). I changed nothing in the repository.

Results:
- AUTHZ-01 (leftover invite links) holds as written and is wider than reported. A voluntary leave also leaves the links working, and so does switching off can_invite. Kept at High: it defeats the operator's documented offboarding.
- AUTHZ-02 (sharing over a group's skill) reproduces exactly. But ADR-0015 contradicts itself here. Line 21 and DESIGN.md:546 say "any member may share over a team's skill; the control is visibility". Lines 27-28 and the TeamMember model comment say seeing a group does not make it writable, and that sees-all is read-only. The code follows line 21 and even tells the caller to do it. I corrected it to Medium and an owner decision. The sees-all case is the clear contradiction.
- AUTHZ-03 (private group names in the Members list) reproduces and is kept.
- AUTHZ-04 (last-admin race on PostgreSQL) is now Confirmed by code trace: no lock, no constraint, default READ COMMITTED. It was not run on PostgreSQL. The shared cluster at :5433 is still down, and starting a private one was denied. I lowered it to Low: only near-simultaneous admin actions trigger it, and members can still share and take.
- AUTHZ-05 (a sole member cannot leave) is kept.
- AUTHZ-06 (team names reserve usernames) is dropped. The shared namespace is a stated design decision (DESIGN.md:250, team_service.py:45, test_teams.py:101), and the refusal already says "Pick a different one".
- AUTHZ-07 (timing oracle) is kept. The hidden path runs 3 more SQL statements in both places, and the HTTP median gap is about 0.7 ms with identical 404s.
- AUTHZ-08 (test coverage) is corrected. A hand-written outsider check does exist for 5 dashboard routes.

I added one finding the finder missed. Offboarding a team's only admin exactly as docs/OPERATING.md says leaves the team with an admin nobody can reach. There is no product or documented way back.

### AUTHZ-01: Removing, demoting or offboarding an inviter leaves their invite links working, so the person can rejoin the team or create a new account on the server

**Confirmed.** Severity **High**, effort **S**. Hurts: Team admins and the operator, who believe a person is gone, and every member of that team, whose skills that person can read again

**Where.** src/aistack/services/team_service.py:133-150 (invited_to), :153-162 (is_open_invite), :170-193 (admit), :499-504 (_drop_member), :335-358 (set_member); docs/OPERATING.md:201-205; src/aistack/bundled/dashboard.html:2075

**What is wrong.** _drop_member, used by remove_member and leave_team, deletes only the GroupMember and TeamMember rows. The person's pending invites stay PENDING. Demoting an admin, or switching off can_invite, also leaves their pending invites alone. invited_to and admit never check whether the invite's maker is still in the team, still allowed to invite, or still on the server.

So a removed member, or one who left, can rejoin with a code they made earlier. Because of ADR-0019, any leftover code is also a bootstrap bearer for `join` and creates a brand-new account in the team. This still works after the operator follows OPERATING.md 'Someone left': deleting the machines and rotating AISTACK_INVITE_CODE does not touch team invites.

After demotion, or losing can_invite, the person can no longer see or cancel their own pending invites, yet those links still admit people. Meanwhile the remove dialog promises '&lt;username&gt; stops seeing this team's skills and groups.'

**How it was confirmed.** Re-run on my own server (port 8420, fresh SQLite) with &lt;scratch&gt;/verify-security-authz/v_probe.py; output in v_probe.out next to it, tokens redacted. Admin vadm creates team vinitech. vkim joins, is given can_invite, and makes 3 codes with invite_to_team. vadm then removes her.
- 01.1: kim's list_teams is [].
- 01.2: kim's join_team with her own leftover code returns OK {'team':'vinitech'}.
- 01.4: tools/list with her second code as bearer returns ['join'].
- 01.5: a new user vmal joins with that code and lands in team vinitech.
- 01.6: the admin's invite list still shows kim's other codes as PENDING.
- 01.7-01.9: vlee is made ADMIN, makes a link and is demoted. His invites list is [], invite_to_team is refused, and a new user vzed joins with his link.
- 01.10-01.13: kim's machines are deleted with build_engine, as OPERATING.md says. Her old token gets 401, yet her third leftover code still lists ['join'] and creates account vkim2 in vinitech.

Service-level variants in v_services.py (v_services.out):
- After can_invite is switched off, kim's code still admits new1, and her attempt to cancel her own invite is refused 'Only an admin…'.
- After kim leaves voluntarily, her other code admits new2.

No existing test covers this: test_a_member_who_may_no_longer_invite_cannot (tests/services/test_teams.py:457) checks only that she cannot make new invites.

Second pass (kept): Re-read invited_to, is_open_invite, admit, _drop_member and set_member at the cited lines, and re-ran every step on my own server and at service level. All reproduced. I also confirmed two variants the finder only implied: a voluntary leave, and can_invite switched off. ADR-0019 and ADR-0022 say nothing about an invite outliving its maker's rights, so this is not a deliberate decision. Severity stays High. The window is bounded by the 7-day lifetime, and an admin can see and cancel the pending codes, but nothing prompts them to, and the operator's only documented offboarding step is defeated by a full new account. I refined the fix to make cancel-on-drop the primary step, which needs no read-time check, and kept the read-time check for the operator path.

**Proposed fix.** 1. In team_service._drop_member, set cancelled_on=utc_now() on the leaving person's pending invites for that team. Do the same in set_member when the change leaves the person unable to invite (role becomes MEMBER without can_invite, or can_invite becomes False for a non-admin). is_open_invite and invited_to already treat CANCELLED as unknown, the admin's list shows them as Cancelled, and no migration is needed.
2. As defence in depth, in team_service.invited_to and is_open_invite, accept an invite only while its maker is still a TeamMember of invite.team_id with role ADMIN or can_invite, and still has a Machine. That is the same 'still on the server' proxy dashboard_service.require_a_machine uses. Otherwise raise NotFound(_NOT_AN_INVITE). This covers the operator's offboarding, which today leaves memberships in place.
3. Add a build_engine script to OPERATING.md 'Someone left' that cancels the person's pending invites and takes them out of their teams (see AUTHZ-V01).

No new ADR is needed: ADR-0022 already says a cancelled invite answers like an unknown one.

**Done when.** New tests in tests/services/test_teams.py fail on today's main and pass after the fix: 'a removed member's invites admit nobody, themselves included', 'a member who left leaves no working invite', 'a demoted admin's or a no-longer-inviting member's invites admit nobody'. In tests/mcp/test_teams_over_http.py, tools/list with an offboarded maker's code answers 401. Rerunning v_probe.py prints REFUSED/ERROR for 01.2, 01.5, 01.9 and 01.13.

Related: [DB-06](schema.md#db-06-a-team-invite-outlives-its-makers-right-to-invite-offboarding-by-deleting-machines-removal-from-the-team-and-revoking-can_invite-all-leave-it-working), [ENT-09](concurrency-and-reliability.md#ent-09-an-admin-is-told-an-invite-was-cancelled-while-the-same-invite-admits-its-holder), [PH-02](plot-holes.md#ph-02-invites-outlive-the-person-who-made-them-so-removed-members-and-people-taken-off-the-server-keep-letting-new-accounts-in), [SEC-06](#sec-06-on-postgresql-an-admins-cancel-can-report-success-while-the-person-it-was-meant-to-stop-joins), [SEC-07](#sec-07-a-used-team-invite-code-still-authenticates-as-a-bearer-so-used-and-unknown-codes-answer-differently).

### AUTHZ-02: A member who can only see a group (an open group's non-member, or a 'sees all groups' member) can push a new revision into that group's skill by sharing without a group

**Confirmed.** Severity **Medium**, effort **S**. Hurts: Members of a group who took a skill from it, private groups included: their sync and dashboard offer them a revision pushed by someone outside the group. Not applied without their yes.

**Where.** src/aistack/services/skill_service.py:252-279 (share; writability checked only in _group_to_share_into at :527-540), message at :268-271; src/aistack/services/visibility.py:123; docs/adr/0015-teams-and-groups.md:21 vs :27-28; src/aistack/db/models/team.py:69-70; tests/services/test_teams.py:593

**What is wrong.** share() checks GroupAccess.writable only when the caller names a group. With no group, the only check on an existing skill is that the caller can see it (:260-265). _find_or_create_skill then returns the existing skill in its group, _store_revision adds a revision there, and the description is replaced.

The documents disagree about whether that is allowed:
- For it: ADR-0015 line 21 and DESIGN.md:546 say 'Any member may change a team's skill, by sharing over it. The control is visibility, not restriction.' The refusal at :268-271 even tells the caller to 'Share it without a group to update it where it is'.
- Against: ADR-0015 lines 27-28 say 'Seeing an open group does not make it writable', and that sight of every group 'grants reading and taking, not sharing'. The TeamMember model comment says 'Reading only', and the test at tests/services/test_teams.py:593 is named '…reads them all and writes to none', though it only tries to create a new skill in the group.

The open-group case fits line 21. The sees-all case, writing into a private group the person is not in, contradicts line 28, the model comment and the test name.

**How it was confirmed.** Re-run with &lt;scratch&gt;/verify-security-authz/v_probe.py (v_probe.out). Team vacme has an open group 'backend' (vben in it), a private 'security' and an open 'security/tools' under it. veve is in no group; vsam has sees_all_groups. vada shares sql-style into backend and pentest into security, and vben takes sql-style.
- 02.1: eve's share into group=backend is refused 404.
- 02.2: her MCP share_skill with no group returns group 'backend', revision 2, previous_pushed_by 'vada', possibly_unrelated True.
- 02.3: ben's sync team_updates offers sql-style 1→2, pushed_by veve.
- 02.4: sam's share into security is refused 404.
- 02.5: with no group, sam gets revision 2 in group 'security'.
- 02.6: ada's list_skills shows vacme/security pentest at revision 2, pushed_by vsam.

Second pass (corrected): The behaviour reproduces exactly. I corrected the framing and the severity. The finder wrote 'ADR-0015 says that is not allowed', but ADR-0015 line 21 and DESIGN.md:546 explicitly allow any member to share over a skill they can see, and the code's own refusal text points callers at this path. So the open-group half is arguably by design, and the ADR is self-contradictory. The sees-all-into-private half does contradict the ADR (line 28), the model comment and the test name. Severity goes from High to Medium: the revision only becomes an offer that names who pushed it, and the people who can do this are team members the admin already trusts with sight of the group. I added the ADR amendment to the fix in either direction.

**Proposed fix.** This needs an owner decision, and ADR-0015 has to be amended either way, because it states both rules.

Recommended: make 'seeing is not writing' hold for revisions too, which matches lines 27-28, the model comment and the test name. Add a predicate to visibility.py, e.g. `may_write_team_skill(session, user_id, skill) -> bool`: true for a team-level skill, otherwise skill.group_id must be in group_access(...).writable. In skill_service.share, after the can_see_team_skill check, refuse an existing skill that is not writable with a Conflict that names the group the caller can already see, e.g. "'sql-style' is in group 'backend' of team 'acme', which you can read but not share into. Ask a team admin to add you, or share it under a different name." Reword :268-271 to suggest sharing without a group only when the caller can write where the skill is. Amend ADR-0015 line 21 to 'Any member may change a team's skill where they may share'.

Alternative: keep today's behaviour, amend lines 27-28 to say that writability decides only where a new skill goes, and rename the test.

**Done when.** With the recommended option, using the groups fixture in tests/services/test_teams.py: eve sharing her own 'sql-style' with no group raises Conflict, and the team's sql-style stays at revision 1 by dimitris. With sees_all, eve sharing over 'pentest' with no group raises. maria (in backend/aistack) sharing over 'api-notes' with no group still succeeds. Rerunning v_probe.py prints refusals for 02.2 and 02.5. ADR-0015 states one rule.

### AUTHZ-03: The team member list leaks private group names through the paths of open subgroups under them

**Confirmed.** Severity **Medium**, effort **S**. Hurts: Members of private groups: the group's name, that it has subgroups, and who is in them are shown to everyone in the team

**Where.** src/aistack/services/team_service.py:260-281 (members, filter at :277-279; _groups_of at :479-484); surfaced by src/aistack/services/dashboard_service.py:49-54 as /api/state teams[].members[].groups and drawn as chips on the Members screen (src/aistack/bundled/dashboard.html:2060-2061)

**What is wrong.** members() hides a member's group only when that group is itself private. An open group nested in a private one is not visible to non-members (visibility.group_access, lines 119-120). But its path, e.g. 'security/tools', is not private, so every member sees it in the list. That reveals the private parent's name, that it has subgroups, and who is in them.

groups() hides the same groups correctly. The rule is decided in team_service rather than visibility.py, against AGENTS.md ('Who may see what is decided in services/visibility.py and nowhere else').

**How it was confirmed.** Re-run with &lt;scratch&gt;/verify-security-authz/v_probe.py (v_probe.out). vada creates private 'security' and an open 'security/tools' under it, and the creator is added to each. In veve's /api/state:
- 03.1: groups = [backend] only.
- 03.2: members shows vada: ['backend', 'security/tools'].
- 03.3: skills show only backend/sql-style.

Traced the filter at team_service.py:277-279: `not private or me.role is ADMIN or name in mine`.

Second pass (kept): Reproduced exactly on my own server and re-traced the filter. ADR-0015 says a private group is seen only by its members, and the groups() docstring says its name alone can say too much, so this is not deliberate. Medium stays: the disclosure needs no effort and reaches every team member, though only names and memberships leak, not skills.

**Proposed fix.** In team_service.members, compute `access = visibility.group_access(session, user_id)` once. Have _groups_of return group_id along with the path. Show a member's group only if me.role is ADMIN, or (group_id in access.visible and (not private or group_id in access.member)). That keeps today's rule (private groups shown only to admins and to people in them) and adds the ancestor rule. Better, put that predicate in visibility.py as e.g. `shows_membership(access, group_id, private)`.

**Done when.** Add an open 'security/tools' to the groups fixture in tests/services/test_teams.py. A test asserts that team_service.members, seen by eve, lists dimitris with ['backend'] only, and that an admin still sees all four paths. Rerunning v_probe.py shows vada: ['backend'] in 03.2.

### AUTHZ-V01: Offboarding a team's only admin as docs/OPERATING.md says leaves the team with an admin nobody can reach, and no way to name a new one

**Confirmed.** Severity **Medium**, effort **S**. Hurts: Every remaining member of a team the departed person administered alone (a common case: the team's creator leaves). Nobody can invite, manage members or groups, or remove skills, and every refusal says 'Ask one of its admins'.

**Where.** docs/OPERATING.md:201-205 ('Someone left: take them off the server') and :99 ('Nothing in a team needs the operator'); src/aistack/services/team_service.py:436-449 (_as_inviter/_as_admin refusals), :487-496 (_keep_an_admin counts the departed admin)

**What is wrong.** The documented offboarding deletes the person's machines and rotates the server code. It leaves their TeamMember rows, roles and can_invite flags in place. If they were a team's only admin, the team now has an admin who can never sign in. The remaining members cannot promote themselves, and OPERATING.md has no script to make someone a team's admin. The departed person also stays listed in the team as ADMIN.

The same happens if one of two admins is offboarded: the departed admin still counts in _keep_an_admin, so the remaining admin may leave, and the team is left with only the ghost admin. This contradicts OPERATING.md:99, 'Nothing in a team needs the operator'. It is also why AUTHZ-01's leftover invites survive offboarding.

**How it was confirmed.** &lt;scratch&gt;/verify-security-authz/v_orphan.py against my own server (port 8420, fresh SQLite), output in v_orphan.out. oboss creates team vorphan, and omem joins with its invite. oboss's machines are deleted through build_engine, exactly as OPERATING.md says ('deleted machines: 1'), and oboss's dashboard then answers 401.
- omem's /api/state lists members [[oboss, ADMIN], [omem, MEMBER]].
- omem POSTs /teams/vorphan/members/omem {role: ADMIN}, /teams/vorphan/invite, /teams/vorphan/members/oboss/remove and /teams/vorphan/groups. All answer 400 'Only an admin of team 'vorphan'… Ask one of its admins.'
- Only leaving works (200).

Read OPERATING.md end to end for an admin-recovery script: none.

**Proposed fix.** Add a service function that an OPERATING.md script calls through build_engine, so it runs the same on SQLite and PostgreSQL, e.g. `team_service.offboard(session, username, successors: dict[str, str])`. For each SHARED team the person is in, it:
- promotes the named successor to ADMIN when the person is that team's last admin, and refuses with a sentence naming the team when no successor is given;
- cancels the person's pending invites (as in AUTHZ-01);
- takes them out with _drop_member.

Put it in OPERATING.md 'Someone left' before the machine deletion. Add a short 'Make someone a team's admin' script for teams already in this state, which also serves AUTHZ-04. Run both scripts against a real database before committing, as AGENTS.md requires. No ADR change is needed: ADR-0015 already says a team always has an admin.

**Done when.** A test in tests/services/test_teams.py offboards a team's only admin with a successor: the successor is ADMIN, the departed person is no longer a member, and their pending invites read as CANCELLED. Without a successor the call is refused with a sentence naming the team. Rerunning v_orphan.py after following the updated OPERATING.md shows omem able to make an invite (200), and oboss no longer in the member list.

Related: [AUTHZ-04](#authz-04-the-team-keeps-an-admin-check-counts-first-and-writes-later-without-a-lock-on-postgresql-two-simultaneous-leaves-or-demotions-leave-a-team-with-no-admin), [AUTO-13](automation.md#auto-13-the-documented-offboarding-leaves-a-team-whose-only-admin-left-with-no-admin-anyone-can-reach), [DB-05](schema.md#db-05-teams-can-be-left-with-no-admin-or-no-members-on-postgresql-the-last-admin-check-is-a-racy-count), [DB-07](schema.md#db-07-offboarding-a-teams-only-admin-leaves-the-team-permanently-unmanaged-and-no-operator-script-exists-to-repair-it), [ENT-01](concurrency-and-reliability.md#ent-01-two-admins-acting-at-once-on-postgresql-leave-a-team-with-no-admin), [PH-05](plot-holes.md#ph-05-taking-a-teams-only-admin-off-the-server-leaves-the-team-with-nobody-who-can-manage-it-and-operating-has-no-fix).

### AUTHZ-04: The 'team keeps an admin' check counts first and writes later without a lock; on PostgreSQL two simultaneous leaves or demotions leave a team with no admin

**Confirmed.** Severity **Low**, effort **S**. Hurts: Every member of the team: with no admin nobody can invite, manage members or groups, or remove skills, and there is no product or OPERATING.md way back (members can still share and take)

**Where.** src/aistack/services/team_service.py:487-496 (_keep_an_admin), called from leave_team :317-322, remove_member :325-332, set_member :350-352

**What is wrong.** _keep_an_admin counts ADMIN rows, and the caller then deletes or updates a different row, with no lock in between. src/aistack/db/engine.py sets no isolation level for PostgreSQL, so it runs at the default READ COMMITTED. There is no with_for_update anywhere in services/, and no constraint keeps a team at one admin or more.

Cases that leave zero admins on PostgreSQL:
- Two admins leave at once.
- Two admins demote each other at once. B's _as_admin check still reads B as ADMIN because A's update is not yet committed.
- One admin sends 'remove the other admin' and 'leave' concurrently.

In each case both transactions read 2 admins, write different rows without waiting for each other, and commit. On SQLite, BEGIN IMMEDIATE (ADR-0014) serializes them.

**How it was confirmed.** Code trace: team_service.py:317-322 → :491-494 count → :499-504 delete. set_member :342-352 → count → their.role updated at flush. engine.py:20-30 adds BEGIN IMMEDIATE only for SQLite. ADR-0008 documents the same READ COMMITTED behaviour for the server-admin guard.

Harness: &lt;scratch&gt;/verify-security-authz/v_race_admin.py &lt;db url&gt; leave|demote. It holds both transactions at a threading.Barrier right after the count. On SQLite both modes print 'barrier broken … serialized' and admins_left = 1 (v_race_admin.out).

Not executed on PostgreSQL: 127.0.0.1:5433 refuses connections, and initdb of a private cluster in my folder was denied by the permission system.

Second pass (corrected): Re-traced every statement on both paths and confirmed there is no lock, no constraint and no PostgreSQL isolation override. The write skew follows from READ COMMITTED semantics, which the project itself documents in ADR-0008. So I changed the status from Suspected to Confirmed by code trace, and say plainly that it was not executed on PostgreSQL. Severity goes from Medium to Low: it needs two admin actions within milliseconds, and the realistic deliberate trigger is a single admin firing two requests, who could already harm the team in other ways. The team keeps working for sharing and taking.

**Proposed fix.** At the start of _keep_an_admin, before counting, lock the team's row so that membership changes for one team run one at a time: `session.execute(select(Team.team_id).where(Team.team_id == team.team_id).with_for_update())`. Under READ COMMITTED, the count after the lock sees the other transaction's committed change. SQLite renders no FOR UPDATE and is already serialized.

Add a PostgreSQL-only Barrier test (skip on SQLite), modelled on test_two_people_using_one_invite_at_once_let_exactly_one_in in tests/services/test_teams.py, for both leave and mutual demotion. The operator recovery script ('make someone a team's admin') is shared with AUTHZ-V01.

**Done when.** With TEST_DATABASE_URL set, `v_race_admin.py postgresql+psycopg://…/<disposable db> leave` and `… demote` each print one refusal 'That would leave team…' and admins_left = 1. The new PostgreSQL test fails without the lock and passes with it.

Related: [AUTHZ-V01](#authz-v01-offboarding-a-teams-only-admin-as-docsoperatingmd-says-leaves-the-team-with-an-admin-nobody-can-reach-and-no-way-to-name-a-new-one), [AUTO-13](automation.md#auto-13-the-documented-offboarding-leaves-a-team-whose-only-admin-left-with-no-admin-anyone-can-reach), [DB-05](schema.md#db-05-teams-can-be-left-with-no-admin-or-no-members-on-postgresql-the-last-admin-check-is-a-racy-count), [DB-07](schema.md#db-07-offboarding-a-teams-only-admin-leaves-the-team-permanently-unmanaged-and-no-operator-script-exists-to-repair-it), [ENT-01](concurrency-and-reliability.md#ent-01-two-admins-acting-at-once-on-postgresql-leave-a-team-with-no-admin), [PH-05](plot-holes.md#ph-05-taking-a-teams-only-admin-off-the-server-leaves-the-team-with-nobody-who-can-manage-it-and-operating-has-no-fix).

### AUTHZ-05: The only member of a team can never leave it, and no team can be deleted; the page's own demo lets them

**Confirmed.** Severity **Low**, effort **M**. Hurts: Anyone who created a team by mistake or is the last person left in one: the team stays in their dashboard and list_teams for good, and its name, shared with usernames, stays reserved

**Where.** src/aistack/services/team_service.py:317-322 and :487-496; src/aistack/bundled/dashboard.html:2350-2361 (Leave card shown to everyone), demo handler :2635-2638

**What is wrong.** leave_team runs _keep_an_admin with leaving=True. For a team whose only member is its admin, it raises 'That would leave team 'solo' with no admin. Make someone else an admin first.', but there is nobody to promote. No tool or route deletes a team. The page's built-in demo handler refuses only when `t.members.length > 1`, so the page expects a sole member to be able to leave, and the server disagrees.

**How it was confirmed.** &lt;scratch&gt;/verify-security-authz/v_probe.py step 05.1: veve creates 'vsolo' and POSTs /api/teams/vsolo/leave, which returns 409 'That would leave team 'vsolo' with no admin. Make someone else an admin first.' Grepped team_service.py, api/dashboard.py and mcp/tools/teams.py: no delete-team action exists. Read dashboard.html:2350-2361 (the Leave card is unconditional) and :2635-2638 (the demo condition).

Second pass (kept): Reproduced (409) on my own server, and confirmed that no delete-team action exists and that the demo handler disagrees with the server. ADR-0015's 'a team always has at least one admin' does not address an empty team, so this is a dead end rather than a deliberate limit, and README 'Known limits' does not mention it. Low is right.

**Proposed fix.** In _keep_an_admin, allow the change when the leaver is the team's last member. leave_team then removes the empty team: its invites, groups (their members and unsubscriptions cascade), its skills (as remove_skill does; personal copies keep their history because source_skill_id is ON DELETE SET NULL), and the team row, which frees the name. Record this as a short amendment to ADR-0015: a team still always has an admin, because an empty team stops existing. Update DESIGN.md's dashboard route table.

**Done when.** A test in tests/services/test_teams.py: the sole member leaves, the team disappears from list_teams, a copy taken from it stays in the Library, and create_team with the same name succeeds. v_probe.py 05.1 returns 200.

Related: [PH-04](plot-holes.md#ph-04-a-team-or-group-can-never-be-deleted-or-renamed-a-lone-admin-can-never-leave-team-names-take-usernames-for-good), [PH-16](plot-holes.md#ph-16-a-username-is-permanent-shares-a-namespace-with-team-names-and-a-taken-one-is-always-explained-as-this-is-you-on-a-new-computer), [UX-03](ux.md#ux-03-a-team-made-by-mistake-can-never-be-removed-its-only-member-cannot-leave-and-nothing-deletes-or-renames-a-team-or-group).

### AUTHZ-07: A private group that exists answers slower than one that does not, so a member can probe private group names by timing

**Confirmed.** Severity **Low**, effort **S**. Hurts: Private groups, whose names 'alone can say too much' (team_service.groups docstring)

**Where.** src/aistack/services/team_service.py:307-310 (set_subscribed: _group, then group_access only when found); src/aistack/services/skill_service.py:534-539 (_group_to_share_into short-circuits on a missing group)

**What is wrong.** Both routes give the same sentence and the same 404 for a hidden group and a missing one, which is correct. But a hidden group also runs visibility.group_access (three more SQL statements) and a missing one does not, so the hidden answer takes measurably longer.

**How it was confirmed.** Statement counts in &lt;scratch&gt;/verify-security-authz/v_services.py (v_services.out), using a SQLAlchemy before_cursor_execute listener on a fresh SQLite file:
- set_subscribed: 6 statements for a hidden private group 'hush', 3 for a missing 'nope'.
- share into a group: 7 vs 4.
Both answer identical NotFound sentences.

Timing over HTTP with v_timing.py (v_timing.out): a member POSTs /api/teams/vtime/group {path, subscribed:false}, alternating 'hush' and 'nope', 300 rounds each. Medians 5.45 vs 4.72 ms, p10 4.78 vs 4.10 ms, p90 7.32 vs 6.30 ms. Both answer 404 "Team 'vtime' has no group 'X'."

Second pass (kept): Independently re-measured. The statement-count gap (3 statements on both paths) is deterministic, and the HTTP median gap of about 0.7 ms on localhost matches the finder's runs. Low stays: it needs a member, many samples and guessed names.

**Proposed fix.** Make both paths do the same work. In set_subscribed and _group_to_share_into, compute group_access before the lookup. Or look the group up already filtered by visibility (`TeamGroup.team_id == …, TeamGroup.path == …, TeamGroup.group_id.in_(access.visible)` or `.writable`), with None meaning 'not there' either way.

**Done when.** A test counts SQL statements (before_cursor_execute listener) for set_subscribed and for share-into-group on a hidden group and on a missing one, and the counts are equal. Rerunning v_services.py prints equal counts.

### AUTHZ-08: OUTSIDER_VIEW checks only that each tool has a label; most labels are never exercised, and there is no matrix for a member who sees but cannot write, or cannot see a private group

**Confirmed.** Severity **Low**, effort **M**. Hurts: Maintainers: authorization regressions such as AUTHZ-03 and the sees-all half of AUTHZ-02 pass the suite

**Where.** tests/mcp/test_teams_over_http.py:27-99 (OUTSIDER_VIEW, REFUSED_CALLS and the label test), :303-335; tests/api/test_dashboard_over_http.py:245-290

**What is wrong.** test_every_machine_tool_has_a_stated_view_for_an_outsider asserts only that the registered tool names equal the OUTSIDER_VIEW keys, and that the 'refused' tools match REFUSED_CALLS. Only 'refused' drives a parametrized behaviour test.
- 'hidden' is checked by one hand-written test of three fixed tools (list_skills, list_teams, sync), so a future tool labelled 'hidden' is never called.
- 'own' is never checked against a team.
- The matrix covers only someone outside the team. Nothing pins what share_skill (with and without a group), get_skill(team), sync team_updates or /api/state show a member outside a private group, an open group's non-member, or a sees_all member.
- Dashboard routes have a hand-written outsider loop over 5 routes (leave, invite, take, groups, share) and an admin-only check over 4. Neither is tied to the registered routes, so a new team route needs no row.

**How it was confirmed.** Read the test code at the cited lines. Ran `poetry run pytest -q -p no:cacheprovider tests/services/test_teams.py -k "group or admin or invite"`: 26 passed, 1 skipped, on the same main where v_probe.py reproduces AUTHZ-02 and AUTHZ-03.

Second pass (corrected): The core claim holds. I corrected 'Dashboard routes have no outsider matrix at all': tests/api/test_dashboard_over_http.py:269-290 checks 5 routes for an outsider, and :245-266 checks 4 admin-only refusals. They are hand-written and not tied to the registered routes, so the gap is real but narrower. I tied the AUTHZ-02 example to the sees-all half, because the open-group half is an ADR ambiguity rather than a regression. Low stays.

**Proposed fix.** 1. Drive every label from OUTSIDER_VIEW: call each 'hidden' tool as an outsider and assert no team name or team skill in the structured result; call each 'own' tool and assert it names no team.
2. Add an INSIDER_VIEW keyed by tool and dashboard route for three insiders (open-group non-member, outside a private group, sees_all), with outcomes such as readable, refused-as-missing and not-writable.
3. Build the dashboard route table from the routes registered on mcp (as tests/api/test_dashboard_routes_are_documented.py already enumerates them), so a new route fails until it has a row.

**Done when.** The new INSIDER_VIEW tests fail on today's main for /api/state members[].groups (AUTHZ-03), and for share_skill without a group by a sees_all member (AUTHZ-02, if the owner takes the restrictive option). They pass once those are fixed. Adding a tool or a dashboard route without a row fails the suite.

## Push validation, dependencies and the build

The auditor assigned to push validation, hashing, paths, the install path, the container and dependencies did not run (the account's weekly limit). What is here is the main session's own, smaller pass: the dependency scan, the CI workflow, the Dockerfile's basics, and the existing test suite. A full pass on archive validation, the install staging path, the sync skill's shell steps and `self_update.py` is the last step of PLAN.md.

### PUSH-01: The jobs that hold publishing credentials run third-party actions by moving tags and an unpinned Poetry

**Confirmed.** Severity **Medium**, effort **S**. Hurts: everyone who runs the image or the package: whoever can move one of those tags can publish as the project

**Where.** .github/workflows/tests.yaml:230-261 (`publish`: `docker/setup-qemu-action@v4`, `docker/setup-buildx-action@v4`, `docker/login-action@v4`, `docker/metadata-action@v6`, `docker/build-push-action@v7`, with `packages: write`), :279-294 (`pypi`: `pypa/gh-action-pypi-publish@release/v1`, a branch, with `id-token: write`; `pipx install poetry` unpinned, though the Dockerfile pins Poetry for the same reason)

**What is wrong.** The two jobs that can publish run actions by a tag or a branch that their owners can move. `release/v1` is a branch. Whoever controls one of those refs (the maintainer, or anyone who compromises them, which has happened to popular actions) runs code with the job's `GITHUB_TOKEN` package write or its PyPI OIDC identity. The workflow has no top-level `permissions:`, so the test jobs get whatever the repository's default token permissions are. Nothing updates the pins either way (STD-07).

**How it was confirmed.** Read every `uses:` line in tests.yaml; none is pinned by commit SHA. The `permissions:` blocks appear only on the two publishing jobs.

**Proposed fix.** Pin every `uses:` by full commit SHA with the version as a comment, add `permissions: contents: read` at the top of tests.yaml, pin Poetry in the `pypi` job to the Dockerfile's version, and let Dependabot (`.github/dependabot.yml`, ecosystem `github-actions` and `pip`) propose bumps. This is GitHub's own hardening guide and OpenSSF Scorecard's 'Pinned-Dependencies' and 'Token-Permissions' checks.

**Done when.** `grep -E 'uses: [^@]+@[0-9a-f]{40}' .github/workflows/tests.yaml` matches every `uses:` line; OpenSSF Scorecard (or `zizmor`) reports no unpinned action and no default token permissions.

Related: [STD-17](industry-standards.md#std-17-images-are-unsigned-and-carry-no-sbom-the-base-image-is-unpinned-and-rebuilt-only-on-commits-and-there-is-no-security-policy).

## Checked and holding up

- Server invite code: hmac.compare_digest over sha256 digests (token_service.py:24-31). It is only a bootstrap principal, and policy.authorize lets it reach join only. A machine token cannot call join.
- Machine tokens are aist_ + token_urlsafe(32) (256 bits), stored as sha256 with a unique index, looked up by hash, and returned once. AIStackAccessToken hides the token from repr.
- Team invite codes are aistinv_ + token_urlsafe(24) (192 bits), stored as sha256. They are single use: admit's conditional UPDATE means a second user gets NotFound and the whole join rolls back. They expire after 7 days, and a cancelled code answers 401 as a bearer and 404 on the invite page.
- Transfer tickets: HS256 pinned; exp, aud and sub required; separate audiences for upload, download, dashboard link and dashboard session. The key is 32 random bytes in memory. Upload rechecks the machine is registered to its user. Download rechecks the machine exists and the revision is one of the user's own skills. Replay within 5 minutes is accepted by ADR-0010 and works as described.
- Dashboard link: the second use answers 401. The redirect takes the ticket out of the address bar, with Referrer-Policy no-referrer and no-store.
- Session cookie: HttpOnly, SameSite=Lax, Max-Age 28800, Path=/, and Secure when AISTACK_PUBLIC_URL is https.
- CSRF: a POST without X-AIStack-Request answers 400. No CORS middleware: an OPTIONS preflight from another origin answers 405 on /api/teams and /mcp. No open redirect: / always goes to /app, and sign-in always goes to /app.
- Clickjacking and CSP: /app, the signed-out page and the invite page send CSP frame-ancestors 'none', nosniff and no-store. The page builds DOM only through el() with text nodes, with no innerHTML or eval sinks, so script-src 'unsafe-inline' is not currently exploitable.
- server_base_url: AISTACK_PUBLIC_URL wins. A Host header with shell syntax ('a.example;touch${IFS}x') falls back to the bound address. A public URL with credentials is refused at startup without echoing it.
- Secrets at DEBUG: a full run through join, add_machine, push, get_skill, open_dashboard, invite_to_team and join_team (demo_seed.py plus my probes) logged 0 occurrences of aist_, aistinv_, the server invite code, or JWTs (eyJ). WIRE_LOGGERS keep mcp.server.streamable_http and friends at INFO.
- Startup errors with 8 malformed DATABASE_URL values (bad port, garbage, bad sslmode, unknown option, missing database, unknown dialect, unresolvable host, password in the query string): no password in the output. pydantic settings use hide_input_in_errors, and validate_invite_code never echoes the code.
- Log forging: every aistack logger call interpolates either loggable() values, ids, or names already validated. AIStackError sanitizes its message, and unexpected tracebacks go through bounded_failure.
- The 401 body for a rejected bearer never echoes the bearer. /health says only ok or unavailable. /mcp refuses a 200 MB body with 413 without buffering it.
- Dashboard sessions end when the user's last machine is deleted (require_a_machine), and a server restart voids every link, session and ticket.
- Sharing into a group by name refuses a non-writer with the same 404 sentence for a hidden group and a missing one: eve into backend and sam into security (v_probe 02.1/02.4), and 'hush' vs 'nope' in v_services.py
- A non-member's /api/state groups and skills leave out private groups and the open groups under them (v_probe 03.1, 03.3). dashboard_service._team_skills and sync_service._team_updates both read through visibility.team_skills
- An offboarded user's old machine token answers 401 on /mcp, and their dashboard session answers 401 (dashboard_service.require_a_machine) (v_probe 01.11, v_orphan)
- A team invite code as bearer lists only `join` (v_probe 01.4, 01.12)
- On SQLite the last-admin race is serialized by BEGIN IMMEDIATE: v_race_admin.py leaves admins_left = 1 in both leave and demote modes
- The sole-member leave refusal and the admin-only refusals answer with sentences, not crashes (v_orphan, v_probe 05.1)
- Targeted suite: tests/services/test_teams.py -k "group or admin or invite" has 26 passed and 1 skipped (the PostgreSQL-only invite race)
- My server on port 8420 is stopped, the demo server on 8000 still answers ok, and git status in /home/user/AIStack is clean
- The whole suite, 1,422 tests on SQLite and PostgreSQL 16, passed on this commit, including the archive tests that build a gzip bomb and a pax-header bomb, the path rules (device names, case and NFC/NFD twins, depth), and the push-race test at a `threading.Barrier`.
- A scan of all 84 packages in poetry.lock against PyPI's advisory data found advisories for PyJWT 2.13.0 only (STD-07); every other locked version has none listed.
- The image runs as a fixed unprivileged uid with a HEALTHCHECK and publishes only after every test job passed on that commit (`needs:`), and the PyPI job uses trusted publishing, so no upload token exists.

## Raised and dropped on the second pass

Kept here so a later session does not chase them again.

- **AUTHZ-06** Any member can claim a username nobody has taken yet by creating a team with that name; the newcomer's error then says they may already be registered. The behaviour reproduces, but it is a deliberate design decision. DESIGN.md:250 says 'usernames and team names share one namespace', team_service.py:45 says the same, test_teams.py:101 pins it, and OUTSIDER_VIEW labels create_team 'taken'. The refusal already says 'Pick a different one' first, and the add_machine clause is conditional ('if this is you'). Nothing dead-ends: the newcomer picks another name. What remains is a wording nitpick.
