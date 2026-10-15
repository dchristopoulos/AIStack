# Concurrency and reliability

The failure modes production systems usually get wrong: two people acting at once, errors under load, retries, half-finished work, restarts, limits and clocks. Each race was driven to its exact window with a `threading.Barrier` or an event, on SQLite and on PostgreSQL 16 (READ COMMITTED), and each finding names the test that fails today. The tests were written in the audit's scratch space and are described, not committed.

How far this was checked: each finding below was reproduced or traced line by line by the auditor who raised it, and **Confirmed** means exactly that. The independent second pass that tries to refute each finding ran only for the authorization and UX findings: the account's weekly limit stopped the rest. Where the main session re-checked a finding itself, its entry says so. Treat **Suspected** findings, and anything marked High or Critical without a second pass, as needing a reproduction before the fix lands; the reproduction is described in each.

| Id | Finding | Severity | Status | Effort |
|---|---|---|---|---|
| [ENT-01](#ent-01-two-admins-acting-at-once-on-postgresql-leave-a-team-with-no-admin) | Two admins acting at once on PostgreSQL leave a team with no admin | High | Confirmed | S |
| [ENT-02](#ent-02-a-member-removed-while-being-added-to-a-private-group-keeps-the-group-and-regains-it-on-rejoining) | A member removed while being added to a private group keeps the group, and regains it on rejoining | Medium | Confirmed | S |
| [ENT-03](#ent-03-local-mode-orders-the-library-log-by-wall-clock-so-a-computer-whose-clock-runs-ahead-makes-copies-diverge-and-a-rebuild-silently-replaces-a-newer-edit) | Local mode orders the Library log by wall clock, so a computer whose clock runs ahead makes copies diverge and a rebuild silently replaces a newer edit | Medium | Confirmed | M |
| [ENT-04](#ent-04-on-sqlite-every-read-waits-for-the-global-write-lock-past-5-s-auth-fails-with-a-bare-http-500-tools-fail-as-failed-unexpectedly-and-health-returns-503) | On SQLite every read waits for the global write lock; past 5 s, auth fails with a bare HTTP 500, tools fail as 'failed unexpectedly', and /health returns 503 | Medium | Confirmed | M |
| [ENT-05](#ent-05-syncs-file-listing-includes-a-nested-git-that-push-leaves-out-so-a-skill-folder-that-is-a-git-clone-never-shows-as-current-and-restore-deletes-its-git) | Sync's file listing includes a nested .git that push leaves out, so a skill folder that is a git clone never shows as current, and 'restore' deletes its .git | Medium | Confirmed | S |
| [ENT-06](#ent-06-a-local-library-rebuild-replays-every-archive-inside-one-sqlite-transaction-and-other-sessions-on-the-computer-fail-after-5-s) | A local Library rebuild replays every archive inside one SQLite transaction, and other sessions on the computer fail after 5 s | Medium | Confirmed | M |
| [ENT-07](#ent-07-on-postgresql-concurrent-deletes-and-duplicate-inserts-surface-as-500s-misleading-sentences-or-a-false-success) | On PostgreSQL, concurrent deletes and duplicate inserts surface as 500s, misleading sentences, or a false success | Low | Confirmed | M |
| [ENT-08](#ent-08-a-push-that-lands-during-remove-from-library-leaves-the-skill-hidden-from-the-library-but-enabled-and-kept-current-on-a-computer) | A push that lands during 'remove from Library' leaves the skill hidden from the Library but enabled and kept current on a computer | Low | Confirmed | S |
| [ENT-09](#ent-09-an-admin-is-told-an-invite-was-cancelled-while-the-same-invite-admits-its-holder) | An admin is told an invite was cancelled while the same invite admits its holder | Low | Confirmed | S |
| [ENT-10](#ent-10-dashboard-state-queries-once-per-team-member-and-runs-inside-the-sqlite-write-lock-about-180-ms-per-page-load-for-a-400-member-team) | Dashboard state queries once per team member and runs inside the SQLite write lock, about 180 ms per page load for a 400-member team | Low | Confirmed | S |
| [ENT-11](#ent-11-a-lost-join-response-locks-a-newcomer-out-of-their-username) | A lost join response locks a newcomer out of their username | Low | Confirmed | M |
| [ENT-12](#ent-12-body-limits-answer-in-the-wrong-place-the-mcp-sdks-4-mib-cap-preempts-syncs-own-node_modules-sentence-and-the-dashboard-buffers-whole-bodies) | Body limits answer in the wrong place: the MCP SDK's 4 MiB cap preempts sync's own node_modules sentence, and the dashboard buffers whole bodies | Low | Confirmed | S |
| [ENT-13](#ent-13-an-upload-dropped-mid-body-logs-an-error-with-a-full-traceback) | An upload dropped mid-body logs an ERROR with a full traceback | Info | Confirmed | S |

AIStack is safe under concurrency on SQLite only because every transaction takes the server-wide write lock (BEGIN IMMEDIATE). On PostgreSQL (READ COMMITTED), several check-then-write paths in team_service and skill_service can be interleaved. I drove each one to its exact window with events or barriers on a private PostgreSQL 16 and confirmed seven kinds of failure. The worst: a team can end with no admin and no way back without SQL, and a removed member can keep a private group they regain when they rejoin. Concurrent deletes also surface as 500s or misleading sentences. On SQLite the same lock becomes a throughput cliff. Every read waits for it, including bearer verification and /health. A burst of 200 concurrent syncs failed 3 calls as "sync failed unexpectedly", and a lock held past 5 s turns MCP auth into a bare HTTP 500. In local mode, events are ordered by each computer's wall clock, so a computer whose clock runs ahead makes Library copies diverge, and a rebuild then silently replaces the person's newer edit. A rebuild also replays every archive inside one SQLite transaction, which exceeded the busy timeout at 1,500 events. On the user's side question: local mode keeps the Library in a SQLite database under ~/.aistack (optionally with a GitHub log), not as plain files, so ENT-03 and ENT-06 apply to it. All tests live in &lt;scratch&gt;/enterprise/races/ and run with: cd /home/user/AIStack && PYTHONPATH=/home/user/AIStack:/home/user/AIStack/src:&lt;scratch&gt;/enterprise/races poetry run pytest -q -p no:cacheprovider -s --rootdir=&lt;scratch&gt;/enterprise/races &lt;file&gt;. The shared PostgreSQL on 5433 was down, so the fixture in races/conftest.py makes a throwaway UTF8 database per test on a private cluster in my folder. Start that cluster with: unshare --user -- /usr/lib/postgresql/16/bin/pg_ctl -D &lt;scratch&gt;/enterprise/pg/data -o "-p 8239 -k '' -c listen_addresses=127.0.0.1" start. To use another server, set ENT_PG_ADMIN. The HTTP probes ran against my own servers (SQLite on 8230, PostgreSQL on 8231), which are now stopped.

### ENT-01: Two admins acting at once on PostgreSQL leave a team with no admin

**Confirmed.** Severity **High**, effort **S**. Hurts: Every member of the team, on a PostgreSQL server. With no admin, nobody can invite, change roles, remove members, or remove skills. There is no in-product recovery and no OPERATING.md script for it.

**Where.** src/aistack/services/team_service.py:487 (_keep_an_admin), called from set_member :351, leave_team :320 and remove_member :329

**What is wrong.** _keep_an_admin counts the team's admins, and the caller then demotes or deletes, with no lock between the two. Under READ COMMITTED, two transactions both count 2 and both write. Three cases reach zero admins: two admins demoting each other; two admins leaving at once (with no other member left, this is an empty team whose name stays taken forever); and admin A removing B while B demotes A. A's `_as_admin` check is also stale by then. SQLite is safe only because BEGIN IMMEDIATE serializes the two transactions.

**How it was confirmed.** Test &lt;scratch&gt;/enterprise/races/test_last_admin.py: team acme has admins ann and bob plus member cid. On PostgreSQL, `_keep_an_admin` is wrapped so each transaction waits at a threading.Barrier(2) right after its count. On SQLite both threads start together. Output: 'postgresql outcomes: ['ok', 'ok'] admins left: 0' in all three cases. SQLite gives one refusal (Conflict or ValidationError) and 'admins left: 1'. Fix prototype &lt;scratch&gt;/enterprise/races/test_last_admin_fixed.py moves the barrier to just before the count and locks the team row FOR UPDATE: 3 passed, 'admins left: 1' in each case, and the loser gets Conflict.

**Proposed fix.** Add a `_lock_team(session, team)` helper in team_service: `session.execute(select(Team.team_id).where(Team.team_id == team.team_id).with_for_update())`. Call it in _keep_an_admin before the count, or better, at the start of every mutation that changes admins or members (set_member, leave_team, remove_member). Re-read the caller's TeamMember after the lock so a just-demoted admin cannot finish an admin action. SQLAlchemy omits FOR UPDATE on SQLite, so SQLite behaviour is unchanged. Pin it with tests/db/test_last_admin_race_postgres.py, modeled on test_push_race_postgres.py, with the barrier just before the count; it fails without the lock.

**Done when.** The new PostgreSQL test for all three interleavings fails on main and passes with the fix: exactly one admin remains, and the losing call returns the 'would leave team ... with no admin' Conflict sentence.

Related: [AUTHZ-04](security.md#authz-04-the-team-keeps-an-admin-check-counts-first-and-writes-later-without-a-lock-on-postgresql-two-simultaneous-leaves-or-demotions-leave-a-team-with-no-admin), [AUTHZ-V01](security.md#authz-v01-offboarding-a-teams-only-admin-as-docsoperatingmd-says-leaves-the-team-with-an-admin-nobody-can-reach-and-no-way-to-name-a-new-one), [AUTO-13](automation.md#auto-13-the-documented-offboarding-leaves-a-team-whose-only-admin-left-with-no-admin-anyone-can-reach), [DB-05](schema.md#db-05-teams-can-be-left-with-no-admin-or-no-members-on-postgresql-the-last-admin-check-is-a-racy-count), [DB-07](schema.md#db-07-offboarding-a-teams-only-admin-leaves-the-team-permanently-unmanaged-and-no-operator-script-exists-to-repair-it), [PH-05](plot-holes.md#ph-05-taking-a-teams-only-admin-off-the-server-leaves-the-team-with-nobody-who-can-manage-it-and-operating-has-no-fix).

### ENT-02: A member removed while being added to a private group keeps the group, and regains it on rejoining

**Confirmed.** Severity **Medium**, effort **S**. Hurts: A team admin who removed someone, on PostgreSQL. If the person is invited back later, even only to the team, they can again see a private group's skills that nobody added them to.

**Where.** src/aistack/services/team_service.py:392-406 (set_group_member) and :499-504 (_drop_member)

**What is wrong.** set_group_member checks membership with `_member` and then inserts a GroupMember row. A concurrent remove_member or leave_team runs `_drop_member`, which deletes group rows first and the TeamMember row second, and never sees the uncommitted insert. group_member has no foreign key to team_member, so the row survives for a non-member. visibility.group_access then counts the person as a member of that private group as soon as any later invite readmits them.

**How it was confirmed.** Test &lt;scratch&gt;/enterprise/races/test_team_races.py::test_removed_member_does_not_keep_a_private_group. Bob (admin) runs set_group_member(secret, cid), held right after `_member` returns. Ann (admin) runs remove_member(cid) and commits. Bob's transaction then continues and commits. Output: 'add-to-group vs remove: ('ok', 'ok')', 'group_member rows left for a non-member: 1', and after a new invite and join_team: 'groups cid sees after rejoining: ['secret']'.

**Proposed fix.** Use the same `_lock_team` as ENT-01 at the start of set_group_member, create_group (which adds the creator), remove_member and leave_team, and re-read `_member` after the lock. In `_drop_member`, delete the TeamMember row before the GroupMember and GroupUnsubscribed rows, so the deletes run after any concurrent insert commits. Optional and longer: give group_member a team_id with a composite foreign key to team_member(team_id, user_id) ON DELETE CASCADE, as an expand-then-contract migration under ADR-0024.

**Done when.** test_removed_member_does_not_keep_a_private_group passes on PostgreSQL: no GroupMember row remains for the removed user, and team_service.groups returns [] for them after they rejoin.

### ENT-03: Local mode orders the Library log by wall clock, so a computer whose clock runs ahead makes copies diverge and a rebuild silently replaces a newer edit

**Confirmed.** Severity **Medium**, effort **M**. Hurts: Someone with two computers sharing a GitHub Library when one clock runs ahead, for example a VM, WSL2 after sleep, or a dual-boot machine. Their newer edit loses on every other copy, and later on the computer that made it.

**Where.** src/aistack/services/library_log.py:82-83 (new_event stamps datetime.now), :163-180 (catch_up applies arrivals on top), :182 (rebuild replays in sort_key order)

**What is wrong.** The sort key is the creating computer's wall-clock time. Computer B applies A's event on top, then the person makes a change on B. B's event can be stamped earlier than A's if A's clock is ahead by more than the time between the two. B's copy applied the events as (X, Y), but every other copy, and any copy rebuilt from the log, replays (Y, X). ADR-0025 promises that every computer ends with the same revisions in the same order; here they end up with different 'latest' revisions. Once B's copy is rebuilt (deleted, or an earlier-stamped event arrives), sync on B sees its folder matching an older revision and reports an update. The sync skill applies updates without asking, so the newer edit on disk is replaced. It stays only as an old revision in history.

**How it was confirmed.** Test &lt;scratch&gt;/enterprise/races/test_clock_skew.py uses real local_identity.local_machine, skill_service.push with library_log.record, and unpublished, mark_published and catch_up, with a Python list as the repository. library_log.datetime is patched so the laptop's clock is 60 s ahead. Sequence: the laptop pushes X; the desktop pulls X and then pushes Y; the laptop pulls. Output: 'B rebuilt on pull: False A rebuilt on pull: True', 'laptop (A) latest: (2, '7fd127519407') desktop (B) latest: (2, 'e9feea2aa042')', 'fresh copy latest: (2, '7fd127519407')'. A second test rebuilds the desktop's copy and syncs a folder holding Y: 'desktop sync after rebuild: update [('wizard', 1, 2)]'.

**Proposed fix.** Make the event time a hybrid logical clock. Stamp `at = max(now, at of applied_through(session) + 1 µs)`, so nothing this copy creates sorts before an event it has already applied. That means `new_event` takes the session; callers are local tools, the dashboard's local-mode routes and local_identity. The file format and sort key are unchanged, so older releases still replay these events (ADR-0024). Keep the one-day future cap. Record the rule as an amendment to ADR-0025, whose ordering paragraph says 'by time'.

**Done when.** Both tests in test_clock_skew.py pass: laptop, desktop and a fresh copy all report Y as the latest revision, and the rebuilt desktop's sync reports no update.

Related: [DB-11](schema.md#db-11-library_event-grows-on-no-op-changes-unchanged-pushes-store-the-full-archive-again-and-repeat-installs-log-again), [ENT-06](#ent-06-a-local-library-rebuild-replays-every-archive-inside-one-sqlite-transaction-and-other-sessions-on-the-computer-fail-after-5-s).

### ENT-04: On SQLite every read waits for the global write lock; past 5 s, auth fails with a bare HTTP 500, tools fail as 'failed unexpectedly', and /health returns 503

**Confirmed.** Severity **Medium**, effort **M**. Hurts: The operator of the default SQLite deployment, and every agent during a start-of-day burst. An orchestrator that restarts unhealthy containers also signs every dashboard out (the signing key is in memory) and voids every transfer URL.

**Where.** src/aistack/db/engine.py:64-71 (BEGIN IMMEDIATE for every transaction) with :11 (5 s busy timeout); src/aistack/mcp/auth/aistack_token_verifier.py:86-93; src/aistack/mcp/routes/health.py:33-35; src/aistack/mcp/mcp_error_handler.py:31-34

**What is wrong.** Read-only sessions also start with BEGIN IMMEDIATE: bearer verification on every MCP request, /health, list_skills and /api/state. So an MCP call takes the write lock twice, and readers queue behind writers. SQLite's busy handler polls rather than queueing in order, so under a burst some callers starve past 5 s. The failures surface in three ways. The verifier's OperationalError escapes FastMCP's auth and becomes a plain 'Internal Server Error' (500); uvicorn logs that traceback unescaped, including the SQL with the token's sha256, against the AGENTS.md logging rule. Tools return 'X failed unexpectedly.', which gives the agent no hint to retry. /health returns 503.

**How it was confirmed.** Own server: SQLite on port 8230. &lt;scratch&gt;/enterprise/load.py fires concurrent raw JSON-RPC sync calls from 50 machines of one user. Bursts of 50 and 100 all succeeded (p50 1.4 s and 2.3 s). A burst of 200 gave 197 ok and 3 'sync failed unexpectedly.'; the server log shows sqlite3.OperationalError 'database is locked'; p50 was 5.6 s. &lt;scratch&gt;/enterprise/lockhold.py holds BEGIN IMMEDIATE for 7 s from a separate sqlite3 connection. Result: MCP list_skills got HTTP 500 'Internal Server Error' after 5.0 s, /health got 503 after 5.0 s, and the log shows 'ERROR [uvicorn.error.run_asgi] Exception in ASGI application' through aistack_token_verifier.py _find_machine. &lt;scratch&gt;/enterprise/healthburst.py: /health took 3.8 s during a 200-sync burst, against the Dockerfile HEALTHCHECK's 4 s timeout. A plain deferred BEGIN read in WAL mode, run while a write lock was held, returned in 0.5 ms; the same read with BEGIN IMMEDIATE failed 'database is locked' after 5.0 s. The PostgreSQL server (8231) handled bursts of 50, 100, 200 and 400 with no failures.

**Proposed fix.** (1) Let read-only sessions begin DEFERRED. `_begin_immediate` emits a plain BEGIN when the connection carries an execution option such as `aistack_read_only=True`, which the token verifier's two lookups, `_ping_database`, list_skills and the /api/state read use. WAL readers then never wait for the writer. This needs a new ADR amending ADR-0014. (2) Add a `Busy` AIStackError for 'database is locked', and for PostgreSQL's QueuePool TimeoutError, SerializationFailure and DeadlockDetected. Convert it in handle_mcp_errors, and in handle_route_errors with status 503 (add it to _STATUS_CODES), with the sentence 'The server is busy; make the same call again in a few seconds.' (3) Optionally, put an in-process FIFO lock around SQLite write transactions, so waiters queue in order and the timeout is explicit.

**Done when.** While a writer holds the lock, lockhold.py shows list_skills answering normally (authentication does not wait) and /health returning 200. A write tool blocked past the timeout returns the Busy sentence, not 'failed unexpectedly' or a bare 500. A test in tests/db/test_sqlite_write_lock.py asserts that a read session completes while BEGIN IMMEDIATE is held.

Related: [DB-01](schema.md#db-01-dashboard-list_skills-and-sync-count-every-revision-and-file-on-the-whole-server-for-each-request-under-sqlites-write-lock), [SEC-04](security.md#sec-04-unauthenticated-requests-take-sqlites-write-lock-token-checks-health-and-the-invite-page-all-run-begin-immediate), [STD-06](industry-standards.md#std-06-health-checks-bearer-checks-and-the-invite-page-take-sqlites-write-lock-so-one-slow-write-turns-them-into-503-and-500).

### ENT-05: Sync's file listing includes a nested .git that push leaves out, so a skill folder that is a git clone never shows as current, and 'restore' deletes its .git

**Confirmed.** Severity **Medium**, effort **S**. Hurts: Anyone whose skill folder is a git clone, which is common for skills installed from GitHub: every sync asks about it. Answering 'restore' destroys the clone's history and any unpushed commits. Windows users with a dot-folder inside a skill (.github, .claude-plugin) hit the same endless question.

**Where.** src/aistack/bundled/skills/sync-aistack/SKILL.md:43-45 (find) and :53-55 (PowerShell); src/aistack/services/sync_service.py:220-234 (_canonical_hash); compare push_skill's `tar --exclude .git` and local_skills.observed, which drops .git

**What is wrong.** In find, `! -path './.*'` excludes only dot entries at the top level, so ./wizard/.git/... is listed and hashed. Push uploads without .git, so the canonical hash never matches and sync reports the skill as 'unknown' with options restore, push and skip. 'push' stores nothing new (unchanged), so the question comes back on every sync. 'restore' replaces the whole folder, removing .git. The PowerShell filter goes the other way: it drops every nested dot-folder, such as .github, which tar includes, so on Windows the same mismatch happens for those skills.

**How it was confirmed.** Test &lt;scratch&gt;/enterprise/races/test_sync_git_folder.py pushes skill_archive() (what tar --exclude .git sends), then syncs local_digests() plus .git/HEAD and .git/config. Output: 'up_to_date: 0 ask: [('wizard', 'unknown', ['restore', 'push', 'skip'])]'. I also ran the bundled find command and the push tar on a folder at &lt;scratch&gt;/enterprise/findtest: find printed ./wizard/.git/HEAD; `tar -tzf` listed .github/workflows/ci.yml but no .git.

**Proposed fix.** On the server, make `sync_service._canonical_hash` skip any path with a `.git` segment. Push and local mode already leave .git out; share one helper (for example in skill_archive) so the rule exists in one place. Fix the bundled skill as well: add `! -path '*/.git/*'` to find, and make the PowerShell filter exclude only `\.git\` segments, not every dot-folder. refresh_sync_skill then rolls the new skill out to machines. Add the case to tests/services/test_sync_service.py.

**Done when.** test_sync_git_folder passes (up_to_date 1, ask empty). The bundled PowerShell command, run on the findtest layout, lists .github/workflows/ci.yml and not .git/HEAD.

### ENT-06: A local Library rebuild replays every archive inside one SQLite transaction, and other sessions on the computer fail after 5 s

**Confirmed.** Severity **Medium**, effort **M**. Hurts: Someone with two computers on a GitHub Library and a long history, who runs two agent sessions or the localhost dashboard. The rebuild time grows with the whole log, since it is never compacted.

**Where.** src/aistack/services/library_log.py:182-199 (rebuild) and :163-180 (catch_up), via apply → src/aistack/services/skill_service.py:63 (validated_skill(read_archive(...))), inside the transaction opened at src/aistack/services/library_sharing.py:43-48

**What is wrong.** Replay runs each push event through skill_service.push, which base64-decodes, decompresses and validates the archive inside the one transaction catch_up opens. AGENTS.md says nothing slow may run inside a SQLite transaction, archive parsing named explicitly. A rebuild replays the entire log, so its lock time grows with the history. A rebuild happens whenever an event arrives that sorts earlier than what this copy already holds, which happens more often with the clock skew in ENT-03.

**How it was confirmed.** Test &lt;scratch&gt;/enterprise/races/test_rebuild_time.py records 1,500 push events (60 skills of about 24 KB) on one copy, then rebuilds a second copy in a thread while another session factory on the same file runs a read. Output: '1501 events, 1 MB of log', 'second session: OperationalError (sqlite3.OperationalError) database is locked after 5.0 s', 'rebuild held one transaction for 7.9 s'.

**Proposed fix.** (a) Decode and validate every event's archive before opening the transaction: have library_log.catch_up and rebuild receive pre-validated pushes (a `skill_service.store_validated(session, ..., uploaded)` that push also uses after its own pre-transaction validation). (b) Rebuild into a fresh database file next to the live one and swap it in by rename, so no live transaction is held for the replay. (c) Later, periodic snapshots to bound replay length; that needs an ADR.

**Done when.** In test_rebuild_time.py, the second session completes in under 1 s while the 1,500-event rebuild runs, and a spy shows read_archive is never called while the catch_up or rebuild transaction is open.

Related: [DB-11](schema.md#db-11-library_event-grows-on-no-op-changes-unchanged-pushes-store-the-full-archive-again-and-repeat-installs-log-again), [ENT-03](#ent-03-local-mode-orders-the-library-log-by-wall-clock-so-a-computer-whose-clock-runs-ahead-makes-copies-diverge-and-a-rebuild-silently-replaces-a-newer-edit).

### ENT-07: On PostgreSQL, concurrent deletes and duplicate inserts surface as 500s, misleading sentences, or a false success

**Confirmed.** Severity **Low**, effort **M**. Hurts: Team admins and members on PostgreSQL, whose agents or browsers get 'failed unexpectedly' or a wrong explanation, and a member told a share succeeded when the team no longer has the skill.

**Where.** src/aistack/services/team_service.py:356 (set_member), :417 (move_skill), :420-433 (remove_skill), :311-314 (set_subscribed), :176-190 (admit); src/aistack/services/skill_service.py:211-212 (take_from_team), :491 (`except IntegrityError` in _store_revision), :412 (set_enabled)

**What is wrong.** Each of these reads and then writes without locking the row it depends on. Several `except IntegrityError` blocks also assume a unique-key race, so foreign-key violations are misread as one. Observed outcomes: (1) set_member while another admin removes the member: StaleDataError, a 500. (2) move_skill while an admin removes the skill: StaleDataError. (3) get_skill(team) while an admin removes the skill: AttributeError on None.skill_version_id. (4) share with new content while the skill is removed: the FK violation is caught as a revision race, and the member is told 'Several pushes to 'wizard' landed at the same moment'. (5) share with unchanged content while the skill is removed: reports ok and unchanged for a team skill that no longer exists. (6) An admin's remove_skill that waits behind a share: ForeignKeyViolation, a 500. (7) Two unsubscribes of one group, from two tabs: UniqueViolation, a 500. (8) One person joining with two invites to the same team at once: a uq_team_member violation, a 500. (9) The same code submitted twice: the second answer is 'That is not a team invite code that works' although the person is now in the team.

**How it was confirmed.** PostgreSQL tests in &lt;scratch&gt;/enterprise/races/. `_in_window` holds the first transaction at a named function until the second commits; an after_cursor_execute barrier is used for the delete case. test_team_races.py output: "set_member vs remove: ('UNEXPECTED StaleDataError: UPDATE statement on table 'team_member' expected to update 1 row(s); 0 were matched.', 'ok')"; "double unsubscribe: ['ok', 'UNEXPECTED IntegrityError: (psycopg.errors.UniqueViolation) ... uq_group_...']"; "join with two codes: ['ok', 'UNEXPECTED IntegrityError: ... uq_team_m...']"; "join double-click: ['ok', 'NotFound: That is not a team invite code that works...']". test_skill_races.py output: "share (new content) vs admin remove: ('Conflict: Several pushes to 'wizard' landed at the same moment...', 'ok')"; "share (same content) vs admin remove: ('ok', 'ok')"; "get_skill(team) vs admin remove: ('UNEXPECTED AttributeError: 'NoneType' object has no attribute 'skill_version_id'', 'ok')"; "move vs admin remove: ('UNEXPECTED StaleDataError ... table 'skill' ...', 'ok')". test_remove_waits_for_share.py output: "('ok', 'UNEXPECTED IntegrityError: (psycopg.errors.ForeignKeyViolation) update or delete on table \"skill\" violates foreign ke...')". handle_mcp_errors and handle_route_errors mask each UNEXPECTED case as 'X failed unexpectedly.' (a 500 on routes).

**Proposed fix.** Lock the team skill row (`with_for_update()`) when share, take_from_team, move_skill and remove_skill read it, so the operations serialize, then re-read after the lock. In `_store_revision`, `_find_or_create_skill` and `set_enabled`, catch only unique violations (sqlstate 23505 on psycopg, 'UNIQUE constraint failed' on sqlite3); turn a foreign-key violation into NotFound("Team 'x' no longer has a skill named 'y'."). Use the ENT-01 `_lock_team` for set_member. Make the GroupUnsubscribed insert in set_subscribed a savepoint that ignores a duplicate, as set_group_member already does. In admit, insert TeamMember in a savepoint; when the conditional update matches nothing but the caller is now a member, return the team name, so join is idempotent.

**Done when.** The cases above in test_team_races.py, test_skill_races.py and test_remove_waits_for_share.py pass on PostgreSQL: no outcome starts with UNEXPECTED, no 'landed at the same moment' sentence for a removed skill, and share no longer reports success for a deleted team skill.

### ENT-08: A push that lands during 'remove from Library' leaves the skill hidden from the Library but enabled and kept current on a computer

**Confirmed.** Severity **Low**, effort **S**. Hurts: Someone who removes a skill in the dashboard while an agent on another computer is backing it up. The skill disappears from the Library page and list_skills but stays installed, and the dashboard no longer offers a way to remove it.

**Where.** src/aistack/services/skill_service.py:77 (`skill.archived = False` is a no-op when the push read False) and :300-314 (remove_from_my_skills)

**What is wrong.** Push reads the skill with archived False. remove_from_my_skills then commits archived True and disables every placement. Push next re-enables its own placement, but its `archived = False` emits no UPDATE, because the ORM sees no change from the value it loaded. The final state (archived True with an enabled placement) is one neither serial order produces.

**How it was confirmed.** Test &lt;scratch&gt;/enterprise/races/test_skill_races.py::test_push_during_remove_ends_in_a_state_neither_order_gives (PostgreSQL). The push is held right after _store_revision while the remove commits. Output: "push vs remove: ('ok', 'ok') archived: True enabled here: True list_skills: [] sync up_to_date: 1 ask: []".

**Proposed fix.** In push, write `update(Skill).where(Skill.skill_id == skill.skill_id).values(archived=False)` explicitly. It waits on the remove's row lock and then applies, which gives the 'remove, then push' state. Alternatively, lock the skill row FOR UPDATE in both push and remove_from_my_skills.

**Done when.** The test ends in a state one of the serial orders produces: archived False with the placement enabled, or archived True with every placement disabled.

### ENT-09: An admin is told an invite was cancelled while the same invite admits its holder

**Confirmed.** Severity **Low**, effort **S**. Hurts: A team admin cancelling an invite that went to the wrong person, on PostgreSQL. They believe the person was kept out.

**Where.** src/aistack/services/team_service.py:226-230 (cancel_invite)

**What is wrong.** cancel_invite checks `used_on is None` and then sets cancelled_on with an unconditional update by primary key. admit's conditional update can commit in between. The cancel still succeeds, leaving the invite both used and cancelled. Status reads ACCEPTED, and the person is in the team.

**How it was confirmed.** &lt;scratch&gt;/enterprise/races/test_team_races.py::test_cancelling_an_invite_someone_is_using holds the cancel at its utc_now() call (after the check) while eve's join_team commits. Output: "cancel vs use: ('ok', 'ok') used_on set: True cancelled_on set: True members: ['ann', 'eve']".

**Proposed fix.** Make the cancel conditional, as admit already is: `update(Invite).where(Invite.invite_id == id, Invite.used_on.is_(None), Invite.cancelled_on.is_(None)).values(cancelled_on=utc_now())`. If rowcount is 0, re-read and raise the existing 'already used' ValidationError (or succeed quietly if it was already cancelled).

**Done when.** In the test, exactly one of cancel and use succeeds; when the join wins, the cancel answers 'That invite was already used...'.

Related: [AUTHZ-01](security.md#authz-01-removing-demoting-or-offboarding-an-inviter-leaves-their-invite-links-working-so-the-person-can-rejoin-the-team-or-create-a-new-account-on-the-server), [DB-06](schema.md#db-06-a-team-invite-outlives-its-makers-right-to-invite-offboarding-by-deleting-machines-removal-from-the-team-and-revoking-can_invite-all-leave-it-working), [PH-02](plot-holes.md#ph-02-invites-outlive-the-person-who-made-them-so-removed-members-and-people-taken-off-the-server-keep-letting-new-accounts-in), [SEC-06](security.md#sec-06-on-postgresql-an-admins-cancel-can-report-success-while-the-person-it-was-meant-to-stop-joins), [SEC-07](security.md#sec-07-a-used-team-invite-code-still-authenticates-as-a-bearer-so-used-and-unknown-codes-answer-differently).

### ENT-10: Dashboard state queries once per team member and runs inside the SQLite write lock, about 180 ms per page load for a 400-member team

**Confirmed.** Severity **Low**, effort **S**. Hurts: Large teams on SQLite. Every dashboard load holds the server-wide lock, and the page reloads state after every action. Admins also receive every invite ever made, with no cap.

**Where.** src/aistack/services/team_service.py:273-281 (`_groups_of` per member in members()), called per team from src/aistack/services/dashboard_service.py:37-73; group_access recomputed per team (team_service.groups :290, visibility.team_skills :138); team_service.invites :196-211 (unbounded)

**What is wrong.** members() issues one query per member, and state() calls group_access and members() again for each team. On SQLite all of that runs inside one BEGIN IMMEDIATE transaction, so concurrent requests wait. invites() returns every invite the team ever had, accepted and expired ones included.

**How it was confirmed.** Test &lt;scratch&gt;/enterprise/races/test_big_team_state.py builds 400 members, 30 groups and 300 shared skills, and counts statements with a before_cursor_execute listener. Output: 'state() for admin: 424 statements, 181 ms inside one transaction, 0.5 MB'; 'state() for user0: 422 statements, 108 ms'. list_skills for comparison: 6 statements, 16 ms. dashboard.html run() calls load(), which re-fetches /api/state after every action.

**Proposed fix.** Fetch every member's groups for a team in one query: GroupMember joined to TeamGroup where team_id matches, grouped in Python. Compute visibility.group_access once in state() and pass it to groups and team_skills. Return pending invites plus those from the last 30 days. With ENT-04's deferred read, the state read no longer takes the write lock.

**Done when.** For the 400-member fixture, state() issues fewer than 40 statements, independent of member count, and runs in under 30 ms.

Related: [DB-02](schema.md#db-02-dashboard-state-issues-one-query-per-team-member-plus-a-dozen-per-team-n1), [IMP-07](improvements.md#imp-07-apistate-queries-per-team-and-per-member-inside-sqlites-write-lock-concurrent-refreshes-delay-everyones-sync-and-return-500).

### ENT-11: A lost join response locks a newcomer out of their username

**Confirmed.** Severity **Low**, effort **M**. Hurts: A newcomer whose `join` answer is lost to a proxy timeout, a dropped connection or an agent crash. With a team invite, the invite is also used up.

**Where.** src/aistack/services/onboarding_service.py:54-68 (join)

**What is wrong.** join commits the user, machine and token hash, and the response is the only copy of the token. A retry with the same username gets 'Username 'x' is already taken... add the machine from a computer that is already registered', but the person has no registered computer. A retry with a team invite answers 'That is not a team invite code that works', because invited_to refuses the now-used invite before the username check. Only the operator script in docs/OPERATING.md ('Register a machine for them') recovers.

**How it was confirmed.** Traced: join flushes User and the personal Team inside `try` and raises Conflict on IntegrityError. The first, committed join holds both names, so any second call with that username raises the Conflict. For a team invite, onboarding_service.join:52 calls team_service.invited_to before the user insert, and invited_to (team_service.py:146) refuses a used invite with NotFound. I did not run this one: the code path is deterministic.

**Proposed fix.** Give join an optional idempotency key: an agent-generated request_id that the setup instructions pass, stored hashed on the machine row (a new nullable column, a compatible migration under ADR-0024). A retry with the same username and request_id within 10 minutes rotates and returns a fresh token for that machine instead of the Conflict. As a cheaper first step, change the Conflict sentence to name the operator recovery when the account's only machine has never authenticated.

**Done when.** A test calls join twice with the same username and request_id: both calls return a working token, and the database holds one user and one machine.

Related: [AUTO-11](automation.md#auto-11-running-setup-in-the-second-agent-on-an-already-connected-computer-registers-the-same-computer-twice-and-the-two-then-undo-each-other), [AUTO-21](automation.md#auto-21-joining-drops-the-name-the-person-gave-and-asks-questions-local-mode-answers-itself), [PH-09](plot-holes.md#ph-09-setup-step-1-stops-at-already-connected-for-any-aistack-connection-a-pasted-team-invite-is-dropped-and-another-server-or-local-mode-dead-ends), [PH-10](plot-holes.md#ph-10-a-setup-that-stops-after-join-locks-the-newcomer-out-the-re-run-refuses-the-used-invite-then-the-username), [UX-11](ux.md#ux-11-joining-asks-for-the-name-you-want-to-go-by-but-join-needs-a-lowercase-username-and-has-no-place-for-the-full-name), [UX-12](ux.md#ux-12-an-existing-user-who-pastes-the-invite-pages-setup-sentence-may-never-be-put-in-the-team-setup-has-no-branch-for-a-team-code).

### ENT-12: Body limits answer in the wrong place: the MCP SDK's 4 MiB cap preempts sync's own node_modules sentence, and the dashboard buffers whole bodies

**Confirmed.** Severity **Low**, effort **S**. Hurts: Someone with a node_modules tree inside a skill: their agent gets a plain HTTP 413 instead of the hint to leave the folder out. The operator, whose dashboard routes read any size of body from a signed-in browser before checking the 16 KB cap.

**Where.** MCP SDK RequestBodyLimitMiddleware (4 MiB, mcp/server/transport_security.py) versus src/aistack/services/sync_service.py:32-33 and :206-211; src/aistack/api/dashboard.py:328-331 (_json_body)

**What is wrong.** sync_service accepts up to 20,000 files and explains the node_modules case past that, but the SDK refuses a JSON-RPC body over 4 MiB first, with plain text. A modest node_modules tree crosses 4 MiB, so the agent never sees the sentence written for it. Separately, `_json_body` calls `await request.body()` before comparing against _MAX_BODY_BYTES; the transfer route's `_bounded_body` already shows the streaming pattern.

**How it was confirmed.** &lt;scratch&gt;/enterprise/syncsize.py against my SQLite server. 12,000 files (1.3 MiB): accepted. 25,000 files (2.8 MiB): 'sync received 25001 files, and the limit is 20000. If a .git or node_modules folder...'. 40,000 files (4.4 MiB): 'HTTP 413: Request body too large'. &lt;scratch&gt;/enterprise/bigbody.py: bodies of 10, 50 and 200 MB to /mcp were refused with 413 in 0.3 s or less (that cap works). The dashboard path is traced at dashboard.py:329.

**Proposed fix.** In the bundled sync skill, say that an HTTP 413 'Request body too large' from sync means a skill folder holds too many files (node_modules, .git) and should be left out. After ENT-05's .git fix, also exclude node_modules from the listing and from push's tar consistently. Make `_json_body` stream with a running count and refuse once past 16 KB, like `_bounded_body`.

**Done when.** A sync listing of 40,000 node_modules files produces an agent-readable instruction, and a 1 MB POST to /api/teams returns 400 'larger than 16384 bytes' without the body being buffered (assert on bytes received).

### ENT-13: An upload dropped mid-body logs an ERROR with a full traceback

**Confirmed.** Severity **Info**, effort **S**. Hurts: The operator, who sees a false server fault for every flaky-network upload. Nothing is stored, and a retry with the same ticket works.

**Where.** src/aistack/mcp/routes/transfer.py:90-116 (_bounded_body) and src/aistack/mcp/routes/route_error_handler.py:49-52

**What is wrong.** starlette's ClientDisconnect is not handled in `_bounded_body`, so the generic `except Exception` logs it at ERROR as 'upload_skill failed' with a traceback. For the client this is expected behaviour, not a server fault.

**How it was confirmed.** &lt;scratch&gt;/enterprise/partial.py declares the archive's Content-Length, sends a third of it, and hangs up. The server log shows "ERROR [aistack.mcp.routes.transfer.wrapper] upload_skill failed. Error: 'Traceback ... ClientDisconnect'". The same ticket used afterwards stored revision 1, and once more returned unchanged true.

**Proposed fix.** Catch `starlette.requests.ClientDisconnect` in `_bounded_body` and log 'Upload dropped by the client before it finished' at INFO, with no traceback and no response body.

**Done when.** A test that disconnects mid-upload finds no ERROR record from aistack.mcp.routes.transfer and one INFO line.

## Checked and holding up

- Revision numbers: _store_revision retries 3 times on a unique-key collision and then raises a clean Conflict. The repo's tests/db/test_push_race_postgres.py (three concurrent shares get revisions 2-4; two first pushes of one name make one skill) passes against my private PostgreSQL.
- First-user admin race (ADR-0008): tests/db/test_admin_race_postgres.py, 8 joiners in both modes, passes on PostgreSQL. Exactly one admin.
- One invite used by two people at once lets exactly one in: tests/services/test_teams.py::test_two_people_using_one_invite_at_once_let_exactly_one_in passes on PostgreSQL.
- create_team with the same name at once on PostgreSQL: one ok, one clean Conflict sentence (savepoint + IntegrityError). join with the same username at once: one ok, one clean Conflict.
- record_sync with two first syncs of one folder at once on PostgreSQL: exactly one reports first_sync. set_enabled with two first placements at once: no error (savepoint plus re-read).
- On SQLite, every team and skill race above is serialized by BEGIN IMMEDIATE: each last-admin race gives one refusal and leaves 1 admin.
- PostgreSQL server: bursts of 50, 100, 200 and 400 concurrent syncs, and 20 and 100 concurrent push-plus-upload: zero failures and no QueuePool timeout (pool 5+10, 30 s timeout).
- SQLite server: bursts of 50 and 100 concurrent syncs, and 20 and 100 concurrent pushes: zero failures. The cliff starts near 200 (ENT-04).
- Transfer upload retried with the same ticket is idempotent (unchanged true, same revision). An upload dropped mid-body stores nothing.
- get_skill whose download never happens: the next sync reports install again (desired enabled, local absent), so nothing is stranded.
- /mcp refuses bodies over 4 MiB (SDK RequestBodyLimitMiddleware): 10, 50 and 200 MB bodies got 413 in 0.3 s or less. The upload route streams with a 1 MB cap and a 30 s read deadline.
- Dashboard double-click: run() in dashboard.html marks the control aria-busy and ignores a second click while the first request is in flight.
- Used dashboard sign-in links are pruned on every use and bounded by the links used within 5 minutes. The in-memory key and the single-instance requirement are documented in docs/OPERATING.md, so replicas are not reported.
- Migrations run in one transaction under pg_advisory_xact_lock on PostgreSQL, so two processes starting at once do not both migrate.
- GitHub Library publish: events stay unpublished after a failed push and go out on the next catch_up or write. A crash between git push and mark_published re-writes identical files, so there is nothing to commit and they are then marked published.
- Time handling: stored timestamps go through as_utc before arithmetic, and invite expiry uses the same `<=` comparison in is_open_invite and invited_to. Everything is UTC, so DST does not apply.
