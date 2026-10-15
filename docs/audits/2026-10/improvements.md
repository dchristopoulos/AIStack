# Improvements

Everything else that would make the product clearly better, ranked by value for effort: test gaps, code health, performance, documentation drift, and features that are cheap now.

How far this was checked: each finding below was reproduced or traced line by line by the auditor who raised it, and **Confirmed** means exactly that. The independent second pass that tries to refute each finding ran only for the authorization and UX findings: the account's weekly limit stopped the rest. Where the main session re-checked a finding itself, its entry says so. Treat **Suspected** findings, and anything marked High or Critical without a second pass, as needing a reproduction before the fix lands; the reproduction is described in each.

| Id | Finding | Severity | Status | Effort |
|---|---|---|---|---|
| [IMP-01](#imp-01-the-windows-job-gates-neither-merging-nor-publishing-and-local-mode-then-updates-itself-from-pypi) | The Windows job gates neither merging nor publishing, and local mode then updates itself from PyPI | High | Confirmed | S |
| [IMP-02](#imp-02-unsubscribing-from-a-group-stops-syncs-update-offers-but-not-the-dashboards) | Unsubscribing from a group stops sync's update offers but not the dashboard's | Medium | Confirmed | S |
| [IMP-03](#imp-03-the-log-replay-test-cannot-catch-a-localhost-dashboard-write-that-forgets-its-log-event) | The log-replay test cannot catch a localhost-dashboard write that forgets its log event | Medium | Confirmed | S |
| [IMP-04](#imp-04-admin-and-destructive-dashboard-paths-never-run-in-any-test-privacy-of-an-existing-group-moving-or-removing-a-team-skill-subscribing-and-console-errors-are-mostly-unchecked) | Admin and destructive dashboard paths never run in any test: privacy of an existing group, moving or removing a team skill, subscribing; and console errors are mostly unchecked | Medium | Confirmed | S |
| [IMP-05](#imp-05-setup-can-run-from-github-today-but-the-steps-it-prints-still-install-from-pypi-follows-from-the-known-missing-release) | Setup can run from GitHub today, but the steps it prints still install from PyPI (follows from the known missing release) | Medium | Confirmed | S |
| [IMP-06](#imp-06-the-dashboard-cannot-say-when-a-computer-last-synced-or-which-revision-it-holds) | The dashboard cannot say when a computer last synced or which revision it holds | Medium | Confirmed | M |
| [IMP-07](#imp-07-apistate-queries-per-team-and-per-member-inside-sqlites-write-lock-concurrent-refreshes-delay-everyones-sync-and-return-500) | /api/state queries per team and per member inside SQLite's write lock: concurrent refreshes delay everyone's sync and return 500 | Medium | Confirmed | M |
| [IMP-08](#imp-08-no-way-to-see-what-a-teammate-changed-before-taking-an-offered-update) | No way to see what a teammate changed before taking an offered update | Medium | Confirmed | M |
| [IMP-09](#imp-09-a-person-cannot-retire-revoke-or-rename-their-own-computer-only-the-operator-can) | A person cannot retire, revoke or rename their own computer; only the operator can | Medium | Confirmed | M |
| [IMP-10](#imp-10-designmd-the-document-that-wins-on-conflict-contradicts-the-code-in-a-dozen-places) | DESIGN.md, the document that 'wins' on conflict, contradicts the code in a dozen places | Medium | Confirmed | M |
| [IMP-11](#imp-11-a-first-sync-with-many-skills-costs-one-tool-call-per-backup-and-in-a-github-library-one-commit-and-push-per-skill) | A first sync with many skills costs one tool call per backup, and in a GitHub Library one commit and push per skill | Medium | Confirmed | M |
| [IMP-12](#imp-12-tool-results-and-listings-spend-the-agents-context-on-what-it-never-uses-and-two-descriptions-have-no-room-left) | Tool results and listings spend the agent's context on what it never uses, and two descriptions have no room left | Low | Confirmed | S |
| [IMP-13](#imp-13-try-it-in-two-minutes-dead-ends-after-five-minutes-and-the-contributor-test-instructions-skip-the-browser-tests) | 'Try it in two minutes' dead-ends after five minutes, and the contributor test instructions skip the browser tests | Low | Confirmed | S |
| [IMP-14](#imp-14-readme-has-drifted-adr-list-size-claims-a-stale-known-limit-a-built-roadmap-item-and-old-screenshots) | README has drifted: ADR list, size claims, a stale known limit, a built roadmap item, and old screenshots | Low | Confirmed | S |
| [IMP-15](#imp-15-one-team-update-is-offered-once-per-folder-and-again-on-every-sync-after-it-was-declined) | One team update is offered once per folder, and again on every sync after it was declined | Low | Confirmed | S |
| [IMP-16](#imp-16-a-skill-that-can-never-be-backed-up-is-listed-under-backup-on-every-sync) | A skill that can never be backed up is listed under backup on every sync | Low | Confirmed | S |
| [IMP-17](#imp-17-no-static-check-guards-the-python-or-the-pages-1876-line-script-and-the-page-ships-an-untested-200-line-fake-backend) | No static check guards the Python or the page's 1,876-line script, and the page ships an untested 200-line fake backend | Low | Confirmed | S |
| [IMP-18](#imp-18-most-of-the-server-log-is-mcp-sdk-chatter) | Most of the server log is MCP SDK chatter | Low | Confirmed | S |

AIStack is in good shape where it matters most. The non-browser suite passes (996 tests) with 94% line coverage, sync stays fast at scale (300 skills in about 50 ms on the server), and the Python and the page's script are lint-clean today with nothing enforcing that. The best value for effort is in four places: release gating (the Windows job gates neither merge nor publishing, while local mode updates itself from PyPI), tests that look complete but miss real paths (local-dashboard writes skipping the log, making an existing group private, moving or removing a team skill), one shared cost in the dashboard (/api/state runs one or more queries per team and per member inside SQLite's write lock, which under concurrent refreshes delays syncs and returns 500s), and docs that have drifted from the code (DESIGN.md, which wins on conflict, still says "No CLI" and leaves out two tables and local mode). On the product side, cheap features would close the loop the manual-sync model leaves open: when each computer last synced and which revision it holds, a diff before taking a teammate's update, removing or renaming your own computer, and backing up many skills in one call on a first sync. All probes ran against my own server on port 8210 (now stopped) and scratch copies under &lt;scratch&gt;/improvements/. Nothing in the repository was changed.

### IMP-01: The Windows job gates neither merging nor publishing, and local mode then updates itself from PyPI

**Confirmed.** Severity **High**, effort **S**. Hurts: Every Windows user of local mode (the PyPI package runs on their computer), and the maintainer, who relies on auto-merge

**Where.** .github/workflows/tests.yaml:222 and :269 (`needs: [pytest, browsers, container]`); .agents/skills/ship-a-change/SKILL.md:34 (required checks list); src/aistack/bootstrap/self_update.py:47-66

**What is wrong.** AGENTS.md says the publish job needs every test job. Both `publish` and `pypi` leave out `windows`, and the required checks the ship skill relies on for auto-merge are `pytest`, `browsers (firefox)`, `browsers (webkit)` and `container`, without `windows`. So a PR that turns the Windows job red merges itself, a `v*` tag publishes it to PyPI, and `self_update.check_and_upgrade` runs `uv tool upgrade aistack-mcp` within 24 hours on every computer installed with `uv tool install`. A Windows break would spread with no human in the loop. No macOS job exists either, though local mode has macOS-only paths: `system_profiler` naming in application_context.py:197-213, and `/opt/homebrew/bin` lookups for gh and uv in library_repo.py:226-237 and self_update.py:78-87.

**How it was confirmed.** Read tests.yaml: `windows` is defined at line 107 and missing from `needs` at 222 and 269. Read ship-a-change/SKILL.md:34 for the required checks. Traced self_update.start_in_background (called from bootstrap/__main__.py:69 on every local start) through check_and_upgrade, which only checks the PyPI version and then upgrades.

**Proposed fix.** Add `windows` to `needs` of `publish` and `pypi` in tests.yaml. Make `windows` a required status check on main and list it in ship-a-change/SKILL.md step 4. Add a `macos-latest` job running the same subset as `windows`. Add a small test (e.g. tests/test_ci_workflow.py) that loads tests.yaml with PyYAML and asserts `publish` and `pypi` need every other job, so a new test job cannot be left out again.

**Done when.** The new workflow test fails on today's tests.yaml and passes once `windows` is in both `needs` lists. Branch protection lists `windows` as required, and a PR with a red Windows job cannot auto-merge.

Related: [AUTO-19](automation.md#auto-19-every-way-to-set-up-another-computer-in-local-mode-and-the-self-updater-depend-on-pypi), [IMP-05](#imp-05-setup-can-run-from-github-today-but-the-steps-it-prints-still-install-from-pypi-follows-from-the-known-missing-release), [LH-01](plot-holes.md#lh-01-local-mode-cannot-be-installed-aistack-mcp-is-not-on-pypi-and-no-release-has-ever-been-tagged), [STD-02](industry-standards.md#std-02-the-pypi-name-every-setup-sentence-runs-aistack-mcp-is-unregistered-and-anyone-can-take-it), [UX-10](ux.md#ux-10-the-dashboard-and-the-local-sync-skill-hand-out-uvx-aistack-mcp-setup-and-uv-tool-install-aistack-mcp-which-fail-today).

### IMP-02: Unsubscribing from a group stops sync's update offers but not the dashboard's

**Confirmed.** Severity **Medium**, effort **S**. Hurts: A member who unsubscribed to stop the nagging: the Library keeps the blue dot, the Updates count and the Take update button

**Where.** src/aistack/services/dashboard_service.py:231 (`update_available` ignores subscriptions); compare src/aistack/services/sync_service.py:315-318; the page's own promise at src/aistack/bundled/dashboard.html:1884

**What is wrong.** DESIGN.md says "A user who unsubscribes from a group is not offered its updates", and the toast after unsubscribing says "You will not be offered their updates". Sync filters out unsubscribed groups through `visibility.group_access(...).unsubscribed`. `dashboard_service._my_skills` computes `update_available = source.revision > source_revision` with no such filter. The two surfaces disagree, and the one the user is looking at keeps offering.

**How it was confirmed.** Script &lt;scratch&gt;/improvements/unsubscribe_probe.py against my own server. An admin shares probe-skill into group `backend`, a member takes it with get_skill, the admin pushes and shares r2, and the member unsubscribes with POST /api/teams/{team}/group {path, subscribed:false}. Output: before, dashboard update_available=True and sync team_updates=['probe-skill']; after, group subscribed=False, dashboard update_available=True, sync team_updates=[].

**Proposed fix.** In dashboard_service.state, compute `quiet = visibility.group_access(session, user_id).unsubscribed` once. Carry the team skill's group_id through `_team_skills` (select `visible.c.group_id`). In `_my_skills`, set `update_available` to false when the source's group_id is in `quiet`, keeping `latest_revision` so the page can still show it on request. Add a test to tests/api/test_dashboard_over_http.py covering an unsubscribed group and a group beneath it.

**Done when.** A new HTTP test shows update_available false after unsubscribing (from the group or a parent) and true again after resubscribing, matching sync's team_updates. It fails today.

Related: [DB-13](schema.md#db-13-group-unsubscriptions-survive-leaving-a-team-so-a-returning-member-silently-misses-updates).

### IMP-03: The log-replay test cannot catch a localhost-dashboard write that forgets its log event

**Confirmed.** Severity **Medium**, effort **S**. Hurts: Someone with two computers on a GitHub Library: a dashboard change that is not logged never reaches their other computers and disappears when the copy is rebuilt

**Where.** tests/mcp/test_library_log.py:128-145 (re-implements the route bodies); src/aistack/api/dashboard.py:186-191 and :209-211 (lines 188 and 210 run in no non-browser test)

**What is wrong.** AGENTS.md says test_library_log.py "replays random sequences to catch" a local write path that skips the log. For the dashboard's two local write actions (place a skill, remove from Library), the test copies the route's service call and `library_log.record` into the test itself instead of calling the route. Deleting the record calls from api/dashboard.py therefore breaks nothing. Nothing makes a future `_action(..., local=True)` record an event either.

**How it was confirmed.** Mutation test. I copied the repo with `git archive` to &lt;scratch&gt;/improvements/mutant and replaced both `library_log.record(...)` blocks in src/aistack/api/dashboard.py with `pass`. Then I ran `PYTHONPATH=<mutant>/src:<mutant> python -m pytest tests/mcp/test_library_log.py tests/api/test_local_dashboard.py tests/mcp/test_local_mode.py tests/mcp/test_library_github.py` from the mutant: 61 passed. The coverage run of the non-browser suite also reports dashboard.py lines 188 and 210 as never executed. tests/ui/test_local_dashboard_page.py performs no write action.

**Proposed fix.** In `_random_changes`, perform 'remove' and 'place' through the real localhost routes: tests/local_dashboard.py already serves LOCAL_ROUTES in-process, so sign in once and POST /api/skills/{name}/remove and /api/skills/{name}/machines/{id}. Add a structural test that every POST in `LOCAL_ROUTES` except /api/logout adds at least one `library_event` row on success. Optionally make `_action` take the event to record, so a local action cannot be registered without one.

**Done when.** Rerunning the mutant above makes tests/mcp/test_library_log.py fail, and coverage shows dashboard.py:188 and :210 executed.

### IMP-04: Admin and destructive dashboard paths never run in any test: privacy of an existing group, moving or removing a team skill, subscribing; and console errors are mostly unchecked

**Confirmed.** Severity **Medium**, effort **S**. Hurts: Team admins and members: a regression in who can see a group's skills (a visibility trust boundary) or in removing a team's copy would ship green

**Where.** src/aistack/services/team_service.py:389 (set_group success path); src/aistack/api/dashboard.py:277-285, :294-302; page controls at src/aistack/bundled/dashboard.html:1881, :1993, :2127; tests/ui/conftest.py:58-62

**What is wrong.** The coverage run of the whole non-browser suite never executes the success path of `team_service.set_group` (an admin making an existing group private or open). tests/services/test_teams.py:473 only checks that a member is refused. The routes for group privacy and subscription, moving a team skill, and removing a team skill (destructive: deletes the team's copy and its history) also never run. No browser test clicks Move…, the privacy switch of an existing group, or the Subscribed switch. Separately, 17 of the 32 browser test functions never assert on the console errors the fixture collects: 13 in test_dashboard_page.py and all 4 in test_local_dashboard_page.py, which do not use `Opened` at all.

**How it was confirmed.** Installed coverage into &lt;scratch&gt;/improvements/covlib and ran `COVERAGE_CORE=sysmon PYTHONPATH=<covlib> python -m coverage run --source=src/aistack -m pytest -q -p no:cacheprovider --ignore=tests/ui --ignore=tests/e2e tests`: 996 passed, 7 skipped, 94% total. `coverage report -m` lists team_service.py 389 and dashboard.py 279-285, 296, 302 as missed. grep of tests/ui and tests/api finds no call to /group, /move or /skills/{name}/remove under /teams. An AST scan of tests/ui counted the test functions without `console_errors`. private_toggle.py in my folder shows the behavior is right today: after the toggle a non-member's groups, team skills and list_skills entries go from ['secret'], ['hidden-one'], ['hidden-one'] to empty.

**Proposed fix.** Add to tests/api/test_dashboard_over_http.py: an admin makes an open group private, then a non-member's /api/state and list_skills lose it and a group member keeps it; toggle back; move a skill into a private group; remove a team skill, after which the member's taken copy stays and its source is null; unsubscribe through the route. Add browser tests for the Move… dialog, the privacy switch of an existing group and the Subscribed switch. Assert `console_errors == []` in the `sign_in` fixture's teardown for every Opened page, and wrap the local-dashboard pages in Opened.

**Done when.** Coverage shows team_service.py:389 and dashboard.py:279-302 executed, and an error thrown in the Move dialog's handler fails a browser test.

### IMP-05: Setup can run from GitHub today, but the steps it prints still install from PyPI (follows from the known missing release)

**Confirmed.** Severity **Medium**, effort **S**. Hurts: A newcomer following README's first instruction, until the first release

**Where.** README.md:23; src/aistack/bundled/local/setup.md:25; src/aistack/bundled/local/sync-aistack/SKILL.md:15; src/aistack/bootstrap/self_update.py:52-66

**What is wrong.** With aistack-mcp absent from PyPI, `uvx --from git+https://github.com/dchristopoulos/AIStack aistack-mcp setup` works and prints the setup steps. Step 1 of those steps (setup.md:25) is `uv tool install aistack-mcp`, which then fails, and so does the recovery advice in the local sync skill. A computer installed from git also never updates itself: check_and_upgrade asks PyPI first, and the failure is logged only at INFO.

**How it was confirmed.** Ran `HOME=<scratch> UV_CACHE_DIR=<scratch> uvx --from git+https://github.com/dchristopoulos/AIStack aistack-mcp setup` in &lt;scratch&gt;/improvements/uvx-home. It exited 0 and printed '# Set up AIStack on this computer' (output in uvx-setup.out in my folder). Read setup.md:25 and self_update.py.

**Proposed fix.** Cut v0.1.0: the `pypi` job exists, but confirm the trusted publisher on pypi.org first, and add IMP-01's gating. Until then, have README.md:23 and setup.md:25 give the git source (`uv tool install git+https://github.com/dchristopoulos/AIStack`), or better, have `aistack setup` print the install command matching how it was installed: read `importlib.metadata.distribution('aistack-mcp').read_text('direct_url.json')` and print the VCS URL when there is one. After the release, add a step to the pypi job that runs `uvx aistack-mcp@<version> setup` from the index.

**Done when.** On a clean HOME, README's sentence plus the printed steps ends with `aistack-mcp check` printing 'AIStack is ready.'

Related: [AUTO-19](automation.md#auto-19-every-way-to-set-up-another-computer-in-local-mode-and-the-self-updater-depend-on-pypi), [IMP-01](#imp-01-the-windows-job-gates-neither-merging-nor-publishing-and-local-mode-then-updates-itself-from-pypi), [LH-01](plot-holes.md#lh-01-local-mode-cannot-be-installed-aistack-mcp-is-not-on-pypi-and-no-release-has-ever-been-tagged), [STD-02](industry-standards.md#std-02-the-pypi-name-every-setup-sentence-runs-aistack-mcp-is-unregistered-and-anyone-can-take-it), [UX-10](ux.md#ux-10-the-dashboard-and-the-local-sync-skill-hand-out-uvx-aistack-mcp-setup-and-uv-tool-install-aistack-mcp-which-fail-today).

### IMP-06: The dashboard cannot say when a computer last synced or which revision it holds

**Confirmed.** Severity **Medium**, effort **M**. Hurts: Anyone with two or more computers: with no background sync, a computer that has not synced for weeks, or ever, looks exactly like a current one

**Where.** src/aistack/services/dashboard_service.py:126-147 (machines without last_synced_on) and :202-209 (placements without revision); src/aistack/bundled/dashboard.html:1699-1703 (a computer page's 'Revision' column shows the Library's latest revision)

**What is wrong.** The server records `machine_harness.last_synced_on` on every sync (sync_service.py:250-267) and `machine_skill.revision` on every install and push, but /api/state sends neither: a machine is only {id, name, os, harnesses}. The computer page labels the Library's newest revision 'Revision', so 'r2' reads as 'this computer has r2' even when it still has r1. DESIGN.md says a placement is a decision, 'not proof the files are there yet', yet the page never shows the difference. In the seeded demo, 'desktop' was added and has never synced, and nothing on its page says so.

**How it was confirmed.** perf_sync.py in my folder printed `machine keys: ['id', 'name', 'os', 'harnesses']` from /api/state. state_keys.py printed the full state shape. Read dashboard.html:1699-1703, where the cell is `'r' + s.revision`. Screenshot computer-desktop-light.png shows the 'Revision' column and the desktop computer with no sync information.

**Proposed fix.** In `dashboard_service._machines`, return the harnesses with `last_synced_on` (ISO or null). In placements, add `revision` from machine_skill. On the page, show in the computer header 'Last synced 3 days ago' or 'Not synced yet: say sync aistack there', and in the folder table 'r1 here · r2 in your Library, arrives at the next sync'. Document the new fields in DESIGN's /api/state table. In a GitHub Library only a folder's first sync is logged (src/aistack/mcp/tools/local.py:88-92), so show other computers' times only where the database is shared (server, PostgreSQL), or log a periodic 'synced' event.

**Done when.** For the demo seed, /api/state shows desktop's claude_code last_synced_on as null and macbook's as a time. A browser test finds 'Not synced yet' on desktop's page and 'r1 here' after a newer revision is pushed from another computer.

Related: [AUTO-02](automation.md#auto-02-on-a-server-a-person-cannot-cut-off-their-own-lost-or-stolen-computer), [AUTO-20](automation.md#auto-20-computers-cant-be-renamed-or-removed-and-a-reinstall-leaves-vm-and-vm-2-forever), [IMP-09](#imp-09-a-person-cannot-retire-revoke-or-rename-their-own-computer-only-the-operator-can), [PH-13](plot-holes.md#ph-13-owners-cannot-rename-or-remove-a-computer-and-nothing-shows-when-a-computer-last-synced), [SEC-01](security.md#sec-01-a-stolen-machine-token-outlives-the-documented-revocation-sibling-tokens-dashboard-sessions-and-upload-urls-keep-working), [STD-04](industry-standards.md#std-04-a-person-cannot-see-when-each-computer-last-connected-or-remove-a-lost-one-and-a-stolen-tokens-push-lands-silently-on-their-other-computers).

### IMP-07: /api/state queries per team and per member inside SQLite's write lock: concurrent refreshes delay everyone's sync and return 500

**Confirmed.** Severity **Medium**, effort **M**. Hurts: Everyone on a team server running SQLite (the default) once users are in several teams. The page reloads state on every window focus, so dashboards load it constantly

**Where.** src/aistack/services/dashboard_service.py:38-74; src/aistack/services/team_service.py:260-281 (`_groups_of` per member at :274) and :284-297; src/aistack/services/visibility.py:138 (group_access recomputed per call); src/aistack/db/engine.py:28 and :63-72 (BEGIN IMMEDIATE for every transaction); src/aistack/api/dashboard.py:359-363; src/aistack/bundled/dashboard.html:2512-2513

**What is wrong.** state() runs, for each team, a membership select, `members()` (one `_groups_of` query per member), `groups()` (group_access: 3 queries), `invites()`, and `team_skills()`, which recomputes group_access. The SQL count grows with teams × members. Every SQLite transaction takes the write lock at BEGIN (ADR-0014), so this read-only request holds the server-wide lock throughout. ADR-0014 accepted that cost because 'AIStack's transactions are a handful of indexed statements' and named the fix (mark read-only sessions and begin them deferred). /api/state no longer meets that premise.

**How it was confirmed.** Scripts in &lt;scratch&gt;/improvements/ against my own server. count_queries.py attaches a before_cursor_execute counter and calls dashboard_service.state directly: a user in 15 teams (6 groups, 40 skills, 5 members each) takes 251 statements and 188 ms; a 31-member team takes 53 statements (members_scale.py: one per member); a user with only 300 skills takes 11 statements and 18 ms, and list_skills is always 5. lock_contention.py builds a similar 15-team user, fires K concurrent GET /api/state plus one sync from another user: K=20 gives state median 2.8 s and the other user's sync 3.8 s (0.17-0.28 s alone); K=40 gives some /api/state 500s (4 'database is locked' tracebacks in my server.log) and the sync 6.0 s.

**Proposed fix.** (1) Compute `visibility.group_access` once per state and pass it into `team_service.groups`, `members` and `visibility.team_skills` as an optional argument, keeping each function's leading `visibility.membership` check (AGENTS.md). (2) Replace the per-member `_groups_of` with one query per team, grouped in Python. (3) Take each team's `TeamMember` row from list_teams' join instead of a separate select. (4) As ADR-0014 itself proposes, open read-only transactions (/api/state, list_skills) with a deferred BEGIN through a read-only flag on the session factory, and add a note to ADR-0014. (5) Map OperationalError 'database is locked' to 503 with a sentence instead of a bare 500.

**Done when.** A test counting statements for a user in 3 teams of 10 members asserts a bound that does not grow with members or teams (it fails today), and lock_contention.py with K=40 returns no 500.

Related: [DB-02](schema.md#db-02-dashboard-state-issues-one-query-per-team-member-plus-a-dozen-per-team-n1), [ENT-10](concurrency-and-reliability.md#ent-10-dashboard-state-queries-once-per-team-member-and-runs-inside-the-sqlite-write-lock-about-180-ms-per-page-load-for-a-400-member-team).

### IMP-08: No way to see what a teammate changed before taking an offered update

**Confirmed.** Severity **Medium**, effort **M**. Hurts: Every member offered a team update: the only information is who pushed it and the revision numbers

**Where.** src/aistack/bundled/dashboard.html:1617 and :1664 (the offer shows `r1 → r2, pushed by …` and Take update); src/aistack/mcp/tools/sync.py:51-56 (TeamUpdateEntry); src/aistack/api/dashboard.py (no route serves a skill's content)

**What is wrong.** ADR-0015 makes a teammate's change an offer, and DESIGN's security posture says the mitigation is 'visibility at the moment of risk'. Yet nothing in the dashboard or over MCP shows the change itself. Reading what changed means taking it, which replaces the user's latest copy (the old one survives only in history). A skill is instructions to an agent, so this is the decision that most needs the content.

**How it was confirmed.** Read every route in api/dashboard.py: none returns file content. Screenshot maria-library-update-desktop-light.png shows the offer row with 'Update available r1 → r2 pushed by dimitris' and only 'Take update'. skill-panel-desktop-light.png shows the details panel with metadata and no content.

**Proposed fix.** Add a service `skill_service.team_update_changes(session, user_id, team, name)` that reaches the team copy through `visibility.team_skill` and the user's copy through `visibility.required_my_skill`, and returns a per-file unified diff (difflib; files are UTF-8 by push validation) between the user's latest revision and the team's latest, with a size cap. Add a route `GET /api/teams/{team}/skills/{name}/changes` (local=False), documented in DESIGN's route table (the docs test enforces that). Add 'Review changes' beside 'Take update', rendering the diff through `el()` text nodes only. No ADR needed: it shows only what the user may already take.

**Done when.** A browser test as maria opens Review changes on code-review and reads the line demo_seed adds ('Also check that migrations are reviewed.'), and an HTTP test shows an outsider gets the same 404 as for an unknown skill.

### IMP-09: A person cannot retire, revoke or rename their own computer; only the operator can

**Confirmed.** Severity **Medium**, effort **M**. Hurts: A member of a team server whose laptop is lost or sold (the operator is someone else); someone with two Windows PCs named 'Windows PC' and 'Windows PC-2'

**Where.** src/aistack/api/dashboard.py (no machine route); docs/OPERATING.md:127-178; README.md:347; naming in src/aistack/services/library_log.py:224-229 and src/aistack/bootstrap/context/application_context.py:197-213

**What is wrong.** README lists revoking a machine as 'server administration… a documented script'. Removing one's own computer affects no one else, though. Today a stolen laptop's token keeps working until the operator runs a script inside the container, a retired computer stays in the rail and in every Add to… dialog forever, and auto-generated names can only be fixed in the database. This dead-ends the user rather than being a deliberate admin boundary.

**How it was confirmed.** Listed every @_route and @_action in api/dashboard.py: none touches Machine. Read OPERATING.md's 'A laptop was lost or stolen' and 'A machine is gone for good' sections. Read `_add_machine`'s '-2' suffixing and `_computer_name`, which returns 'Windows PC' for every Windows computer.

**Proposed fix.** Add `onboarding_service.remove_machine(session, user_id, machine_id)` and `rename_machine(...)` with the ownership check `dashboard_service.set_on_machine` uses (someone else's machine is NotFound), refusing to remove the last machine with a sentence (`require_a_machine` would otherwise end the session). Add routes `POST /api/machines/{machine_id}/remove` and `/rename`, server-only at first (local=False: local mode would need new log event kinds under ADR-0025). Add a confirm on the computer page saying the computer's connection stops working at once. Update DESIGN's route table, and keep the operator script for the last-machine case.

**Done when.** An HTTP test removes 'desktop' and its token then gets 401 at /mcp, removing another user's machine id answers 404, removing the last machine is refused, and a browser test renames a computer.

Related: [AUTO-02](automation.md#auto-02-on-a-server-a-person-cannot-cut-off-their-own-lost-or-stolen-computer), [AUTO-20](automation.md#auto-20-computers-cant-be-renamed-or-removed-and-a-reinstall-leaves-vm-and-vm-2-forever), [IMP-06](#imp-06-the-dashboard-cannot-say-when-a-computer-last-synced-or-which-revision-it-holds), [PH-13](plot-holes.md#ph-13-owners-cannot-rename-or-remove-a-computer-and-nothing-shows-when-a-computer-last-synced), [SEC-01](security.md#sec-01-a-stolen-machine-token-outlives-the-documented-revocation-sibling-tokens-dashboard-sessions-and-upload-urls-keep-working), [STD-04](industry-standards.md#std-04-a-person-cannot-see-when-each-computer-last-connected-or-remove-a-lost-one-and-a-stolen-tokens-push-lands-silently-on-their-other-computers).

### IMP-10: DESIGN.md, the document that 'wins' on conflict, contradicts the code in a dozen places

**Confirmed.** Severity **Medium**, effort **M**. Hurts: Contributors and coding agents, who AGENTS.md tells to treat DESIGN.md as authoritative

**Where.** docs/DESIGN.md:67, :71, :555, :568, :608-609, :618, :622, §4 Schema (:398-536), /api/state (:331-392); docs/adr/0020-local-mode-and-where-the-library-lives.md:3

**What is wrong.** Contradictions found: (1) ADR-0025 is '(proposed)' at :67, while the ADR says accepted. (2) :71 says 'No CLI, no daemon' and :555 'no CLI/daemon', but `aistack` has serve/dashboard/setup/sync-skill/check/export/github and a background self-update thread. (3) :608-609 lists five subcommands. (4) :618 says 'fourteen tables'; the models declare 15. (5) :622 says 'local mode's five' tools; local_mcp registers six. (6) The Schema section has no LIBRARY_EVENT, no SCHEMA_COMPATIBILITY and no team_member.can_invite. (7) The /api/state documentation lacks teams[].can_invite, members[].can_invite, teams[].invites and library kind 'github' with its repository. (8) Roadmap item 1 at :568 (second harness) is built but not marked so, unlike items 2 and 8. (9) Nothing describes local mode's tool contracts, such as push_skill's `shared` or sync's `folders` and `harness`. (10) ADR-0020's status says 'Not built yet'.

**How it was confirmed.** grep of __tablename__ in src/aistack/db/models gives 15 names. desc_len.py (in my folder) lists local tools disable_skill, get_skill, list_skills, open_dashboard, push_skill and sync. state_keys.py printed the actual state shape including can_invite and invites. Read each ADR's status line and bootstrap/__main__.py:186-188 for the subcommands.

**Proposed fix.** Bring DESIGN.md up to date: a local-mode subsection in §4 with the six tools and the CLI, the two tables and the column in Schema, the state fields, ADR-0025's status, and the roadmap. Fix ADR-0020's status line. Extend tests/api/test_dashboard_routes_are_documented.py with a check that every key `dashboard_service.state` returns appears in DESIGN's field table, and add a test that the tool names listed in DESIGN match `mcp` and `local_mcp`.

**Done when.** The extended doc test fails on today's DESIGN.md (`invites` is undocumented) and passes after the update, and DESIGN.md no longer says 'No CLI'.

Related: [IMP-14](#imp-14-readme-has-drifted-adr-list-size-claims-a-stale-known-limit-a-built-roadmap-item-and-old-screenshots), [PH-17](plot-holes.md#ph-17-design-operating-and-context-describe-a-server-that-has-since-changed).

### IMP-11: A first sync with many skills costs one tool call per backup, and in a GitHub Library one commit and push per skill

**Confirmed.** Severity **Medium**, effort **M**. Hurts: A newcomer whose computer already holds dozens of skills (README's own reference run had 25), on their first sync

**Where.** src/aistack/mcp/tools/skills.py:70-100 (push_skill takes one name); src/aistack/mcp/tools/local.py:216-234; src/aistack/services/library_sharing.py:50-64 (publish after every write)

**What is wrong.** Sync lists every new skill under `backup` and the agent pushes each one: a tool call per skill, plus tar and curl on a server. In a GitHub Library each push is its own commit and push. The server side is cheap; the cost is the agent's turns and tokens, plus one GitHub round trip per skill. DESIGN §4 'Bulk import: not a tool' can stay true with a list argument instead of a new tool.

**How it was confirmed.** perf_local.py in my folder drives local mode over stdio with 50 skills, with a local bare git repo standing in for GitHub: 50 push_skill calls (median 69 ms each) and 52 commits on the remote. The SQLite Library took 1.0 s for 50. perf_sync.py on my server: 300 sequential push_skill plus PUT took 6.0 s (19 ms median), so the server is not the bottleneck. Agent turn counts are not measured here; README records 14 turns for a sync with 2 backups.

**Proposed fix.** Local mode first: let push_skill take `names: list[str]` (or `name` or `names`). Each skill is read and validated before its transaction, stored in its own transaction with its log event, and `library_after_write` runs once at the end: one call, one commit, one push, with a per-name result that includes refusals. On a server, `push_skill(names=[...])` returns one upload_url per name. Update the sync tool description and both sync-aistack skills to push the whole backup list in one call.

**Done when.** perf_local.py with 50 skills makes one push_skill call and at most two commits, and a test in tests/mcp/test_local_mode.py pushes three names in one call, one of them refused, and finds two revisions and one reason.

### IMP-12: Tool results and listings spend the agent's context on what it never uses, and two descriptions have no room left

**Confirmed.** Severity **Low**, effort **S**. Hurts: Every connected agent: tokens per install and per 'what skills do my teams have?'

**Where.** src/aistack/mcp/tools/skills.py:30 (`_LISTING_RESULT_MAX_CHARS = 500_000`), :217-231 (GetSkillResult `files`, `content_hash`), :276; tests/mcp/test_tool_descriptions.py:11

**What is wrong.** get_skill returns every file's path, sha256 and executable bit, which its own description says 'need no checking'. list_skills has no filter, and instead of narrowing it raises Claude Code's 50,000-character result cap to 500,000. The `sync` description is 2,047 of 2,048 characters and `get_skill` 2,033, so the next wording fix to either fails the test.

**How it was confirmed.** get_skill_size.py (my folder): a 100-file skill's get_skill result is 14,178 characters, 13,651 of them (96%) `files` plus `content_hash`. perf_state.py: list_skills for a user in 15 teams returns 86,572 characters (640 entries). desc_len.py measures every description: sync 2047, get_skill 2033, push_skill 1779.

**Proposed fix.** Drop `files` and `content_hash` from the get_skill result, or replace them with `file_count`, and edit DESIGN §4's get_skill line. Use the freed room in the description. Add optional `team` and `query` (substring of name or description) arguments to list_skills, server and local. Give the description test a soft margin (e.g. fail above 1,950) so there is room to fix wording.

**Done when.** get_skill for a 100-file skill returns under 1 KB, list_skills(team='aistack') returns only that team's skills, and the sync description has at least 100 characters of headroom.

### IMP-13: 'Try it in two minutes' dead-ends after five minutes, and the contributor test instructions skip the browser tests

**Confirmed.** Severity **Low**, effort **S**. Hurts: A newcomer evaluating the product from a checkout, and a new contributor

**Where.** README.md:36-43 and :234-246; scripts/demo_seed.py:91-93 and :147-155; tests/ui/conftest.py:47-50

**What is wrong.** demo_seed prints three one-use sign-in links that expire in five minutes and keeps no machine token, so once they lapse there is no way to get a new link without an agent. Rerunning the seed fails with a traceback, because the users exist and ./aistack.db persists across restarts. The only way back is deleting the database. README 'Tests' never mentions `poetry run playwright install chromium`, so `poetry run pytest` silently skips the 38 browser tests (the skip reason shows only with -rs).

**How it was confirmed.** Ran `poetry run python -I scripts/demo_seed.py http://127.0.0.1:8210 <code>` twice against my server. The second run ends in `fastmcp.exceptions.ToolError: Username 'dimitris' is already taken…`. Read README.md:234-246 and the skip in tests/ui/conftest.py.

**Proposed fix.** Have demo_seed write the three machine tokens to a gitignored file (e.g. `.aistack-demo.json`) and add `scripts/demo_seed.py --links <url>`, which only calls open_dashboard for each. When join answers 'already taken', print 'This server was seeded already: run with --links.' Add the Playwright install line and `-rs` to README 'Tests'.

**Done when.** After a seeded server's links expire, `demo_seed.py --links` prints three working links, and README 'Tests' run on a clean checkout reports no skipped browser tests.

### IMP-14: README has drifted: ADR list, size claims, a stale known limit, a built roadmap item, and old screenshots

**Confirmed.** Severity **Low**, effort **S**. Hurts: Readers evaluating the project, who are told things that are no longer true

**Where.** README.md:360-380, :209, :343, :332, :322, :324; docs/images/*.png

**What is wrong.** (1) The ADR list jumps from 0019 to 0021 and stops there: 0020, 0022, 0023, 0024 and 0025 are missing. (2) 'About 5,800 lines of Python and 6,900 of tests' against 8,974 and 10,213 actual lines (6,941 and 7,344 without blanks and comments). (3) The known limit says 'Add my other computer returns a Claude Code command… Codex… not connected that way yet', but add_machine returns `codex_config` (tools/onboarding.py:94-118), as README:293 itself says. (4) Roadmap item 1 ('a page per skills folder, and agents in the Add to… dialog') is built and tested (tests/ui/test_dashboard_page.py:153, :178). (5) The comparison table says 'Works beyond Claude Code: Planned next' and :324 calls a second harness 'the first thing on the roadmap'. (6) The screenshots predate full names: the account bar shows 'dimitris · 2 computers' where the page now shows 'Dimitris Christopoulos / dimitris'.

**How it was confirmed.** Read README. Line counts with `find src tests -name '*.py' | xargs cat | wc -l`, plus a blank-and-comment-free count. Read onboarding.py's AddMachineResult. Compared docs/images/dashboard-library.png with the screenshot library-desktop-light.png.

**Proposed fix.** Edit the five passages and rerun scripts/retake_screenshots.py. Add a test that every docs/adr/*.md is linked from README's Documentation list.

**Done when.** The new ADR-link test passes, and README no longer says Codex is planned or that add_machine returns only a Claude Code command.

Related: [IMP-10](#imp-10-designmd-the-document-that-wins-on-conflict-contradicts-the-code-in-a-dozen-places), [PH-17](plot-holes.md#ph-17-design-operating-and-context-describe-a-server-that-has-since-changed).

### IMP-15: One team update is offered once per folder, and again on every sync after it was declined

**Confirmed.** Severity **Low**, effort **S**. Hurts: A member with a taken skill in both Claude Code's folder and ~/.agents/skills, or one who declines an update

**Where.** src/aistack/services/sync_service.py:165-166; src/aistack/bundled/skills/sync-aistack/SKILL.md:80

**What is wrong.** `_team_updates` is computed per harness call from the skills enabled in that folder, so one 'sync aistack' over both folders reports the same offer twice and the agent may ask twice. The sync skill also says to ask again on every sync about an offer the user declined, with no way to skip one revision.

**How it was confirmed.** offer_twice.py (my folder): a team skill taken into claude_code and also enabled in agents. After the admin pushes r2, the claude_code sync reports [('twice', 1, 2)] and the agents sync reports [('twice', 1, 2)].

**Proposed fix.** Cheap now: tell the agent in both sync-aistack skills to ask once per skill name across folders, and that taking it in one folder updates the other at its sync. Later: a per-skill 'skip this revision' (e.g. `skill.declined_source_revision` on the personal copy), offered again only for a newer team revision. That amends ADR-0015's 'decides each time', so it needs a new ADR.

**Done when.** A headless or scripted run of the sync skill over both folders asks once. With the later change, a declined r2 is not offered again but r3 is.

### IMP-16: A skill that can never be backed up is listed under backup on every sync

**Confirmed.** Severity **Low**, effort **S**. Hurts: Anyone with a skill holding an image or more than 100 files: every sync costs a refused push and an error line in the agent's log

**Where.** src/aistack/services/sync_service.py:163-164; src/aistack/mcp/tools/local.py:216-234; README.md:310

**What is wrong.** README accepts this as a limit, but the cost recurs on every sync forever, and local mode could avoid it cheaply because its sync already reads the folder. Each refused push also makes the local server print "Error calling tool 'push_skill'" to the agent's stderr, for an expected refusal.

**How it was confirmed.** binary_backup.py (my folder) drives local mode over stdio with a skill holding logo.png: sync 1 gives backup=['logo-maker'] and push refused ''logo.png' is not UTF-8 text…'; sync 2 gives the same backup and the same refusal. The ERROR line appeared on the process's stderr.

**Proposed fix.** In local mode, run the pure push validation (skill_archive and skill_validation) on each backup candidate during sync and report failures in a new `cannot_back_up: [{name, reason}]` field instead of `backup`. On a server, pre-check what the digests reveal (more than 100 files, .env files, invalid paths, no SKILL.md). Tell the agent in the description to mention these once.

**Done when.** binary_backup.py shows logo-maker under cannot_back_up with its reason and makes no push call.

### IMP-17: No static check guards the Python or the page's 1,876-line script, and the page ships an untested 200-line fake backend

**Confirmed.** Severity **Low**, effort **S**. Hurts: Maintainers: the code is clean today with nothing keeping it that way, and demo mode duplicates the API's rules in JavaScript

**Where.** pyproject.toml [dependency-groups] (no linter, though .gitignore lists .ruff_cache and .mypy_cache); .github/workflows/tests.yaml (no lint step); src/aistack/bundled/dashboard.html:2531-2732 (demo mode, DEMO_ROUTES)

**What is wrong.** A JavaScript ReferenceError in a rarely visited view is caught only if a browser test both visits it and checks console errors (see IMP-04). Demo mode is entered with `?demo` or by opening the file from disk. It re-implements share, remove, place and the team actions in JavaScript and lacks state fields the real API sends (server, library, invites). It is undocumented, and the UI tests state 'no demo mode'.

**How it was confirmed.** `ruff check --isolated --select F,E9,B,ASYNC src scripts`: 0 findings in src, 2 ASYNC240 in scripts/container_smoke.py. Extracted the page's scripts to my folder's js/: `node --check` passes and ESLint 9 (no-undef, no-unused-vars) reports 0 errors and 9 warnings, all unused catch variables. demo_mode.py opened the file from disk in Chromium and visited 8 screens with no page errors; the Storage page shows 'Server' with an empty host.

**Proposed fix.** Add ruff (select F, E9, B, I) to the dev group and a CI step. Add a CI step that extracts the inline scripts and runs `node --check` (no npm needed) or ESLint with no-undef. Either delete demo mode (README's screenshots already come from a real seeded server) or add one browser test that opens the page from disk and visits each screen.

**Done when.** CI fails on an unused import in src or an undefined identifier in dashboard.html, and demo mode is either gone or covered by a test.

Related: [UI-22](ui.md#ui-22-no-icon-is-declared-so-every-page-load-asks-for-faviconico-gets-404-and-the-browser-tests-fail-in-a-full-browser).

### IMP-18: Most of the server log is MCP SDK chatter

**Confirmed.** Severity **Low**, effort **S**. Hurts: The operator reading logs

**Where.** src/aistack/bootstrap/__main__.py:36-43 (WIRE_LOGGERS floored at INFO)

**What is wrong.** Every tool call adds 'Processing request of type CallToolRequest' (mcp.server.lowlevel.server) and 'Terminating session: None' (mcp.server.streamable_http) at INFO, two lines per call around AIStack's own one-line record, which buries it.

**How it was confirmed.** After my probes, my server.log had 2,024 of 3,302 lines (61%) matching those two messages (`grep -c`).

**Proposed fix.** Floor `mcp.server.lowlevel.server` and `mcp.server.streamable_http` at WARNING in configure_logging. That keeps AGENTS.md's guarantee: the floor only rises, and nothing is removed from WIRE_LOGGERS. Add a test of the configured levels.

**Done when.** A sync on a fresh server writes one log line, AIStack's own, and the logging test asserts both loggers sit at WARNING or above.

Related: [STD-10](industry-standards.md#std-10-changes-made-on-the-dashboard-leave-no-log-line-shares-groups-group-privacy-takes-and-placements), [STD-11](industry-standards.md#std-11-the-server-log-mixes-two-formats-and-fastmcps-multi-line-rich-lines-ignore-aistack_log_level), [STD-19](industry-standards.md#std-19-the-log-is-the-only-way-to-observe-a-server-no-metrics-no-request-ids-no-version).

## Checked and holding up

- Sync performance on the server: a first sync reporting 300 unknown skills took 81 ms; a steady sync of 300 current skills took 50-57 ms, a constant few queries (perf_sync.py)
- Push throughput: 300 sequential push_skill + PUT took 6.0 s at 19 ms median; list_skills is always 5 SQL statements
- Local mode: 50 pushes into a SQLite Library took 1.0 s, into a git-backed Library 3.8 s; steady sync of 50 skills took 57-96 ms
- /api/state for a user with 300 skills and no teams: 33 ms and 11 statements (the cost is per team and per member, see IMP-07)
- Non-browser suite: 996 passed, 7 skipped, 94% line coverage of src/aistack; sync_service, skill_validation, transfer_ticket, skill_archive and library_log are at 97-99%
- Every dashboard route is listed in DESIGN.md's route table (an existing test enforces it)
- Every tool description is within the 2,048-character limit, on the server and in local mode
- Making an existing group private does hide it and its skills from non-members in /api/state and list_skills; the move and group-privacy routes answer ok (only untested, see IMP-04)
- add_machine returns both the Claude Code command and the Codex config.toml block
- Python is clean under ruff F/E9/B/ASYNC in src/, and the page's script passes node --check and ESLint no-undef
- Demo mode renders all 8 screens from disk without page errors
- self_update only upgrades uv tool installs and never a checkout or the container
- Setup runs from the git source with uvx today (exit 0) despite the missing PyPI release
- The repository was left unchanged (git status clean). My server on port 8210 was stopped by PID, and the demo server on 8000 stayed healthy throughout
