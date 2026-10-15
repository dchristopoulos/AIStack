# Database schema

Constraints, indexes, SQLite and PostgreSQL parity, migrations, and upgrades between releases (ADR-0016, ADR-0024). Measurements come from databases seeded through the real services, up to 3,000 users and about a gigabyte on SQLite.

How far this was checked: each finding below was reproduced or traced line by line by whoever raised it, and **Confirmed** means exactly that. The independent second pass that tries to refute each finding was done only for the authorization and UX findings; there was no time for the rest. Where a finding was re-checked separately, its entry says so. Treat **Suspected** findings, and anything marked High or Critical without a second pass, as needing a reproduction before the fix lands; the reproduction is described in each.

| Id | Finding | Severity | Status | Effort |
|---|---|---|---|---|
| [DB-01](#db-01-dashboard-list_skills-and-sync-count-every-revision-and-file-on-the-whole-server-for-each-request-under-sqlites-write-lock) | Dashboard, list_skills and sync count every revision and file on the whole server for each request, under SQLite's write lock | High | Confirmed | M |
| [DB-02](#db-02-dashboard-state-issues-one-query-per-team-member-plus-a-dozen-per-team-n1) | Dashboard state issues one query per team member, plus a dozen per team (N+1) | Medium | Confirmed | M |
| [DB-03](#db-03-the-models-and-migrations-agree-test-cannot-see-check-constraints-server-defaults-or-partial-index-predicates) | The 'models and migrations agree' test cannot see CHECK constraints, server defaults, or partial-index predicates | Medium | Confirmed | S |
| [DB-04](#db-04-widening-a-stored-enum-a-new-harness-os-or-role-breaks-older-releases-that-adr-0024-lets-keep-running) | Widening a stored enum (a new harness, OS or role) breaks older releases that ADR-0024 lets keep running | Medium | Confirmed | M |
| [DB-05](#db-05-teams-can-be-left-with-no-admin-or-no-members-on-postgresql-the-last-admin-check-is-a-racy-count) | Teams can be left with no admin, or no members, on PostgreSQL: the last-admin check is a racy count | Medium | Confirmed | S |
| [DB-06](#db-06-a-team-invite-outlives-its-makers-right-to-invite-offboarding-by-deleting-machines-removal-from-the-team-and-revoking-can_invite-all-leave-it-working) | A team invite outlives its maker's right to invite: offboarding by deleting machines, removal from the team and revoking can_invite all leave it working | Medium | Confirmed | S |
| [DB-07](#db-07-offboarding-a-teams-only-admin-leaves-the-team-permanently-unmanaged-and-no-operator-script-exists-to-repair-it) | Offboarding a team's only admin leaves the team permanently unmanaged, and no operator script exists to repair it | Medium | Confirmed | S |
| [DB-08](#db-08-compatibility-is-checked-only-when-a-process-starts-a-process-already-running-when-another-upgrades-the-database-is-never-told) | Compatibility is checked only when a process starts; a process already running when another upgrades the database is never told | Low | Confirmed | M |
| [DB-09](#db-09-0008-and-0009-are-additive-but-not-compatible-an-older-writer-silently-breaks-invariants-the-newer-release-depends-on) | 0008 and 0009 are 'additive' but not compatible: an older writer silently breaks invariants the newer release depends on | Low | Confirmed | S |
| [DB-10](#db-10-missing-indexes-on-the-columns-the-services-look-up-by-and-no-constraint-for-one-library-per-user) | Missing indexes on the columns the services look up by, and no constraint for 'one Library per user' | Low | Confirmed | S |
| [DB-11](#db-11-library_event-grows-on-no-op-changes-unchanged-pushes-store-the-full-archive-again-and-repeat-installs-log-again) | library_event grows on no-op changes: unchanged pushes store the full archive again, and repeat installs log again | Low | Confirmed | S |
| [DB-12](#db-12-no-naming-convention-on-basemetadata-constraint-names-differ-by-dialect-and-by-migration) | No naming convention on Base.metadata: constraint names differ by dialect and by migration | Low | Confirmed | M |
| [DB-13](#db-13-group-unsubscriptions-survive-leaving-a-team-so-a-returning-member-silently-misses-updates) | Group unsubscriptions survive leaving a team, so a returning member silently misses updates | Low | Confirmed | S |
| [DB-14](#db-14-text-order-by-differs-between-sqlite-and-postgresql-depending-on-the-database-collation) | Text ORDER BY differs between SQLite and PostgreSQL depending on the database collation | Info | Confirmed | S |
| [DB-15](#db-15-as_utc-returns-a-non-utc-time-on-postgresql-when-the-databases-timezone-is-not-utc) | as_utc returns a non-UTC time on PostgreSQL when the database's TimeZone is not UTC | Info | Confirmed | S |

The models and migrations match on both databases, and older code still runs after an upgrade. I checked both: the existing test passes on SQLite and PostgreSQL 16, a pg_dump/sqlite_master diff of a migrated database against a create_all one shows only column order, constraint names and one server default, and code from the 0007-, 0008- and 0009-era commits runs every service step against a database migrated to 0010 on both dialects. The weak points are speed and safety under load. The dashboard, list_skills and sync count revisions and files across the whole server, not just the caller's skills, so their cost grows with everyone's data. On SQLite every transaction is BEGIN IMMEDIATE, so that work holds the write lock: on a 1 GB server a dashboard refresh holds it for about 2 s, and 8 concurrent refreshes failed 5 times with "database is locked". The dashboard also issues one query per team member (1,167 statements for 5 teams of 220). The model-vs-migration test cannot see CHECK constraints, server defaults or partial-index predicates. ADR-0024's "only adds" rule misses three things: a widened enum CHECK, a new table or column that older writers silently skip, and processes that were already running when the upgrade happened. A few invariants are enforced only in Python and fail on PostgreSQL under concurrency (two admins leaving at once leaves a team with nobody in it). Several rows outlive their meaning: a departed person's invites still work, unsubscriptions survive leaving a team, and no-op local-mode events are stored forever.

### DB-01: Dashboard, list_skills and sync count every revision and file on the whole server for each request, under SQLite's write lock

**Confirmed.** Severity **High**, effort **M**. Hurts: Everyone on a growing server: every agent session syncs and every dashboard focus refreshes; on the default SQLite deployment pushes, joins and other users' syncs queue behind these reads and can fail with 'database is locked'.

**Where.** src/aistack/services/dashboard_service.py:150-168 (_newest: GROUP BY over all skill_version and all skill_file), used at :171 and :193; src/aistack/services/skill_service.py:138-141 (list_skills newest); src/aistack/services/sync_service.py:316-319 (_team_updates newest); the transaction is opened in src/aistack/api/dashboard.py:356-360 (_in_transaction), which on SQLite is BEGIN IMMEDIATE (src/aistack/db/engine.py:64-71)

**What is wrong.** The 'latest revision' and 'file count' subqueries aggregate whole tables (GROUP BY skill_version.skill_id over every skill on the server, and GROUP BY skill_file.skill_version_id over every file of every revision) and are only then joined to the caller's 200 skills. Neither database pushes the join key into the aggregate. So the cost of one user's dashboard, listing or sync grows with the total data on the server. That data keeps growing: every push, share and take copies whole revisions. On SQLite this all runs inside a BEGIN IMMEDIATE transaction, so for its whole duration it holds the only write lock, against AGENTS.md's 'nothing slow may happen inside one'.

**How it was confirmed.** Seeded through the real services with &lt;scratch&gt;/schema/seed.py: user 'focus' with 200 skills, 5 teams and 300 other users, then bulk-loaded 3,000 users x 50 skills x 3 files with bulk_sqlite.py (SQLite, 1.07 GB) and SQL generate_series (PostgreSQL 16, database 'big'). EXPLAIN (explain_state.py) shows 'Seq Scan / Index Only Scan on skill_file (468,706 rows) -&gt; HashAggregate/GroupAggregate' and the same on skill_version for a user with 200 skills, on both dialects (SQLite: 'SCAN skill_file USING COVERING INDEX ... MATERIALIZE'). stmt_times.py on the 1 GB SQLite file: sync spends 627 ms in the _team_updates query, list_skills 1,231 ms, dashboard state 1,507 ms in SQL (two statements at about 750 ms each). With the same server holding only 6,400 skills these take 36-57, 26-32 and 95-130 ms. On PostgreSQL, the today-shaped _my_skills query takes 161 ms; rewritten with a LATERAL latest revision and a correlated per-version file count it takes 2.6 ms, with identical rows. lock_contention.py: with 8 concurrent dashboard refreshes on the 1 GB SQLite file, 5 refreshes failed with 'sqlite3.OperationalError: database is locked' (output in lock8.txt), and a one-row write behind 1-5 refreshes waited 1.5-4.7 s against the 5 s busy timeout.

**Proposed fix.** Scope every 'newest' to the skills being returned. In dashboard_service._newest, skill_service.list_skills and sync_service._team_updates, take the latest revision per selected skill with a correlated subquery or LATERAL `ORDER BY revision DESC LIMIT 1`, which uses uq_skill_version_skill_revision, or with max(revision) filtered by `skill_id IN (<the selected skill ids>)`. Count files with a correlated scalar subquery on skill_file.skill_version_id, which uses uq_skill_file_version_path. Put the shared helper in services/ so the three callers stop drifting. This needs no schema change and no ADR. Separately, running read-only routes (GET /api/state, list_skills) as BEGIN DEFERRED on SQLite would stop reads from taking the write lock; that changes ADR-0014 and needs a new ADR.

**Done when.** A test under tests/services captures the statements issued by dashboard_service.state, skill_service.list_skills and sync_service.sync for a seeded user, runs EXPLAIN QUERY PLAN on each (SQLite) and EXPLAIN (PostgreSQL), and fails on any full scan of skill_file or skill_version, covering-index scans included. It fails today. Re-running stmt_times.py on the 1 GB file shows each call under 50 ms, and lock_contention.py with 8 refreshes reports no 'database is locked'.

Related: [ENT-04](concurrency-and-reliability.md#ent-04-on-sqlite-every-read-waits-for-the-global-write-lock-past-5-s-auth-fails-with-a-bare-http-500-tools-fail-as-failed-unexpectedly-and-health-returns-503), [SEC-04](security.md#sec-04-unauthenticated-requests-take-sqlites-write-lock-token-checks-health-and-the-invite-page-all-run-begin-immediate), [STD-06](industry-standards.md#std-06-health-checks-bearer-checks-and-the-invite-page-take-sqlites-write-lock-so-one-slow-write-turns-them-into-503-and-500).

### DB-02: Dashboard state issues one query per team member, plus a dozen per team (N+1)

**Confirmed.** Severity **Medium**, effort **M**. Hurts: Members of larger teams: every dashboard refresh, and every other request on SQLite, which waits for the write lock this transaction holds. On a managed PostgreSQL (Neon or Supabase, as OPERATING.md suggests) each statement is a network round trip.

**Where.** src/aistack/services/dashboard_service.py:37-71 (state loops over teams), src/aistack/services/team_service.py:263-279 (members: _groups_of per member at :274), :282-296 (groups recomputes group_access per team), :196-211 (invites re-resolves membership); also skill_service.export_library at src/aistack/services/skill_service.py:383-395

**What is wrong.** For each team, state() makes one query for the caller's TeamMember row, then calls members(), groups() and invites(). Each of those resolves visibility.membership again; groups() recomputes group_access (3 queries) per team; and members() runs _groups_of once for every member. The statement count is about 7 + T x (M + 12). export_library has the same shape: about 5 statements per skill, and it builds every archive inside the transaction.

**How it was confirmed.** count_queries.py (SQLAlchemy before_cursor_execute counting) on the seeded databases: 5 teams x 20 members gives 167 statements (105 of them the _groups_of SELECT), 95-130 ms on SQLite and 166 statements, about 290 ms on PostgreSQL over local TCP. After grow_teams.py (5 teams x 220 members) it gives 1,167 statements (1,105 _groups_of), 334 ms, all inside one BEGIN IMMEDIATE on SQLite. export_library for 200 skills: 1,002 statements, 424 ms in one write-locked transaction.

**Proposed fix.** Assemble the team part of state() in dashboard_service with a fixed number of queries. (1) Fetch every membership row of the caller's non-personal teams once. (2) Compute group_access once and pass it into team_service.members and team_service.groups through new keyword arguments (or add batch variants such as members_of_teams). (3) Fetch every (team_id, user_id, path, private) group membership for those teams in one query and group them in Python. (4) Fetch the invites of every team where the caller is admin or may invite in one query. All of this stays in services and still goes through visibility for the access decision. For export_library, read the latest versions and their files in two queries and build the archives after the transaction closes.

**Done when.** A test seeds 2 teams x 3 members and 5 teams x 40 members, then asserts that dashboard_service.state issues the same number of statements for both (at most about 15); count_queries.py on big.db reports at most about 15 statements, down from 1,167.

Related: [ENT-10](concurrency-and-reliability.md#ent-10-dashboard-state-queries-once-per-team-member-and-runs-inside-the-sqlite-write-lock-about-180-ms-per-page-load-for-a-400-member-team), [IMP-07](improvements.md#imp-07-apistate-queries-per-team-and-per-member-inside-sqlites-write-lock-concurrent-refreshes-delay-everyones-sync-and-return-500).

### DB-03: The 'models and migrations agree' test cannot see CHECK constraints, server defaults, or partial-index predicates

**Confirmed.** Severity **Medium**, effort **S**. Hurts: The operator and every user, the first time a migration gets an enum CHECK or the single-admin index wrong: the suite stays green and the database enforces something other than what the models say.

**Where.** tests/db/test_schema.py:119-126 (test_a_fresh_database_gets_exactly_the_schema_the_models_describe uses alembic compare_metadata with default options); src/aistack/db/models/team.py:762 vs src/aistack/db/migrations/versions/0004_can_invite.py:14

**What is wrong.** AGENTS.md and ADR-0016 rely on 'a test fails when models and migrations disagree'. alembic's compare_metadata does not compare CHECK constraints, and with default options it does not compare server defaults or the WHERE of a partial index. Today the enum CHECKs (ck_machine_os, ck_team_kind, ck_team_member_role, ck_machine_skill_harness, ck_machine_harness_harness) and ix_user_single_admin's predicate (ADR-0008) are guarded by nothing but review. One disagreement already exists and goes unseen: migrated databases have team_member.can_invite DEFAULT false, while the model and create_all have no default. The next foreseeable migration, widening the harness CHECK in two tables, could widen only one and pass.

**How it was confirmed.** compare_blind.py on my PostgreSQL 16 (port 8141): migrate a fresh database, alter it, and call the same compare_metadata the test calls. Widening ck_machine_skill_harness only: not detected. Dropping ck_team_kind: not detected. Adding a server default to machine_skill.enabled: not detected. Recreating ix_user_single_admin without its WHERE: not detected. Dropping ON DELETE CASCADE from skill_file's FK: detected. diff_schema.py dumps create_all vs migrate_schema with pg_dump -s and sqlite_master; the only real difference is 'can_invite boolean DEFAULT false' (pg_mig.sql vs pg_ca.sql).

**Proposed fix.** In tests/db/test_schema.py, add a second assertion. Build a reference database with Base.metadata.create_all on the same dialect, then for every table compare inspector.get_check_constraints() (normalized sqltext), inspector.get_indexes() including dialect_options (postgresql_where / sqlite_where), and the column server defaults against the migrated database. Alternatively compare normalized pg_dump -s / sqlite_master SQL with names and column order stripped. Also pass compare_server_default=True to MigrationContext.configure. Decide on can_invite: add server_default=false() to the model, matching what shipped.

**Done when.** Running compare_blind.py's four undetected alterations against the new test makes each one fail it, and the suite stays green on SQLite and on PostgreSQL via TEST_DATABASE_URL.

### DB-04: Widening a stored enum (a new harness, OS or role) breaks older releases that ADR-0024 lets keep running

**Confirmed.** Severity **Medium**, effort **M**. Hurts: Someone with two computers on one shared database in local mode, or a server mid rolling deploy: the computer that has not updated gets a broken dashboard as soon as the other uses the new value.

**Where.** src/aistack/db/models/harness.py:11-28 (docstring prescribes 'a migration that widens the CHECK constraints'), harness_type with validate_strings and Enum mapping; reads that fail: src/aistack/services/dashboard_service.py:132-137 (_machines) and :201-208 (_my_skills placements); ADR-0024 'only adds' rule in AGENTS.md (Migrations)

**What is wrong.** Harness, OperatingSystem, TeamKind and TeamRole are non-native SQLAlchemy Enums. Reading a value the release does not know raises LookupError. The project's own guidance treats a new harness as a migration that widens two CHECKs, and ADR-0024 classifies additive changes as compatible. So the next harness migration will be marked older_releases_compatible = True, the older release will start on it (schema.py:181-205), and any of its queries that select harness for rows written by the newer release will crash.

**How it was confirmed.** widened_enum.py on PostgreSQL. A fresh database is migrated with the current code, a user pushes a skill, then the database is altered as a 'compatible 0011' would alter it: both harness CHECKs gain 'codex', alembic_version becomes '0011', and one machine_harness and one machine_skill row use 'codex'. migrate_schema logs 'Running on schema 0011 ... still supports this release'. Then: dashboard_service.state raises "LookupError: 'codex' is not among the defined enum values. Enum name: ck_machine_skill_harness"; sync, get_skill and remove_from_my_skills for claude_code still work.

**Proposed fix.** Write a new ADR, or amend ADR-0024 through one, saying that adding a value to a stored value set is breaking unless every older release reads unknown values safely. Also make the reads tolerant now, before the next harness ships. In dashboard_service._machines and _my_skills (and any query selecting harness or os), filter `.where(MachineSkill.harness.in_(list(Harness)))`. Or switch harness_type to a TypeDecorator over String that returns None for values this release does not know, with callers skipping None. Add the rule to AGENTS.md beside the expand-and-contract rule.

**Done when.** A test inserts a machine_skill and a machine_harness row with an unknown harness value (after replacing the CHECK, on both dialects) and dashboard_service.state still returns the known placements without raising.

### DB-05: Teams can be left with no admin, or no members, on PostgreSQL: the last-admin check is a racy count

**Confirmed.** Severity **Medium**, effort **S**. Hurts: A team on PostgreSQL whose two admins step down or leave at the same moment. Afterwards nobody can invite, manage groups or remove skills, the team name stays taken, and no operator script exists to repair it.

**Where.** src/aistack/services/team_service.py:483-494 (_keep_an_admin counts admins with a plain SELECT), used by leave_team :318-323, remove_member :326-334, set_member :337-361

**What is wrong.** 'A shared team always has an admin' is enforced only by counting ADMIN rows and then updating or deleting a different row. On PostgreSQL READ COMMITTED, two transactions each count two admins, each change a different row (no row conflict), and both commit. SQLite is safe only because BEGIN IMMEDIATE serializes every transaction.

**How it was confirmed.** admin_race.py: two admins (ann, ben) of team acme call team_service.leave_team in two threads. A threading.Barrier placed right after _keep_an_admin returns makes both pass the check before either commits. On PostgreSQL: no errors, and acme ends with zero member rows (the team row remains). On SQLite the second transaction cannot begin while the first holds the lock, so it never reaches the check and nothing changes, which confirms the problem is PostgreSQL-only.

**Proposed fix.** In _keep_an_admin, lock before counting: `session.scalars(select(TeamMember.team_member_id).where(TeamMember.team_id == team.team_id, TeamMember.role == TeamRole.ADMIN).with_for_update()).all()` and use len() of the result. On PostgreSQL the second caller waits and then sees one admin; SQLite ignores FOR UPDATE and is already serialized. Add tests/db/test_team_admin_race_postgres.py modelled on test_admin_race_postgres.py, using a Barrier at the same point.

**Done when.** The new PostgreSQL test (two concurrent leave_team calls and two concurrent cross-demotions) fails today and passes after the change, with exactly one caller getting the 'would leave team ... with no admin' Conflict.

Related: [AUTHZ-04](security.md#authz-04-the-team-keeps-an-admin-check-counts-first-and-writes-later-without-a-lock-on-postgresql-two-simultaneous-leaves-or-demotions-leave-a-team-with-no-admin), [AUTHZ-V01](security.md#authz-v01-offboarding-a-teams-only-admin-as-docsoperatingmd-says-leaves-the-team-with-an-admin-nobody-can-reach-and-no-way-to-name-a-new-one), [AUTO-13](automation.md#auto-13-the-documented-offboarding-leaves-a-team-whose-only-admin-left-with-no-admin-anyone-can-reach), [DB-07](#db-07-offboarding-a-teams-only-admin-leaves-the-team-permanently-unmanaged-and-no-operator-script-exists-to-repair-it), [ENT-01](concurrency-and-reliability.md#ent-01-two-admins-acting-at-once-on-postgresql-leave-a-team-with-no-admin), [PH-05](plot-holes.md#ph-05-taking-a-teams-only-admin-off-the-server-leaves-the-team-with-nobody-who-can-manage-it-and-operating-has-no-fix).

### DB-06: A team invite outlives its maker's right to invite: offboarding by deleting machines, removal from the team and revoking can_invite all leave it working

**Confirmed.** Severity **Medium**, effort **S**. Hurts: Team admins and the operator offboarding someone. A departed person who kept an invite link can make a fresh account and be back in the team, seeing its skills, for up to 7 days.

**Where.** src/aistack/services/team_service.py:121-147 (invited_to / is_open_invite check only the invite's own status), :167-191 (admit), :497-504 (_drop_member does not touch invites), :337-361 (set_member can_invite=False does not either); docs/OPERATING.md 'Someone left: take them off the server' (deletes machines and rotates only the server's invite code)

**What is wrong.** invite.created_by is never consulted when an invite is used. Nothing in the documented offboarding procedure, remove_member, or revoking can_invite cancels the pending invites that person made. Because a team invite code also creates an account (ADR-0019), whoever holds it, the departed maker included, can join the server and the team without the server's invite code.

**How it was confirmed.** offboarding.py (SQLite): eve, acme's admin, makes an invite; the operator's DELETE FROM machine script from OPERATING.md removes her laptop; onboarding_service.join(..., team_invite=&lt;eve's code&gt;) creates 'eve2' as a member of acme. invite_outlives.py: bob gets can_invite, makes a code, the admin revokes can_invite and removes bob, eve's invite list still shows ('bob', 'PENDING'), and a stranger joins acme with bob's code.

**Proposed fix.** In team_service.admit (reached from both join_team and join), refuse an invite whose created_by is no longer a member of the team with role ADMIN or can_invite, or has no machine left. Answer with the same _NOT_AN_INVITE sentence, so it reads like any dead code. Also cancel the member's pending invites in _drop_member and when set_member removes ADMIN or can_invite (set cancelled_on where used_on and cancelled_on are null). Add a line to the OPERATING.md offboarding script that cancels pending invites with created_by = that user.

**Done when.** Tests in tests/services: after remove_member, after set_member(can_invite=False), and after the member's machines are deleted, using that member's pending code raises NotFound with the standard sentence, and the team's invite list shows it as CANCELLED.

Related: [AUTHZ-01](security.md#authz-01-removing-demoting-or-offboarding-an-inviter-leaves-their-invite-links-working-so-the-person-can-rejoin-the-team-or-create-a-new-account-on-the-server), [ENT-09](concurrency-and-reliability.md#ent-09-an-admin-is-told-an-invite-was-cancelled-while-the-same-invite-admits-its-holder), [PH-02](plot-holes.md#ph-02-invites-outlive-the-person-who-made-them-so-removed-members-and-people-taken-off-the-server-keep-letting-new-accounts-in), [SEC-06](security.md#sec-06-on-postgresql-an-admins-cancel-can-report-success-while-the-person-it-was-meant-to-stop-joins), [SEC-07](security.md#sec-07-a-used-team-invite-code-still-authenticates-as-a-bearer-so-used-and-unknown-codes-answer-differently).

### DB-07: Offboarding a team's only admin leaves the team permanently unmanaged, and no operator script exists to repair it

**Confirmed.** Severity **Medium**, effort **S**. Hurts: Members of a team whose sole admin left the company: nobody can invite, change roles, manage groups or remove skills, and the departed admin still appears as ADMIN.

**Where.** docs/OPERATING.md 'Someone left: take them off the server' and 'Admin operations' (no role script); src/aistack/services/team_service.py:483-494 (_keep_an_admin counts the departed admin), :584-590 (_as_admin)

**What is wrong.** The schema has no notion of a departed user. The documented offboarding deletes machines and keeps the account, its team_member rows and its ADMIN role. Every admin action then needs that unreachable admin, and OPERATING.md offers no script to promote someone else.

**How it was confirmed.** offboarding.py: after the OPERATING.md machine-delete script removes eve, acme's only admin, maria calling set_member(role='ADMIN') gets 'Only an admin of team acme can do that'. members() still lists ('eve', 'ADMIN'). Checked every admin operation in OPERATING.md: none changes a team role.

**Proposed fix.** Add an OPERATING.md script, run through build_engine and team_service, that makes a named member the admin of a named team. Add a query to the offboarding section that lists teams where the leaving user is the only admin, to run before deleting their machines. Optionally have dashboard_service mark members with no machine as 'left the server' so a team can see why nobody answers.

**Done when.** Following the updated OPERATING.md offboarding steps against offboarding.py's database leaves acme with maria as ADMIN, and the script was run against a real database before committing, as AGENTS.md requires.

Related: [AUTHZ-04](security.md#authz-04-the-team-keeps-an-admin-check-counts-first-and-writes-later-without-a-lock-on-postgresql-two-simultaneous-leaves-or-demotions-leave-a-team-with-no-admin), [AUTHZ-V01](security.md#authz-v01-offboarding-a-teams-only-admin-as-docsoperatingmd-says-leaves-the-team-with-an-admin-nobody-can-reach-and-no-way-to-name-a-new-one), [AUTO-13](automation.md#auto-13-the-documented-offboarding-leaves-a-team-whose-only-admin-left-with-no-admin-anyone-can-reach), [DB-05](#db-05-teams-can-be-left-with-no-admin-or-no-members-on-postgresql-the-last-admin-check-is-a-racy-count), [ENT-01](concurrency-and-reliability.md#ent-01-two-admins-acting-at-once-on-postgresql-leave-a-team-with-no-admin), [PH-05](plot-holes.md#ph-05-taking-a-teams-only-admin-off-the-server-leaves-the-team-with-nobody-who-can-manage-it-and-operating-has-no-fix).

### DB-08: Compatibility is checked only when a process starts; a process already running when another upgrades the database is never told

**Confirmed.** Severity **Low**, effort **M**. Hurts: Someone with two agents on one computer in local mode (Claude Code and Codex start separate processes, and self_update installs a newer release for the next start), and a server during a rolling deploy.

**Where.** src/aistack/bootstrap/context/application_context.py:67 and :103-111 (the only migrate_schema / NewerSchema checks); src/aistack/bootstrap/self_update.py:1-7, 41-60; src/aistack/services/library_log.py:180-196 (rebuild deletes only the tables this release knows)

**What is wrong.** ADR-0024 promises that a release meeting a schema it cannot use refuses and changes nothing. In practice the check runs once, at process start. Local-mode processes live as long as an agent session, and the self-update means a second session can start a newer release that migrates the same ~/.aistack database while the first keeps running old code. A later breaking (contract) migration then lands under a live process that still reads and writes the old shape. An additive one leaves that process writing without whatever the new schema relies on. For example, rebuild() empties only the tables this release knows: a newer table with a foreign key to skill or machine makes the old process's rebuild fail, and one without leaves orphans.

**How it was confirmed.** Traced: migrate_schema is called only from build_application_context and build_local_context, at startup, and no tool, route or library_before_read re-reads alembic_version. self_update.check_and_upgrade replaces the installed tool in the background and logs 'takes over at the next start', so an old and a new process can share one database. Not run end to end: no breaking migration exists after 0006 to demonstrate with.

**Proposed fix.** Make the check per transaction and cheap. In local mode, before each tool call (library_before_read, and the start of each write tool), read alembic_version, and if it is not this release's head, re-run schema._runs_on_a_newer_schema and set _local_refusal on NewerSchema, so the agent gets the ADR-0024 sentence instead of a crash. On a server, document in OPERATING.md that a breaking release requires stopping every replica first. Record the decision in a short ADR amending ADR-0024.

**Done when.** A test starts local mode, then bumps alembic_version and schema_compatibility.oldest_compatible_revision to an unknown '9999' from a second connection; the next tool call answers with the 'Run uv tool upgrade aistack-mcp' sentence instead of a database error.

### DB-09: 0008 and 0009 are 'additive' but not compatible: an older writer silently breaks invariants the newer release depends on

**Confirmed.** Severity **Low**, effort **S**. Hurts: Someone with two computers, or two agent sessions, on one database running different releases: sync warns them about a conflict that does not exist, and in a log-shared Library a change made by the older process is never logged.

**Where.** src/aistack/db/migrations/versions/0009_machine_skill_revision.py:12 and 0008_library_event.py:11 (older_releases_compatible = True); src/aistack/services/sync_service.py:178-181 (edited_from from machine_skill.revision); git ed3e04f^ skill_service.set_enabled (pre-0009 code never sets revision)

**What is wrong.** ADR-0024's test for compatibility is about structure only: a table, a nullable column or an index. 0009 adds machine_skill.revision, which the newer release trusts as 'the revision this folder was last installed or pushed at', but the 0008-era set_enabled updates a row without touching it. So after an older process pushes revision 2 from a folder, the newer sync reports edited_from=1 &lt; latest=2, and the agent tells the user that pushing would replace another computer's change. 0008 adds library_event, which ADR-0025 requires every local change to write in the same transaction. A 0007-era process writes none, so its changes never reach the log and a rebuild drops them. That has no effect today, since no release with 0007 shipped, but the rule as written will mark the next such change compatible.

**How it was confirmed.** stale_revision.py (SQLite): the current code joins and pushes revision 1; code extracted from commit 9d01f87 (head 0008, which runs on the 0010 database via the ADR-0024 path) pushes revision 2 from the same machine; the current sync with an edited copy reports ask [('wizard', 'unknown', 'edited_from', 1, 'latest', 2)]. The 0008 case was traced: before 9d01f87 the local tools have no library_log.record call. exercise.py confirmed that 0007-, 0008- and 0009-era code otherwise run every service step on the 0010 database on both dialects.

**Proposed fix.** Amend ADR-0024 through a new ADR, and the AGENTS.md Migrations bullet: a migration is compatible only if (1) its shape is additive, (2) no newer code treats a value older releases do not maintain as authoritative, and (3) it adds no table or column that must be written in the same transaction as an older release's writes. Otherwise mark it False and do the expand-and-contract dance. Add the three questions to the migration template (src/aistack/db/migrations/script.py.mako) as a comment above older_releases_compatible. For 0009 specifically, sync can treat a revision older than the newest revision this machine itself pushed (skill_version.pushed_by plus the machine's push events) as unknown rather than as another computer's change.

**Done when.** script.py.mako and AGENTS.md carry the three-question rule; a rerun of stale_revision.py after the sync change reports edited_from as null (unknown) or 2, not 1.

### DB-10: Missing indexes on the columns the services look up by, and no constraint for 'one Library per user'

**Confirmed.** Severity **Low**, effort **S**. Hurts: The operator of a larger server: every sync, push, listing and visibility check scans team / team_member / group_member, and every 'remove from Library' scans machine_skill server-wide.

**Where.** src/aistack/db/models/team.py:739 (team.created_by), :752 (team_member.user_id), :803 (group_member.user_id), :825 (group_unsubscribed.user_id); src/aistack/db/models/machine_skill.py:508 (skill_id); src/aistack/db/models/skill.py:596-602 (group_id, source_skill_id); src/aistack/db/models/invite.py:358 (team_id); queries at src/aistack/services/visibility.py:36-47, 92-100, 142-145, 156-162 and skill_service.py:328-332

**What is wrong.** Each unique constraint covers its columns only as the leading prefix. (team_id, user_id) cannot serve 'WHERE user_id = ?', and the same goes for group_member and group_unsubscribed. team.created_by, machine_skill.skill_id, skill.source_skill_id, skill.group_id and invite.team_id have no index at all, and PostgreSQL does not index foreign keys automatically. personal_team() relies on exactly one PERSONAL team per created_by, but nothing in the schema enforces it, and .one() raises if it ever breaks.

**How it was confirmed.** EXPLAIN on PostgreSQL ('seed' and 'big') and EXPLAIN QUERY PLAN on SQLite (seed.db): personal_team gives 'Seq Scan on team ... Rows Removed by Filter: 3400' / 'SCAN team'; membership and group_access give 'Seq Scan on team_member' / 'SCAN team_member USING COVERING INDEX'; group_member and group_unsubscribed by user scan the same way; remove_from_my_skills' UPDATE gives 'Seq Scan on machine_skill ... Rows Removed by Filter: 6298'; the invite list gives 'Seq Scan on invite'. On 'big', deleting one team skill spends 29.7 ms in the fk_skill_source_skill_id_skill SET NULL trigger and 2.1 ms in the machine_skill FK check, out of 32 ms total.

**Proposed fix.** Add migration 0011 (older_releases_compatible = True, indexes only) with matching Index entries in the models in the same commit: a partial unique index ux_team_personal_owner on team(created_by) WHERE kind = 'PERSONAL', written as an expression for both dialects like ix_user_single_admin; ix_team_member_user_id; ix_group_member_user_id; ix_group_unsubscribed_user_id; ix_machine_skill_skill_id; ix_skill_source_skill_id; ix_skill_group_id; and ix_invite_team_id_created_on on invite(team_id, created_on). Before creating the unique index, check for a user with two personal teams and fail with a clear message.

**Done when.** The same EXPLAIN commands show index scans for each lookup on both dialects; inserting a second PERSONAL team for one user raises IntegrityError; test_schema passes on SQLite and PostgreSQL.

### DB-11: library_event grows on no-op changes: unchanged pushes store the full archive again, and repeat installs log again

**Confirmed.** Severity **Low**, effort **S**. Hurts: Local-mode users with a GitHub Library: every no-op is a database row, a file, a commit and a push in their repository forever (ADR-0025: nothing is ever removed), and every rebuild replays them.

**Where.** src/aistack/mcp/tools/local.py:223-228 (push_skill records library_log.pushed even when pushed.unchanged), :160-166 (get_skill records SKILL_PLACED even when nothing changed); src/aistack/services/library_log.py:176-196 (published bodies are never read again)

**What is wrong.** sync already avoids logging every run ('logging every sync would grow the log by one file per session'), but push_skill and get_skill log every call. An unchanged push writes a SKILL_PUSHED event that carries the whole base64 archive, and installing an already-installed revision writes a SKILL_PLACED event. Once published to the repository, a body is never read from the database again (rebuild and unpublished read only published = false), yet the table keeps it.

**How it was confirmed.** drive_unchanged.py over stdio against a copy of the local2 Library (my folder: local/): 5 push_skill calls of an unchanged wizard (4 of them returned unchanged: true) and 5 get_skill calls of the installed revision took the event counts from skill_pushed 2 -&gt; 7 (951 -&gt; 3,451 bytes of body) and skill_placed 2 -&gt; 7.

**Proposed fix.** In mcp/tools/local.py, record SKILL_PUSHED only when not pushed.unchanged. When unchanged but the push enabled the skill in a folder that was not enabled, record a SKILL_PLACED instead. In get_skill, record SKILL_PLACED only when skill_service reports that the decision, the archived flag or the revision changed (return that fact from set_enabled). tests/mcp/test_library_log.py's random replay must still pass.

**Done when.** Re-running drive_unchanged.py adds 0 events after the first push, and test_library_log's replay test still passes.

Related: [ENT-03](concurrency-and-reliability.md#ent-03-local-mode-orders-the-library-log-by-wall-clock-so-a-computer-whose-clock-runs-ahead-makes-copies-diverge-and-a-rebuild-silently-replaces-a-newer-edit), [ENT-06](concurrency-and-reliability.md#ent-06-a-local-library-rebuild-replays-every-archive-inside-one-sqlite-transaction-and-other-sessions-on-the-computer-fail-after-5-s).

### DB-12: No naming convention on Base.metadata: constraint names differ by dialect and by migration

**Confirmed.** Severity **Low**, effort **M**. Hurts: Whoever writes the next migration that alters a constraint: each one has to special-case names per dialect, as 0002 already had to for skill_name_key.

**Where.** src/aistack/db/models/base.py:4-10 (no MetaData(naming_convention=...)); src/aistack/db/migrations/versions/0002_teams.py:131-141

**What is wrong.** Foreign keys and single-column uniques are unnamed in the models. PostgreSQL names them itself (user_username_key, team_name_key, machine_token_hash_key, invite_code_hash_key, skill_pushed_by_fkey, machine_skill_skill_id_fkey, ...). SQLite leaves them unnamed (sqlite_autoindex_*). The skill foreign keys added by 0002 are named fk_skill_* on a migrated PostgreSQL database but skill_*_fkey on a create_all one. To drop or alter any of them a migration has to know each dialect's name, or rebuild with a temporary convention.

**How it was confirmed.** diff_schema.py: pg_dump -s of create_all vs migrate_schema on PostgreSQL (pg_ca.sql vs pg_mig.sql) shows fk_skill_team_id_team vs skill_team_id_fkey, and so on; sqlite_migrated.sql shows the unnamed UNIQUE and FOREIGN KEY clauses.

**Proposed fix.** Give Base a MetaData(naming_convention={'ix': 'ix_%(table_name)s_%(column_0_name)s', 'uq': 'uq_%(table_name)s_%(column_0_name)s', 'ck': 'ck_%(table_name)s_%(constraint_name)s', 'fk': 'fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s', 'pk': 'pk_%(table_name)s'}), checking that the existing explicit names (uq_*, ck_*) are kept. Add a migration that renames the existing constraints to it: on PostgreSQL ALTER TABLE ... RENAME CONSTRAINT, on SQLite batch_alter_table with that naming_convention. Names only, so older_releases_compatible = True.

**Done when.** pg_dump -s of create_all and of migrate_schema show identical constraint names, and a test asserts inspector constraint names equal on SQLite and PostgreSQL.

**Resolution (step 18a).** The convention spells out PostgreSQL's own names (`<table>_<column>_fkey`, `<table>_<column>_key`, `<table>_pkey`) rather than the `fk_`/`uq_` names proposed above, so on PostgreSQL only the three foreign keys 0002 named need renaming and nothing else moves. On SQLite, migration 0011 rebuilds `skill`, `user`, `machine`, `team` and `invite` with the names, and leaves the large tables (`skill_version`, `skill_file`, `machine_skill` and the rest) with the unnamed constraints the baseline gave them, because rebuilding them copies every file for a name SQLite never uses: it cannot alter a constraint in place, and a batch migration that drops one passes the convention (AGENTS.md, Migrations). So the test compares every name on PostgreSQL, and on SQLite every name the database stored.

### DB-13: Group unsubscriptions survive leaving a team, so a returning member silently misses updates

**Confirmed.** Severity **Low**, effort **S**. Hurts: A member who leaves and later rejoins a team: sync never offers updates from groups they had muted before, without saying so.

**Where.** src/aistack/services/team_service.py:497-504 (_drop_member deletes group_member and team_member rows but not group_unsubscribed)

**What is wrong.** group_unsubscribed rows reference the group and the user, not the membership, and leaving the team does not remove them. A rejoined member starts with the old mutes, and the rows also linger for people who never come back.

**How it was confirmed.** invite_outlives.py (last part): a member unsubscribes from acme/backend, calls leave_team, and joins again with a new invite; groups() returns [('backend', False)].

**Proposed fix.** In team_service._drop_member, also delete GroupUnsubscribed rows where user_id = the leaving user and group_id is in that team's groups (the same in_team subquery already used for GroupMember).

**Done when.** A service test (unsubscribe, leave, rejoin) shows subscribed True for the group, and no group_unsubscribed row for that user remains after leave_team.

Related: [IMP-02](improvements.md#imp-02-unsubscribing-from-a-group-stops-syncs-update-offers-but-not-the-dashboards).

### DB-14: Text ORDER BY differs between SQLite and PostgreSQL depending on the database collation

**Confirmed.** Severity **Info**, effort **S**. Hurts: Anyone comparing a SQLite server with a PostgreSQL one (including CI, whose postgres image defaults to en_US.utf8): skills, groups, members and file lists come back in a different order.

**Where.** src/aistack/services/team_service.py:255, :271, :293; dashboard_service.py:179, :200; skill_service.py:154, :187, :515; sync_service.py:328

**What is wrong.** SQLite orders TEXT by bytes. PostgreSQL uses the database's collation, which on managed services and the official image is a locale or ICU collation. Names may contain '.', '-', '_' and '/', file paths may contain capitals, and those sort differently. Uniqueness is unaffected, because both databases compare deterministically and names are validated lowercase.

**How it was confirmed.** On my PostgreSQL 16: under ICU en-US the list sorts as 'backend &lt; backend-tools &lt; backend/api &lt; examples/a.md &lt; j_smith &lt; j-smith &lt; j.smith &lt; jsmith &lt; README.md &lt; Zeta.md'. Under C.UTF-8, and in SQLite / Python sorted(), it sorts as 'README.md &lt; Zeta.md &lt; ... &lt; j-smith &lt; j.smith &lt; j_smith &lt; jsmith'.

**Proposed fix.** Either sort these small result lists in Python in the services (the same order on both databases), or have the engine module expose a portable binary collation and apply .collate() in the order_by calls (PostgreSQL 'C', SQLite 'BINARY'), keeping the dialect choice inside db/engine.py as ADR-0002 asks.

**Done when.** A portable test (portable_engine fixture) creates groups 'a-b', 'a.b', 'a_b' and 'ab' and asserts the same order from team_service.groups on SQLite and on an en_US/ICU PostgreSQL database.

**Resolution (step 18b).** `db/ordering.py`'s `bytewise()` orders by bytes on both databases (`COLLATE "C"` on PostgreSQL, SQLite's own BINARY), and the listed `order_by` calls use it, file paths included. `library_event.sort_key` is left as it is: it is fixed-width lowercase hex, digits and punctuation in the same places, which every collation orders as its bytes, and a collated ORDER BY would stop PostgreSQL using its unique index for the newest event.

### DB-15: as_utc returns a non-UTC time on PostgreSQL when the database's TimeZone is not UTC

**Confirmed.** Severity **Info**, effort **S**. Hurts: Operators of a managed PostgreSQL whose default time zone is local: dashboard JSON carries '+03:00' times on PostgreSQL and '+00:00' on SQLite.

**Where.** src/aistack/db/models/timestamps.py:15-21

**What is wrong.** as_utc returns an aware value unchanged. psycopg returns timestamptz in the session's TimeZone, so 'as UTC' is UTC only on SQLite or on a UTC-configured server. The instants are the same, so the arithmetic is correct, but the serialized form differs per database, against 'runs identically on both'.

**How it was confirmed.** ALTER DATABASE t1 SET timezone = 'Europe/Athens' on my PostgreSQL, then as_utc(User.created_on) returned datetime(..., tzinfo=ZoneInfo('Europe/Athens')), isoformat '2026-10-15T18:29:07.014251+03:00'.

**Proposed fix.** Return moment.astimezone(timezone.utc) for aware values in as_utc; optionally also pass connect_args={'options': '-c TimeZone=UTC'} for PostgreSQL in build_engine.

**Done when.** A PostgreSQL test with the database time zone set to a non-UTC zone asserts as_utc(...).utcoffset() == timedelta(0).

## Checked and holding up

- Models and migrations agree on both databases. tests/db/test_schema.py passed (29 passed, 1 skipped) with TEST_DATABASE_URL on PostgreSQL 16. A pg_dump -s / sqlite_master diff of migrate_schema vs create_all (diff_schema.py) shows only column order, constraint names, and can_invite's DEFAULT false.
- Upgrades between releases. Code extracted from be8e64b (head 0007), 9d01f87 (0008) and ed3e04f (0009) ran every step of exercise.py (join, two pushes, sync, get_skill and disable on agents, create_team, share, invite, list_skills, list_teams, dashboard state, remove/restore) on a database migrated to 0010, on SQLite and PostgreSQL. The 0007-era release created data that the current code then read without error.
- schema_compatibility mechanism: _record_compatibility records oldest = 0006 (the newest migration without the flag); an unknown head with a known oldest runs, an unknown oldest raises NewerSchema and changes nothing; on PostgreSQL the advisory lock serializes concurrent starts; on SQLite migrations run with foreign keys off and PRAGMA foreign_key_check before commit.
- Every migration from 0007 on declares older_releases_compatible, never imports a model (uses sa.table), and writes the single-admin index predicate as an expression; 0001-0006 are untouched records.
- ON DELETE behaviour: deleting a machine (the OPERATING.md script) cascades only machine_skill and machine_harness; deleting a user is refused by NO ACTION foreign keys from machine, skill, skill_version, team, team_member, group_member, group_unsubscribed and invite, matching 'Never delete a user'; deleting a team skill sets source_skill_id to NULL on personal copies and cascades nothing into anyone's Library; team_group and invite cascade from team (no team-delete path exists).
- Length enforcement: every VARCHAR (username 64, full_name 100, machine.name 64, team.name 64, group path 255, skill name 64, description 1024, origin 255, version 32, file path 255, sort_key 128, kind 32) is validated in the service before it reaches the database, so PostgreSQL never rejects what SQLite accepted.
- NUL characters and unpaired surrogates in file content and frontmatter are rejected at push (skill_validation.py:303 and :386-398), so the JSONB and TEXT columns on PostgreSQL never see input SQLite would accept; frontmatter is BaseLoader strings, so json.dumps cannot emit NaN.
- Case sensitivity and uniqueness: usernames, team names, group names and skill names are validated lowercase [a-z0-9._-], and both databases compare deterministically, so uniqueness is identical; machine names are case-sensitive on both alike.
- Timestamps: every write comes from utc_now; every read used in arithmetic or rendered goes through as_utc (invites, dashboard, archive mtimes); SQLite's fixed microsecond text format orders correctly.
- Revision, row and admin races are held by unique constraints with savepoint retries (uq_skill_version_skill_revision, uq_machine_skill_machine_harness_skill, uq_machine_harness_machine_harness, uq_skill_team_name, ix_user_single_admin), and invite use is a conditional UPDATE.
