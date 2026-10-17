# Plan

The audit's work as pull-request-sized steps, highest value and risk first. Work through it top to bottom: one step is one branch and one PR, shipped with the `ship-a-change` skill. Each step names the findings it closes (linked), the files it touches, the ADR it needs (drafts are in `docs/adr/`, status proposed), and its tests. A step marked **trust boundary** gets AGENTS.md's diff review and the PostgreSQL half before it merges.

Before starting a step, reproduce its High and Critical findings: only the authorization and UX findings had an independent second pass (see README.md).

## Start here

What changed since the audit was written (2026-10-15):

- The audit merged as #118.
- The owner set up PyPI trusted publishing for `aistack-mcp` (workflow `tests.yaml`, environment `pypi`). The name is claimed only when the first upload lands, which is when the owner pushes the `v0.1.0` tag. Check `https://pypi.org/pypi/aistack-mcp/json` before step 1: once it answers, step 1 is only the Windows gate and the install-sentence test.
- Versions follow the rule now in AGENTS.md: never 1.0.0, a pull request never changes `version`, the owner cuts releases. `tests/test_release_version.py` holds it.

A cloud development environment is ready when it starts: `.claude/hooks/session-start.sh` runs `poetry install`, starts PostgreSQL 16 on port 5433 when the image has it and sets `TEST_DATABASE_URL`, and points Playwright at the image's Chromium with `PLAYWRIGHT_BROWSERS_PATH`. On your own computer, follow README "Tests" instead.

The browser tests pass in that full Chromium: [UI-22](ui.md#ui-22-no-icon-is-declared-so-every-page-load-asks-for-faviconico-gets-404-and-the-browser-tests-fail-in-a-full-browser) (a missing favicon) was fixed ahead of step 36.

How to work through it:

- Take the first unticked step below. Read its findings in full and reproduce the High and Critical ones: the reproduction is described in each.
- One step is one branch from `main` and one PR, shipped with the `ship-a-change` skill. Steps 4 to 11, 18, 19, and the project steps marked **trust boundary** get its extra checks.
- Tick the step here in the same PR, with the PR's number: `- [x] 4. … (#123)`.
- A step that needs an ADR moves its draft from proposed to accepted in the same PR, once the code agrees with it.
- If a step turns out wrong or bigger than one PR, split or rewrite it here first, then work.
- A finding that turns out false: say so under it, with what you ran, and move on.

### Progress

- [x] 1. Claim and publish `aistack-mcp`, and make every install sentence resolve (#129)
- [x] 2. Bump PyJWT and pin the build (#133)
- [x] 3. Make local setup's agent commands work and stop printing secrets (#134)
- [x] 4. An invite dies with its maker's right to invite (#126)
- [x] 5. Lock the team while its admins and members change (#132)
- [x] 6. A team can always be managed: delete a team, let a lone admin leave, repair an orphaned one (#147)
- [x] 6b. A mistyped group can be renamed or deleted (#165)
- [x] 7. Sharing over a group's skill takes being able to share into that group (#149)
- [x] 8. A session belongs to the computer that opened it; signing out ends it (#127)
- [x] 9. A person can remove and rename their own computers, and see when each last synced (#140)
- [x] 9b. Read a computer's removal and rename in local mode (#154)
- [ ] 9c. Remove and rename a computer in local mode (after a release that carries 9b)
- [x] 10. Taking a team skill never silently replaces an unrelated skill of yours (#150)
- [x] 11. Throttle failed credentials and keep caller text out of the log (#142)
- [x] 12a. Backups that restore, and a snapshot before every upgrade (#141)
- [x] 12b. Operator tasks are `aistack admin` commands, not Python copied from Markdown (#162)
- [x] 12c. The operator renames a user, and join says a team may hold the name (#166)
- [x] 13. Scope the 'latest revision' queries and batch the dashboard's team queries (#151)
- [x] 14. Reads that change nothing stop taking SQLite's write lock (#143)
- [x] 15. Answer every conflict and limit with a sentence (#155)
- [x] 16. Fix the layouts that break at tablet width and with long names (#139)
- [x] 17. Versions, a changelog, and a channel to stay on (#145)
- [x] 18a. The schema test sees every constraint, and constraints have one name (#125)
- [x] 18b. Index what the services look up by; order and times alike on both databases (#131)
- [x] 18c. Write down what 'compatible' means and enforce it (#135)
- [x] 19. Order the local log so a fast clock cannot win, and rebuild without holding the lock (#128)
- [x] 20. Every terminal command finds the agent's Library (#130)
- [x] 20b. Moving a Library is one command that keeps history (#137)
- [x] 20c. Say when GitHub cannot be reached, and nudge a Library kept on this computer only (#146)
- [x] 20d. A moved Library tells the computers still on the old place: the reader (#163)
- [ ] 20e. `aistack move` records where the Library went (after a release that carries 20d)
- [x] 21. A restored home folder is a new computer (#148)
- [ ] 21b. A server notices a machine token copied to another computer
- [x] 22. A second computer gets the sync skill and the session-start hook, whatever its agent (#157)
- [ ] 22b. Adding a computer on a server is one paste, with no token carried between computers
- [x] 23. Setup can be run again, and a stopped setup can finish (#167)
- [x] 24. Record the decision: ADR-0026 and the glossary (#152)
- [x] 25. Identify a project from its remote or its path (#153)
- [x] 26. Add the project tables (one compatible migration) (#156)
- [x] 27. Project placements in the services, and a removed skill wanted nowhere (#159)
- [x] 28. Replay project events before anything records them (bridge release) (#160)
- [x] 29. Sync a project folder (#168)
- [x] 30. Server-mode tools take a project (#169)
- [x] 31. Teach the server's sync-aistack skill the project steps (#170)
- [ ] 32. Local mode: git-hardened project folders
- [x] 33. Dashboard API for project folders, on a server (#171)
- [x] 34. Dashboard page: projects in the computer tree (#172)
- [x] 35. Keyboard and screen reader (#161)
- [x] 36. The pages before sign-in, the icon, and local mode's remembered choices (#173)
- [x] 37. Shorter text, and words that say what is true
- [x] 38. Bring DESIGN.md, OPERATING.md and the README back in line with the code (#158)
- [x] 39. See what changed before taking an update, and get an older revision back (6b65ccd)
- [ ] 39b. Restore an older revision, and bring back a removed skill, in local mode (a reader release, then a writer a week later)
- [x] 40. Sync reports what is true: nested .git, unsubscribed groups, removed skills, skills that cannot be backed up (06269bf)
- [x] 40b. Fewer calls per sync: one push for many skills, a listing that narrows, room in the descriptions (f91a3ae)
- [ ] 40d. Sync without copying digests or running seven commands per skill (trust boundary; get_skill's smaller result waits for a minor release)
- [x] 40c. A session start that stays quiet when nothing changed (f43f3b1)
- [x] 41. One log: a line for every change, one format, no SDK chatter (14907f9)
- [x] 41d. Download your Library, and the headers an https server sends (d29e8e4)
- [ ] 41e. The page's words in one table
- [x] 41b. The operator can forget a person (d6efb33)
- [x] 41c. Metrics for the operator, behind a token (f5e9ff3)
- [x] 42. Tests and checks the code is missing (1a1109a)
- [x] 43. Finish the security pass this audit could not (0986ae4)

Session notes:
- 2026-10-17: main was red because the pytest job ran past its 25 minutes with Chromium inside it; the browser tests now run in the `browsers` matrix beside it (32c6ccb).
- 2026-10-17: 41b done (d6efb33): `aistack admin forget`, pseudonym `former-member-<4 hex>`, prefix reserved at join and rename; ADR-0034 accepted.
- Next: 41e (the page's words in one table), then Dependabot #136 and #138, the rest of the CI split, the test strategy, 40d.
- Blocked: nothing. Check the CI runs for 32c6ccb and d6efb33 at the start of the next session.

## Unblock newcomers and the supply chain

Nothing else matters if the first sentence of the README fails, and the publishing jobs are the one place an outsider could ship code to every user.

### 1. Claim and publish `aistack-mcp`, and make every install sentence resolve

Closes: [LH-01](plot-holes.md#lh-01-local-mode-cannot-be-installed-aistack-mcp-is-not-on-pypi-and-no-release-has-ever-been-tagged), [STD-02](industry-standards.md#std-02-the-pypi-name-every-setup-sentence-runs-aistack-mcp-is-unregistered-and-anyone-can-take-it), [UX-10](ux.md#ux-10-the-dashboard-and-the-local-sync-skill-hand-out-uvx-aistack-mcp-setup-and-uv-tool-install-aistack-mcp-which-fail-today), [IMP-05](improvements.md#imp-05-setup-can-run-from-github-today-but-the-steps-it-prints-still-install-from-pypi-follows-from-the-known-missing-release), [AUTO-19](automation.md#auto-19-every-way-to-set-up-another-computer-in-local-mode-and-the-self-updater-depend-on-pypi), [IMP-01](improvements.md#imp-01-the-windows-job-gates-neither-merging-nor-publishing-and-local-mode-then-updates-itself-from-pypi).
Largest effort among them: S.

Until the tag is pushed, the sentences use `uvx --from git+https://github.com/dchristopoulos/AIStack aistack-mcp`, which IMP-05 found works today.

Files: .github/workflows/tests.yaml (add `windows` to the `needs:` of `publish` and `pypi`); README.md; src/aistack/bundled/local/setup.md; src/aistack/bundled/local/sync-aistack/SKILL.md; src/aistack/bundled/dashboard.html (`ADD_COMPUTER`, `STORAGE[...].say`).

ADR: none needed.

Tests: A test that collects every `uvx …`/`uv tool install …` sentence in `bundled/**` and the page and asserts they use one constant; a CI job that runs that command in a clean container after publishing. The owner pushes the `v0.1.0` tag: that is the one step a session cannot do. If PyPI already answers for `aistack-mcp`, drop the `git+` fallback below.

Outcome: the owner tagged `v0.1.0` and `aistack-mcp` 0.1.0 is on PyPI with this repository as its homepage, so the `git+` fallback was never needed. The sentences come from `RUN_COMMAND` and `INSTALL_COMMAND` in `aistack.bundled`. The container job runs `uvx aistack-mcp setup` from PyPI on an empty home folder and checks that the PyPI project still names this repository, and the `pypi` job runs setup from the index after each upload. Left to the owner: make `windows` a required check on `main`, then add it to the ship-a-change skill's list. Moved: IMP-01's macOS job to step 42.

### 2. Bump PyJWT and pin the build

Closes: [STD-07](industry-standards.md#std-07-nothing-scans-or-updates-dependencies-and-the-shipped-lock-pins-pyjwt-2130-which-has-14-published-advisories), [PUSH-01](security.md#push-01-the-jobs-that-hold-publishing-credentials-run-third-party-actions-by-moving-tags-and-an-unpinned-poetry), [STD-17](industry-standards.md#std-17-images-are-unsigned-and-carry-no-sbom-the-base-image-is-unpinned-and-rebuilt-only-on-commits-and-there-is-no-security-policy).
Largest effort among them: S.

Files: pyproject.toml, poetry.lock (pyjwt ≥ 2.15.1); .github/workflows/tests.yaml (every `uses:` by SHA, top-level `permissions: contents: read`, Poetry pinned); .github/dependabot.yml (new); Dockerfile (base image by digest).

ADR: none needed.

Tests: Full suite on SQLite and PostgreSQL; the container job; a test that fails when a workflow `uses:` is not a 40-character SHA.

Outcome: PyJWT is at 2.15.1, and the pytest job runs `pip-audit` over every locked package, so a known advisory fails the build. Every action is pinned by commit, the workflow's token reads the repository and nothing else by default, Poetry is pinned to the Dockerfile's 2.4.1, and the base image is pinned by digest. Dependabot proposes Python, action and base-image updates weekly, with fastmcp left alone. The image carries an SBOM and provenance and is signed with Sigstore, and a weekly scheduled build takes in base-image fixes. SECURITY.md already existed. Moved: STD-07's Trivy scan of the image to step 42, because a scanner that fails on unfixed base-image CVEs would block every merge until Debian ships the fix.

### 3. Make local setup's agent commands work and stop printing secrets

Closes: [AUTO-01](automation.md#auto-01-local-setups-claude-mcp-add-fails-as-written-for-the-github-and-postgresql-choices), [AUTO-04](automation.md#auto-04-setup-and-both-sync-skills-run-claude-mcp-get-aistack-which-prints-the-machine-token-or-the-database-password-in-full), [AUTO-12](automation.md#auto-12-local-setup-makes-the-agent-hand-assemble-five-config-edits-the-installed-program-could-make-itself), [AUTO-23](automation.md#auto-23-an-agents-configuration-is-written-once-at-setup-and-never-updated-though-later-releases-changed-it).
Largest effort among them: M.

Files: src/aistack/bundled/local/setup.md; src/aistack/bundled/setup-aistack.md; both sync-aistack skills; src/aistack/bootstrap/__main__.py (`aistack connect claude|codex`, optional).

ADR: none needed.

Tests: A static test that every `claude mcp add` line in `bundled/**` names the server before `-e`/`-H`; a test that no bundled text runs `claude mcp get` or `codex mcp get` without a filter; `connect` writes the same config twice idempotently.

Outcome: `aistack connect claude-code|codex [--hook]` replaces local setup's steps 5 to 7. It runs the check, writes the sync skill, connects the agent by the installed program's full path with the name before `-e`, and merges the session-start hook; a second run changes nothing, and a settings file that is not valid JSON or TOML is left alone. `check --agent` and `export --agent` read the Library's place from the agent's own config without showing it, which is how the local sync skill troubleshoots and moves a Library now. Nothing bundled runs `mcp get` any more: Claude Code checks with `claude mcp list` and Codex with a `grep -c` on its config. Both sync skills count Codex's approvals without printing the connection and bring them up to date (AUTO-23). AUTO-01 and AUTO-04 were reproduced with Claude Code 2.1.300 in a scratch home before the change.

## Close the trust-boundary holes

Each of these lets someone keep or gain access the product says they do not have, or lets a team end in a state nobody can repair. Every step here is a trust-boundary change: AGENTS.md's diff review and the PostgreSQL half apply.

### 4. An invite dies with its maker's right to invite

Closes: [AUTHZ-01](security.md#authz-01-removing-demoting-or-offboarding-an-inviter-leaves-their-invite-links-working-so-the-person-can-rejoin-the-team-or-create-a-new-account-on-the-server), [PH-02](plot-holes.md#ph-02-invites-outlive-the-person-who-made-them-so-removed-members-and-people-taken-off-the-server-keep-letting-new-accounts-in), [DB-06](schema.md#db-06-a-team-invite-outlives-its-makers-right-to-invite-offboarding-by-deleting-machines-removal-from-the-team-and-revoking-can_invite-all-leave-it-working), [SEC-07](security.md#sec-07-a-used-team-invite-code-still-authenticates-as-a-bearer-so-used-and-unknown-codes-answer-differently), [SEC-06](security.md#sec-06-on-postgresql-an-admins-cancel-can-report-success-while-the-person-it-was-meant-to-stop-joins), [ENT-09](concurrency-and-reliability.md#ent-09-an-admin-is-told-an-invite-was-cancelled-while-the-same-invite-admits-its-holder).
Largest effort among them: S. **Trust boundary.**

Files: src/aistack/services/team_service.py (`invited_to`, `is_open_invite`, `_drop_member`, `set_member`, `cancel_invite` as a conditional update); src/aistack/mcp/auth/aistack_token_verifier.py; docs/OPERATING.md ('Someone left').

ADR: none needed.

Tests: tests/services/test_teams.py: a removed member's, a demoted admin's and an offboarded user's invites admit nobody; a used code is not a bearer (`tools/list` answers 401); on PostgreSQL, cancel and use at a `threading.Barrier` give exactly one winner and the cancel reports truthfully.

### 5. Lock the team while its admins and members change

Closes: [ENT-01](concurrency-and-reliability.md#ent-01-two-admins-acting-at-once-on-postgresql-leave-a-team-with-no-admin), [DB-05](schema.md#db-05-teams-can-be-left-with-no-admin-or-no-members-on-postgresql-the-last-admin-check-is-a-racy-count), [AUTHZ-04](security.md#authz-04-the-team-keeps-an-admin-check-counts-first-and-writes-later-without-a-lock-on-postgresql-two-simultaneous-leaves-or-demotions-leave-a-team-with-no-admin), [ENT-02](concurrency-and-reliability.md#ent-02-a-member-removed-while-being-added-to-a-private-group-keeps-the-group-and-regains-it-on-rejoining), [ENT-07](concurrency-and-reliability.md#ent-07-on-postgresql-concurrent-deletes-and-duplicate-inserts-surface-as-500s-misleading-sentences-or-a-false-success), [ENT-08](concurrency-and-reliability.md#ent-08-a-push-that-lands-during-remove-from-library-leaves-the-skill-hidden-from-the-library-but-enabled-and-kept-current-on-a-computer).
Largest effort among them: M. **Trust boundary.**

Files: src/aistack/services/team_service.py (`_lock_team` with `SELECT … FOR UPDATE`; delete `TeamMember` before group rows); src/aistack/services/skill_service.py (lock the team skill row in share/take/move/remove; unique violations become `Conflict`).

ADR: none needed.

Tests: tests/db/test_last_admin_race_postgres.py and a group-membership race test, each watched failing with the lock removed; concurrent duplicate creates answer 409 with a sentence, never 500.

### 6. A team can always be managed: delete a team, let a lone admin leave, repair an orphaned one

Closes: [AUTHZ-V01](security.md#authz-v01-offboarding-a-teams-only-admin-as-docsoperatingmd-says-leaves-the-team-with-an-admin-nobody-can-reach-and-no-way-to-name-a-new-one), [DB-07](schema.md#db-07-offboarding-a-teams-only-admin-leaves-the-team-permanently-unmanaged-and-no-operator-script-exists-to-repair-it), [PH-05](plot-holes.md#ph-05-taking-a-teams-only-admin-off-the-server-leaves-the-team-with-nobody-who-can-manage-it-and-operating-has-no-fix), [AUTO-13](automation.md#auto-13-the-documented-offboarding-leaves-a-team-whose-only-admin-left-with-no-admin-anyone-can-reach), [AUTHZ-05](security.md#authz-05-the-only-member-of-a-team-can-never-leave-it-and-no-team-can-be-deleted-the-pages-own-demo-lets-them), [PH-04](plot-holes.md#ph-04-a-team-or-group-can-never-be-deleted-or-renamed-a-lone-admin-can-never-leave-team-names-take-usernames-for-good), [UX-03](ux.md#ux-03-a-team-made-by-mistake-can-never-be-removed-its-only-member-cannot-leave-and-nothing-deletes-or-renames-a-team-or-group), [PH-12](plot-holes.md#ph-12-an-admin-outside-a-private-group-sees-it-as-empty-gets-a-subscribe-switch-that-fails-and-can-remove-skills-by-name-they-cannot-see).
Largest effort among them: M. **Trust boundary.**

Files: src/aistack/services/team_service.py (`delete_team`, last-member leave deletes); src/aistack/api/dashboard.py, dashboard.html (Delete team in Team settings); docs/OPERATING.md (script: name a new admin).

ADR: [ADR-0028 (draft)](../../adr/0028-a-team-can-be-deleted.md): A team can be deleted, and nobody is kept in one.

PH-04's group half, deleting and renaming a group, is step 6b.

PH-12's service half lands here: an admin's move or remove of a skill in a private group they are not in answers like a missing skill. Its page half, showing such a group as not joined instead of empty, moves to step 37.

Tests: Service tests: the last member leaving deletes the team and frees its name; an admin deletes a team and members' Library copies stay; the operator script names an admin. A UI test deletes a team by the button's words.

### 6b. A mistyped group can be renamed or deleted

Closes: the group half of [PH-04](plot-holes.md#ph-04-a-team-or-group-can-never-be-deleted-or-renamed-a-lone-admin-can-never-leave-team-names-take-usernames-for-good) and of [UX-03](ux.md#ux-03-a-team-made-by-mistake-can-never-be-removed-its-only-member-cannot-leave-and-nothing-deletes-or-renames-a-team-or-group). Step 6 deleted teams; nothing yet deletes or renames a group.
Largest effort among them: M. **Trust boundary** (it deletes, and a group's path decides who sees its skills).

Files: src/aistack/services/team_service.py (`rename_group`: admin only, rewrites the path of the group and every group under it in one transaction, refused when the new path is taken; `delete_group`: admin only, and only an empty group, with no skills and no groups under it); src/aistack/api/dashboard.py (`/teams/{team}/group/rename`, `/teams/{team}/group/delete`, `local=False`); dashboard.html (Rename and Delete on a group's page); docs/DESIGN.md (the route table).

ADR: none needed. The audit proposed moving a deleted group's skills one level up, but a private group's skills would then reach people it kept them from, so a group with skills is refused with a sentence that says to move or remove them first. A mistyped group is empty.

Tests: Service tests: an admin renames a group with subgroups and every path follows, and its skills and members stay; a rename onto a taken path changes nothing; an empty group is deleted, and one with a skill or a subgroup is refused and kept; a member who is not an admin is refused. An admin already sees and manages every group, private ones too (`team_service.groups`), so a rename or delete by one reveals nothing new. A UI test renames and deletes a group by the buttons' words.

### 7. Sharing over a group's skill takes being able to share into that group

Closes: [AUTHZ-02](security.md#authz-02-a-member-who-can-only-see-a-group-an-open-groups-non-member-or-a-sees-all-groups-member-can-push-a-new-revision-into-that-groups-skill-by-sharing-without-a-group), [AUTHZ-03](security.md#authz-03-the-team-member-list-leaks-private-group-names-through-the-paths-of-open-subgroups-under-them), [AUTHZ-07](security.md#authz-07-a-private-group-that-exists-answers-slower-than-one-that-does-not-so-a-member-can-probe-private-group-names-by-timing), [AUTHZ-08](security.md#authz-08-outsider_view-checks-only-that-each-tool-has-a-label-most-labels-are-never-exercised-and-there-is-no-matrix-for-a-member-who-sees-but-cannot-write-or-cannot-see-a-private-group).
Largest effort among them: M. **Trust boundary.**

Files: src/aistack/services/skill_service.py (`share` checks `GroupAccess.writable` for the existing skill's group); src/aistack/services/team_service.py (`members` shows a private group's subgroups only to those who see it); tests/mcp/test_teams_over_http.py (OUTSIDER_VIEW exercised, plus a reader-not-writer matrix).

ADR: [ADR-0029 (draft)](../../adr/0029-sharing-over-a-groups-skill.md): Sharing over a group's skill takes being able to share into the group (resolves ADR-0015's two sentences that disagree).

Tests: A sees-all member and an open-group non-member are refused with the same sentence as an unknown group; the member list hides private ancestors; the matrix fails when a tool is added without its row.

### 8. A session belongs to the computer that opened it; signing out ends it

Closes: [SEC-01](security.md#sec-01-a-stolen-machine-token-outlives-the-documented-revocation-sibling-tokens-dashboard-sessions-and-upload-urls-keep-working), [SEC-05](security.md#sec-05-signing-out-does-not-end-the-session-a-copied-cookie-keeps-working-for-the-rest-of-its-8-hours), [STD-03](industry-standards.md#std-03-a-dashboard-session-cannot-be-ended-not-by-signing-out-and-not-by-deleting-the-machine-that-opened-it), [SEC-10](security.md#sec-10-a-sign-in-link-silently-replaces-the-browsers-existing-session-login-csrf).
Largest effort among them: M. **Trust boundary.**

Files: src/aistack/services/transfer_ticket.py (`mid` and token-hash claims; a revoked-session set until expiry); src/aistack/api/dashboard.py (`sign_out` revokes; a link opened in a signed-in browser asks before switching); src/aistack/services/dashboard_service.py (`require_a_machine` → the opening machine); docs/OPERATING.md (lost laptop runbook).

ADR: [ADR-0027 (draft)](../../adr/0027-a-session-belongs-to-the-computer-that-opened-it.md): A dashboard session belongs to the computer that opened it, and its owner can remove that computer.

Tests: After rotating machine A, A's session gets 401 and A's upload URL 403; after sign-out the old cookie gets 401; a second link in a signed-in browser does not silently replace the session.

### 9. A person can remove and rename their own computers, and see when each last synced

Closes: [AUTO-02](automation.md#auto-02-on-a-server-a-person-cannot-cut-off-their-own-lost-or-stolen-computer), [STD-04](industry-standards.md#std-04-a-person-cannot-see-when-each-computer-last-connected-or-remove-a-lost-one-and-a-stolen-tokens-push-lands-silently-on-their-other-computers), [PH-13](plot-holes.md#ph-13-owners-cannot-rename-or-remove-a-computer-and-nothing-shows-when-a-computer-last-synced), [IMP-09](improvements.md#imp-09-a-person-cannot-retire-revoke-or-rename-their-own-computer-only-the-operator-can), [IMP-06](improvements.md#imp-06-the-dashboard-cannot-say-when-a-computer-last-synced-or-which-revision-it-holds), [AUTO-20](automation.md#auto-20-computers-cant-be-renamed-or-removed-and-a-reinstall-leaves-vm-and-vm-2-forever).
Largest effort among them: M. **Trust boundary.**

Files: src/aistack/services/onboarding_service.py (`remove_machine`, `rename_machine`); src/aistack/api/dashboard.py (`/machines/{id}/remove`, `/rename`); src/aistack/services/dashboard_service.py (`last_synced_on` per harness); dashboard.html (computer page); library_log.py (a `machine_removed` kind, replayed one release before it is recorded).

ADR: [ADR-0027 (draft)](../../adr/0027-a-session-belongs-to-the-computer-that-opened-it.md).

Tests: Removing one's own machine makes its token 401 on /mcp; another user's id answers like an unknown one; the last computer cannot be removed; a UI test removes a computer by the button's words.

Split (step 9 was bigger than one PR): step 9 is the server, with the routes registered `local=False`, plus the `machine.added_by_machine_id` migration. Local mode moved to step 9b, because it is a new log kind with its own release order.

### 9b. Read a computer's removal and rename in local mode

Closes: the replay half of the local-mode part of [AUTO-20](automation.md#auto-20-computers-cant-be-renamed-or-removed-and-a-reinstall-leaves-vm-and-vm-2-forever) and [AUTO-02](automation.md#auto-02-on-a-server-a-person-cannot-cut-off-their-own-lost-or-stolen-computer).
Largest effort among them: S.

The first of two releases, per ADR-0024: replay `machine_removed` and `machine_renamed`, and record neither. A later change from a computer that was removed (it may still be running offline) brings it back, so replay never stops and nothing the person did is lost (ADR-0033).

Files: src/aistack/services/library_log.py (the two kinds).

ADR: [ADR-0033](../../adr/0033-a-removed-computer-comes-back-when-it-changes-something.md).

Tests: the log-replay property test covers both kinds; a rename on one computer reaches a second; an event from a removed computer brings it back; two computers that removed or renamed each other offline still replay.

### 9c. Remove and rename a computer in local mode

Closes: the rest of the local-mode part of [AUTO-20](automation.md#auto-20-computers-cant-be-renamed-or-removed-and-a-reinstall-leaves-vm-and-vm-2-forever) and [AUTO-02](automation.md#auto-02-on-a-server-a-person-cannot-cut-off-their-own-lost-or-stolen-computer).
Largest effort among them: S.

Only after a release that carries step 9b, so every computer that reads these events knows them (ADR-0024). Register step 9's two routes on the localhost dashboard and record each change with `library_log.removed` and `library_log.renamed` in the same transaction. A computer that catches up on its own removal while running finds its machine row gone, so this step makes `local_identity.local_machine` add it again before its next change, as startup does. OPERATING or the README says that removing a computer in local mode does not cut it off; revoking its access to the repository does.

Files: src/aistack/api/dashboard.py (`local=True`, recording the events); src/aistack/services/local_identity.py; dashboard.html (the computer settings dialog in local mode).

ADR: [ADR-0033](../../adr/0033-a-removed-computer-comes-back-when-it-changes-something.md).

Tests: removing and renaming from the localhost dashboard records one event each and replays to the same Library; a computer that catches up on its own removal keeps working.

### 10. Taking a team skill never silently replaces an unrelated skill of yours

Closes: [PH-01](plot-holes.md#ph-01-taking-a-team-skill-whose-name-matches-one-of-your-own-silently-replaces-yours-on-every-computer), [UX-V01](ux.md#ux-v01-add-to-library-on-a-team-skill-named-like-an-unrelated-skill-of-your-own-replaces-yours-on-every-computer-with-no-warning-and-the-toast-says-added), [UX-01](ux.md#ux-01-taking-a-team-update-replaces-the-persons-own-backed-up-edits-on-every-computer-and-the-offer-never-says-so), [PH-03](plot-holes.md#ph-03-sharing-an-edit-of-an-older-team-revision-silently-overwrites-a-teammates-newer-one), [UX-06](ux.md#ux-06-sharing-over-a-teammates-unrelated-namesake-is-flagged-only-afterwards-and-teammates-who-took-the-original-are-offered-it-as-an-ordinary-update), [PH-07](plot-holes.md#ph-07-a-library-skill-follows-only-one-team-sharing-it-into-another-team-silently-ends-update-offers-from-the-team-it-came-from).
Largest effort among them: M. **Trust boundary.**

Files: src/aistack/services/skill_service.py (`take_from_team` reports `possibly_unrelated` and refuses without `replace=true`; `share` warns when editing an older team revision); src/aistack/mcp/tools/skills.py (`get_skill` argument and result); dashboard.html (Add to library and Take update confirm what is replaced).

ADR: none needed.

Tests: Taking a namesake that was never linked is refused with a sentence naming both; with `replace` it lands and says so; the dashboard confirm names the skill it replaces; sharing from revision 2 over a team's revision 3 returns a warning.

UX-06's second half, a flag stored on the team revision so teammates are told an offer replaces their skill with an unrelated one, needs a migration and moves to step 39 with the other history work. This step does its first half, the warning in the Share dialog before anything is stored.

### 11. Throttle failed credentials and keep caller text out of the log

Closes: [SEC-02](security.md#sec-02-no-rate-limit-or-lockout-on-any-credential-check-and-the-invite-code-strength-check-accepts-trivially-guessable-codes), [STD-05](industry-standards.md#std-05-failed-authentication-is-never-throttled-and-never-logged-with-a-client-address), [SEC-08](security.md#sec-08-one-team-invite-link-or-the-server-code-is-an-unlimited-oracle-for-every-username-and-team-name-on-the-server), [SEC-03](security.md#sec-03-fastmcp-logs-malformed-tool-arguments-verbatim-at-warning-so-a-team-invite-code-can-reach-the-server-log-and-the-log-leak-test-cannot-see-it), [SEC-14](security.md#sec-14-a-rejected-bearer-gets-fastmcps-oauth-text-telling-the-client-to-re-register-which-aistack-cannot-do), [SEC-09](security.md#sec-09-dashboard-actions-buffer-the-whole-request-body-before-applying-the-16-kib-limit), [AUTO-14](automation.md#auto-14-the-documented-commands-generate-an-invite-code-the-operator-never-sees-and-restart-does-not-rotate-it).
Largest effort among them: M. **Trust boundary.**

Files: src/aistack/mcp/auth/failure_limiter.py (new); src/aistack/mcp/auth/aistack_token_verifier.py; src/aistack/mcp/routes/invite.py; src/aistack/bootstrap/configuration/settings/settings_config.py (stronger code check, `AISTACK_INVITE_CODE_FILE`); src/aistack/bootstrap/__main__.py (fastmcp logger and filter); src/aistack/api/dashboard.py (stream-limited body).

ADR: none needed.

Tests: Twenty wrong bearers from one address get 429 and a log line with the address; a malformed `join_team` call logs no code; `aaaaaaaaaaaaaaaa` is refused at startup without echoing it; a 1 MiB dashboard POST is refused before it is read.

## Keep data safe and the server fast

What an operator needs before they trust it with a team: a restore that works, reads that do not block writes, and pages that stay fast as the server grows.

### 12a. Backups that restore, and a snapshot before every upgrade

Closes: [STD-01](industry-standards.md#std-01-a-stopped-servers-data-lives-in-aistackdb-wal-and-the-obvious-restore-or-the-promised-upgrade-rollback-silently-restores-nothing), [AUTO-16](automation.md#auto-16-an-upgrade-relies-on-the-operator-remembering-to-back-up-first-the-server-could-snapshot-sqlite-itself-before-migrating), and the restore half of [PH-18](plot-holes.md#ph-18-operating-has-no-restore-procedure-no-guidance-for-a-new-server-address-and-a-recovery-script-that-crashes-on-a-typo).
Largest effort among them: M.

Files: src/aistack/db/backup.py (new: back up, restore, snapshot); src/aistack/db/schema.py (snapshot before migrating); src/aistack/bootstrap/context/application_context.py (checkpoint and dispose at shutdown); src/aistack/bootstrap/__main__.py (`aistack backup`, `aistack restore`, close at exit); docs/OPERATING.md (Backups, Restore, Upgrade rollback); compose.yaml (`stop_grace_period`); scripts/container_smoke.py and .github/workflows/tests.yaml (restore drill in the container job).

ADR: none needed.

Tests: After `docker stop` the volume holds one file with the data; the container job backs up, changes, restores and finds the change gone; migrating from an older revision leaves a snapshot at that revision, and a database at head gets none; restore refuses while another process has the database open.

### 12b. Operator tasks are `aistack admin` commands, not Python copied from Markdown

Split from step 12, which was bigger than one PR: the commands below replace every Python block in OPERATING.md, and share a service module with step 9's removal of a computer, so they come after it.

Closes: [AUTO-15](automation.md#auto-15-operator-tasks-are-python-copied-from-markdown-edited-by-hand-and-run-untested), and the rest of [PH-18](plot-holes.md#ph-18-operating-has-no-restore-procedure-no-guidance-for-a-new-server-address-and-a-recovery-script-that-crashes-on-a-typo) (a sentence for an unknown username, the reconnect command beside a new token, changing the server's address).
Largest effort among them: M. **Trust boundary** (it mints and revokes tokens).

Files: src/aistack/bootstrap/admin_cli.py (`aistack admin machines|rotate|remove-machine|register-machine|teams|name-admin|offboard`, reached from __main__.py); src/aistack/services/operator_service.py (already the operator's service, which no tool or route reaches: it gains the computer commands, rather than a second module beside it); docs/OPERATING.md (no Python blocks; a "Changing the server's address" section).

ADR: none needed.

Tests: tests/bootstrap/test_admin_cli.py runs every subcommand against SQLite and PostgreSQL; an unknown username exits with a sentence; OPERATING.md contains no Python blocks.

### 12c. The operator renames a user, and join says a team may hold the name

Closes: [PH-16](plot-holes.md#ph-16-a-username-is-permanent-shares-a-namespace-with-team-names-and-a-taken-one-is-always-explained-as-this-is-you-on-a-new-computer). Step 23 used to link it; the rename and the join sentence are here.
Largest effort among them: S. **Trust boundary** (it changes who a name points at).

Files: src/aistack/services/operator_service.py (`rename_user`: the user and their personal team together, refused when a user or a team holds the new name); src/aistack/bootstrap/admin_cli.py (`aistack admin rename-user OLD NEW`); src/aistack/services/onboarding_service.py (`join`'s refusal says a user or a team holds the name, and no longer reads as "you on a new computer" alone); docs/OPERATING.md (a handle is permanent except through this command).

ADR: none needed. Provenance stores `user_id`, so every `pushed_by` follows the new name.

Tests: tests/bootstrap/test_admin_cli.py renames a user on both databases, and their revisions then show the new name; a rename onto a taken user or team name changes nothing; joining with a team's name gives the same sentence as joining with a user's, and it names both.

The audit proposed telling the two apart. `create_team` deliberately does not say which one holds a name, because a team's name is its members' to know, and a test pins that. So `join` names both instead.

### 13. Scope the 'latest revision' queries and batch the dashboard's team queries

Closes: [DB-01](schema.md#db-01-dashboard-list_skills-and-sync-count-every-revision-and-file-on-the-whole-server-for-each-request-under-sqlites-write-lock), [DB-02](schema.md#db-02-dashboard-state-issues-one-query-per-team-member-plus-a-dozen-per-team-n1), [ENT-10](concurrency-and-reliability.md#ent-10-dashboard-state-queries-once-per-team-member-and-runs-inside-the-sqlite-write-lock-about-180-ms-per-page-load-for-a-400-member-team), [IMP-07](improvements.md#imp-07-apistate-queries-per-team-and-per-member-inside-sqlites-write-lock-concurrent-refreshes-delay-everyones-sync-and-return-500).
Largest effort among them: M.

Files: src/aistack/services/dashboard_service.py; src/aistack/services/skill_service.py (`list_skills`, `export_library`); src/aistack/services/sync_service.py (`_team_updates`); src/aistack/services/team_service.py (batch variants).

ADR: none needed.

Tests: A test captures the statements of `state`, `list_skills` and `sync` for a seeded user and fails on a full scan of `skill_version` or `skill_file` (EXPLAIN on both databases) and on a statement count that grows with team size.

### 14. Reads that change nothing stop taking SQLite's write lock

Closes: [SEC-04](security.md#sec-04-unauthenticated-requests-take-sqlites-write-lock-token-checks-health-and-the-invite-page-all-run-begin-immediate), [STD-06](industry-standards.md#std-06-health-checks-bearer-checks-and-the-invite-page-take-sqlites-write-lock-so-one-slow-write-turns-them-into-503-and-500), [ENT-04](concurrency-and-reliability.md#ent-04-on-sqlite-every-read-waits-for-the-global-write-lock-past-5-s-auth-fails-with-a-bare-http-500-tools-fail-as-failed-unexpectedly-and-health-returns-503).
Largest effort among them: M.

Files: src/aistack/db/engine.py (a read-only session factory that begins DEFERRED); src/aistack/bootstrap/context/application_context.py; src/aistack/mcp/auth/aistack_token_verifier.py, mcp/routes/health.py, mcp/routes/invite.py, api/dashboard.py `state`; AGENTS.md (the transaction rule).

ADR: [ADR-0030 (draft)](../../adr/0030-reads-begin-deferred-on-sqlite.md): On SQLite, a request that only reads begins deferred.

Tests: With a writer holding the lock for 6 s, `/health` answers `ok`, a valid bearer authenticates, and `/api/state` returns; a test proves the read-only factory refuses a write.

### 15. Answer every conflict and limit with a sentence

Closes: [ENT-11](concurrency-and-reliability.md#ent-11-a-lost-join-response-locks-a-newcomer-out-of-their-username), [ENT-12](concurrency-and-reliability.md#ent-12-body-limits-answer-in-the-wrong-place-the-mcp-sdks-4-mib-cap-preempts-syncs-own-node_modules-sentence-and-the-dashboard-buffers-whole-bodies), [ENT-13](concurrency-and-reliability.md#ent-13-an-upload-dropped-mid-body-logs-an-error-with-a-full-traceback), [AUTO-17](automation.md#auto-17-behind-a-tls-proxy-without-aistack_public_url-the-server-silently-hands-out-http-addresses), [STD-14](industry-standards.md#std-14-aistack-serve-reads-the-current-folders-env-and-database_url-mistakes-a-foreign-database-for-an-old-aistack-one-and-blames-reachability).
Largest effort among them: M.

Files: src/aistack/services/onboarding_service.py; src/aistack/mcp/routes/transfer.py; src/aistack/mcp/server_url.py; src/aistack/db/schema.py (`_predates_migrations`); bundled sync skills (413 sentence).

ADR: none needed.

Tests: A retried join after a lost response gets a sentence that says the account exists and how to recover; a sync over the SDK's body cap tells the agent to leave out node_modules; a dropped upload logs one line without a traceback.

### 16. Fix the layouts that break at tablet width and with long names

Closes: [UI-01](ui.md#ui-01-between-821-and-900px-the-desktop-library-and-groups-tables-overlap-themselves-ipad-pro-11-portrait-834px), [UI-02](ui.md#ui-02-deep-group-paths-overflow-their-chips-in-members-and-print-over-the-next-column-the-page-scrolls-sideways-at-every-width), [UI-03](ui.md#ui-03-nowrap-on-user-supplied-names-pushes-the-page-sideways-a-long-computer-name-a-long-username-and-all-of-team), [UI-21](ui.md#ui-21-phone-details-the-current-place-in-the-path-is-cut-to-one-letter-and-the-library-stat-tiles-hide-their-content-behind-hover-titles).
Largest effort among them: M.

Files: src/aistack/bundled/dashboard.html (container query for tables; badge wrapping; nowrap on user text); scripts/demo_seed.py (a long name and an 8-deep group); tests/ui/test_dashboard_page.py.

ADR: none needed.

Tests: At 834×1194 and 900×900 no two cells in a row overlap and nothing scrolls sideways on Library, Groups and Members; with maximum-length names nothing scrolls sideways at 390 and 1440.

## Make releases and upgrades predictable

ADR-0024's promise that computers on different releases keep working depends on releases that can be told apart and on rules for what counts as compatible.

### 17. Versions, a changelog, and a channel to stay on

Closes: [STD-08](industry-standards.md#std-08-every-build-calls-itself-010-so-adr-0024s-refusal-names-a-release-nobody-can-find), [STD-09](industry-standards.md#std-09-latest-is-every-commit-on-main-and-there-is-no-release-tag-or-changelog-to-stay-on), [AUTO-07](automation.md#auto-07-a-computer-on-an-upgraded-library-is-told-to-run-uv-tool-upgrade-by-hand-while-the-self-updater-sits-out-its-24-hour-wait), [STD-16](industry-standards.md#std-16-local-mode-installs-a-new-release-every-day-with-no-way-to-opt-out-or-pin-a-version).
Largest effort among them: S.

Files: CHANGELOG.md (new; the owner's release notes, one section per release, written when a release is cut, not per PR); pyproject.toml (only when the owner cuts a release, per the AGENTS.md version rule); .github/workflows/tests.yaml (`stable` and version image tags; `edge` for main); src/aistack/bootstrap/self_update.py (`AISTACK_AUTO_UPDATE=off`, update at once when a tool meets a newer schema); docs/OPERATING.md.

ADR: none needed.

Tests: The refusal sentence names a version that exists on PyPI; `self_update` honours the opt-out; a computer told its Library was upgraded updates without waiting a day.

Outcome: images from `main` are `edge` and `sha-<commit>` and name their commit (`0.1.0+g1a2b3c4`) in the startup line and in what the database records; `latest`, `X.Y.Z` and the `X.Y` channel come only from a version tag, and every command people copy runs `:0.1`, held by a test against the version. STD-08's check that a breaking migration comes with a new minor runs in the tag pipeline (`scripts/check_release.py`), not on pull requests, because a pull request never changes the version; it also refuses a release without its CHANGELOG.md section, which becomes the GitHub Release. Local mode updates itself only within its minor, `AISTACK_AUTO_UPDATE=off` turns it off, and a Library that needs a newer release starts the update at once, which ADR-0024 now says. The version on the dashboard's Settings page (STD-08) moves to step 37.

### 18. Write down what 'compatible' means and enforce it

Three PRs, because the eight findings are three separate changes: the test that guards the schema, one compatible migration, and the rule with the code that follows it. Each part is a **trust boundary** change (migrations and migration tooling).

#### 18a. The schema test sees every constraint, and constraints have one name

Closes: [DB-03](schema.md#db-03-the-models-and-migrations-agree-test-cannot-see-check-constraints-server-defaults-or-partial-index-predicates), [DB-12](schema.md#db-12-no-naming-convention-on-basemetadata-constraint-names-differ-by-dialect-and-by-migration).
Largest effort among them: S.

Files: tests/db/test_schema.py (CHECKs, server defaults, index predicates and constraint names compared against `create_all` on the same dialect); src/aistack/db/models/base.py (a naming convention that matches PostgreSQL's own names); src/aistack/db/models/team.py (`can_invite`'s shipped default); a migration renaming the three foreign keys 0002 named differently (compatible).

ADR: none needed.

Tests: Each of the four alterations DB-03 lists (one harness CHECK widened, `ck_team_kind` dropped, a server default added, the single-admin index without its WHERE) fails the schema test; constraint names of a migrated PostgreSQL database equal those `create_all` gives.

#### 18b. Index what the services look up by; order and times alike on both databases

Closes: [DB-10](schema.md#db-10-missing-indexes-on-the-columns-the-services-look-up-by-and-no-constraint-for-one-library-per-user), [DB-14](schema.md#db-14-text-order-by-differs-between-sqlite-and-postgresql-depending-on-the-database-collation), [DB-15](schema.md#db-15-as_utc-returns-a-non-utc-time-on-postgresql-when-the-databases-timezone-is-not-utc).
Largest effort among them: S.

Files: a migration adding indexes and a partial unique index for one personal team per user (compatible); the models' `Index` entries; src/aistack/db/engine.py (a portable binary collation, PostgreSQL's TimeZone set to UTC); the services' text `order_by`; src/aistack/db/models/timestamps.py.

ADR: none needed.

Tests: A second personal team for one user is refused; EXPLAIN shows index scans for the lookups DB-10 lists; groups `a-b`, `a.b`, `a_b`, `ab` come back in the same order on both databases; `as_utc` returns UTC on a PostgreSQL database whose time zone is not.

#### 18c. Write down what 'compatible' means and enforce it

Closes: [DB-04](schema.md#db-04-widening-a-stored-enum-a-new-harness-os-or-role-breaks-older-releases-that-adr-0024-lets-keep-running), [DB-09](schema.md#db-09-0008-and-0009-are-additive-but-not-compatible-an-older-writer-silently-breaks-invariants-the-newer-release-depends-on), [DB-08](schema.md#db-08-compatibility-is-checked-only-when-a-process-starts-a-process-already-running-when-another-upgrades-the-database-is-never-told).
Largest effort among them: M.

Files: AGENTS.md (Migrations); src/aistack/db/migrations/script.py.mako (the three questions above `older_releases_compatible`); src/aistack/db/models/harness.py and the other stored value sets (unknown values read as skipped, not as errors); src/aistack/services/sync_service.py (a revision this machine pushed is not another computer's change); src/aistack/db/schema.py and the context assembly (a running process checks the schema before it writes).

ADR: [ADR-0031 (draft)](../../adr/0031-compatible-means-older-data-stays-meaningful.md): A compatible migration also keeps older releases' data meaningful.

Tests: An older release reading a row with an unknown harness value skips it instead of failing; a running process notices a newer schema before its next write; sync after an older release's push from the same machine does not report another computer's change.

### 19. Order the local log so a fast clock cannot win, and rebuild without holding the lock

Closes: [ENT-03](concurrency-and-reliability.md#ent-03-local-mode-orders-the-library-log-by-wall-clock-so-a-computer-whose-clock-runs-ahead-makes-copies-diverge-and-a-rebuild-silently-replaces-a-newer-edit), [ENT-06](concurrency-and-reliability.md#ent-06-a-local-library-rebuild-replays-every-archive-inside-one-sqlite-transaction-and-other-sessions-on-the-computer-fail-after-5-s), [DB-11](schema.md#db-11-library_event-grows-on-no-op-changes-unchanged-pushes-store-the-full-archive-again-and-repeat-installs-log-again).
Largest effort among them: M. **Trust boundary.**

Files: src/aistack/services/library_log.py (hybrid logical clock in the sort key; skip recording no-op events); src/aistack/services/library_sharing.py (rebuild into a new file and swap).

ADR: [ADR-0032 (draft)](../../adr/0032-a-library-log-is-ordered-by-a-hybrid-clock.md): A GitHub Library's log is ordered by a hybrid logical clock.

Tests: Two computers with clocks an hour apart converge on the newer edit by causality; a rebuild of 2,000 events does not make another session on the computer fail; an unchanged push records no event.

## Local mode: one Library, wherever you run it

The remaining local-mode gaps are about finding the right Library and moving it without losing anything.

### 20. Every terminal command finds the agent's Library

Split from the original step 20, which needed a new log event kind and so a release in between (ADR-0024): 20 to 20d below.

Closes: [AUTO-03](automation.md#auto-03-terminal-commands-silently-open-a-different-empty-library-unless-the-agents-settings-are-repeated), [PH-14](plot-holes.md#ph-14-readmes-move-to-a-teams-server-starts-with-an-export-that-cannot-see-a-github-or-postgresql-library-and-reports-exported-0-skills).
Largest effort among them: M.

Files: src/aistack/bootstrap/configuration/settings/settings_config.py (read where the Library lives from `AISTACK_HOME/library.toml` when the environment says nothing; never a password); src/aistack/bootstrap/__main__.py (the agent's server and `check` record the place; `dashboard`, `export` and `check` refuse a place that disagrees, and `export` refuses a Library that does not exist yet); bundled/local/setup.md and the local sync skill (terminal commands need no settings copied out of `claude mcp get`).

ADR: none needed.

Tests: `check` with AISTACK_LIBRARY_REPO, then `check`, `export` and `dashboard`'s context without it report the same repository and create no aistack.db; a conflicting variable exits non-zero naming both places; a PostgreSQL place with no URL set refuses with a sentence; `export` with no Library anywhere leaves no `~/.aistack` behind.

### 20b. Moving a Library is one command that keeps history

Closes: [AUTO-06](automation.md#auto-06-moving-a-library-is-a-hand-re-import-that-loses-history-placements-and-removals-though-publishing-the-existing-log-already-works), [UX-18](ux.md#ux-18-the-move-here-dialog-says-the-same-thing-for-every-destination-wrong-for-only-this-computer-silent-on-history-and-restart). Part 1 of [AUTO-05](automation.md#auto-05-after-moving-a-library-the-other-computers-stop-at-setup-step-1-and-quietly-stay-on-the-old-one), setup's step 1 noticing a connection to a different place, is step 23's: it is the same text as PH-09, and step 3 rewrites it first. Part 3 is gone: the README no longer describes the move.
Largest effort among them: M.

ADR-0025 already says a Library can move to GitHub by publishing the log it records, so no new ADR.

Files: src/aistack/bootstrap/__main__.py (`aistack move github|postgresql|here`: publish the existing log, or replay it into the new database in one transaction, then record the new place); src/aistack/services/library_repo.py (refuse a repository whose log holds another Library); dashboard.html (each destination's own 'after' sentence; history moves with the Library; the agent restarts once); the local sync skill ('Moving the Library' becomes one command and a restart).

Tests: `aistack move github` on a SQLite Library that holds a removed skill and two computers' placements produces the same `/api/state` on a second computer that replays the repository, and sync there does not list the removed skill's folder under backup; a log that cannot rebuild its Library, or a repository holding another Library, is refused and nothing is published; a UI test of 'Move to only this computer' does not find 'other computers then need'.

### 20c. Say when GitHub cannot be reached, and nudge a Library kept on this computer only

Closes: [AUTO-08](automation.md#auto-08-a-github-library-that-cannot-be-reached-or-whose-login-was-revoked-syncs-as-up-to-date-from-a-stale-copy), [UX-08](ux.md#ux-08-for-a-github-library-the-dashboard-says-connected-and-each-computer-picks-up-the-change-when-github-cannot-be-reached), [UX-P01](ux.md#ux-p01-a-library-kept-on-this-computer-only-is-never-shown-as-at-risk-propose-a-nudge-not-a-gate).
Largest effort among them: M.

Files: src/aistack/services/library_sharing.py (remember the last pull's and push's outcome); src/aistack/mcp/tools/local.py (`library_reachable` and `library_problem` on sync and list_skills); src/aistack/api/dashboard.py (the state says whether GitHub was reached; a local action returns `shared`); dashboard.html (Where it lives and the pill say when GitHub is unreachable; the 'only on this computer' notice).

ADR: none needed.

Tests: with the repository moved away, `sync` returns `library_reachable` false and a sentence, and with a fake `gh` that is signed out the sentence names `aistack github`; `/api/state` reports it and a placement change returns `shared` false; a this-computer Library with one skill shows the notice in the browser and a GitHub one does not.

### 20d. A moved Library tells the computers still on the old place

Closes: part 2 of [AUTO-05](automation.md#auto-05-after-moving-a-library-the-other-computers-stop-at-setup-step-1-and-quietly-stay-on-the-old-one).
Largest effort among them: M.

A `library_moved` event is a new kind, so it ships in two releases (ADR-0024): one that reads it and answers every tool with "Your Library moved to <place> on <date>; set AIStack up again with that place", then one where `aistack move` records it in the old Library. Never a secret in the event: the kind and the repository or host.

Files: src/aistack/services/library_log.py; src/aistack/bootstrap/__main__.py; src/aistack/mcp/tools/local.py.

ADR: none needed.

Tests: a release that reads but does not write the event replays a log holding one; after a move recorded in a SQLite or PostgreSQL Library, a second process on the old Library gets the moved sentence from `sync`.

Split into two PRs, one per release. 20d is the reader: replay stores `library_moved`, `record` refuses it (`_REPLAY_ONLY`), and every local tool and every local dashboard action answers with where the Library went. 20e is the writer: `aistack move` records the event in the old Library, and `library_moved` leaves `_REPLAY_ONLY`. It ships in a release after one that carries 20d, as 9c does after 9b.

### 21. A restored home folder is a new computer

Closes: [LH-02](plot-holes.md#lh-02-a-home-folder-restored-onto-a-new-computer-makes-two-computers-one-the-machine-id-and-on-a-server-the-token-travel-with-it), [AUTO-11](automation.md#auto-11-running-setup-in-the-second-agent-on-an-already-connected-computer-registers-the-same-computer-twice-and-the-two-then-undo-each-other).
Largest effort among them: M.

Files: src/aistack/bootstrap/hardware.py (the operating system's id for the computer); src/aistack/bootstrap/context/application_context.py (a fingerprint beside `machine-id`, and a new id when it disagrees); src/aistack/mcp/tools/local.py (`new_computer` in the sync result); src/aistack/bundled/setup-aistack.md (step 1 checks both agents).

ADR: none needed.

Tests: A copied `AISTACK_HOME` under a different fingerprint registers a second machine and says so once, and the original keeps its placements; processes starting together on the restored home agree on one new id; setup's step 1 checks both agents.

The server half of LH-02 is step 21b: the server cannot read a computer's hardware, so the agent would have to send it.

### 21b. A server notices a machine token copied to another computer

Closes: the server half of [LH-02](plot-holes.md#lh-02-a-home-folder-restored-onto-a-new-computer-makes-two-computers-one-the-machine-id-and-on-a-server-the-token-travel-with-it).
Largest effort among them: M.

The token in `~/.claude.json` or `~/.codex/config.toml` travels with a restored home folder. The server sees only the token, so the sync skill would pass a fingerprint the agent reads from the operating system (the same id `bootstrap/hardware.py` reads), hashed with the machine id, to `sync`. A nullable `machine.fingerprint_hash` (a compatible migration) records the first one; a different one is refused with one sentence and the add_machine path. This adds a `sync` argument, which needs its own design pass before it is built: the agent reads the id with a shell command per operating system, and a missing argument from an older sync skill must keep working.

Files: src/aistack/db/models/machine.py and a compatible migration; src/aistack/services/sync_service.py; src/aistack/mcp/tools/sync.py; the bundled sync skill.

ADR: none needed.

Tests: a sync with a different fingerprint than the machine's first is refused with the add_machine sentence; a sync without one still works.

### 22. A second computer gets the sync skill and the session-start hook, whatever its agent

Closes: [PH-06](plot-holes.md#ph-06-a-codex-only-second-computer-added-with-add_machine-never-gets-the-sync-skill-or-the-offer-of-the-library), [UX-07](ux.md#ux-07-a-second-computer-that-has-only-codex-never-gets-the-sync-skill-or-the-first-sync-library-offer-and-the-dashboard-shows-it-a-claude-code-folder-before-it-syncs), [AUTO-09](automation.md#auto-09-a-computer-connected-with-add_machine-is-never-offered-the-session-start-hook-and-a-codex-only-one-never-gets-the-sync-skill), [PH-15](plot-holes.md#ph-15-the-sync-tools-sync-skill-download-fails-on-exactly-the-computers-it-exists-for), [AUTO-22](automation.md#auto-22-the-invite-page-makes-an-existing-user-pick-the-code-out-of-a-setup-sentence), [UX-20](ux.md#ux-20-add-my-other-computer-never-tells-the-person-the-command-they-carry-to-the-other-computer-is-a-permanent-key).
Largest effort among them: M.

Files: src/aistack/mcp/tools/onboarding.py (`add_machine` result); src/aistack/services/sync_service.py (`sync_skill_url` for the folder the caller syncs); src/aistack/mcp/routes/invite.py (a join-team copy block); bundled sync skills.

ADR: none needed.

Tests: A Codex-only computer added with `add_machine` gets `sync_skill_url` and the first-sync offer on its first sync; the add-machine text says the command is a key; the invite page offers 'join a team with this code' to existing users.

AUTO-10 moved to step 22b: a computer invite is a third kind of bootstrap bearer, which needs an ADR, and is more than this PR. AUTO-09's "fetch the sync skill in `codex_config`" is not needed once the server offers the skill to a computer whose Claude Code never synced, and PH-06's report field for the first-sync offer became one line in the `sync` description pointing at the skill's step 5, which the same sync has just downloaded: the description is at its 2048-character limit, and the offer needs `list_skills` either way.

### 22b. Adding a computer on a server is one paste, with no token carried between computers

Closes: [AUTO-10](automation.md#auto-10-adding-a-computer-on-a-server-takes-four-hops-and-moves-a-permanent-token-between-machines-a-one-use-computer-invite-would-make-it-one-paste).
Largest effort among them: M.

A one-use, seven-day computer invite for the caller's own account, built like a team invite (ADR-0022): a row with a hashed `aistdev_` code, made by `add_machine` or a dashboard button, redeemed by `join`, which then registers a machine for the existing user and runs the whole setup there. The token never leaves the computer that uses it.

Files: a compatible migration and model for the invite row; src/aistack/services/onboarding_service.py; src/aistack/mcp/tools/onboarding.py; src/aistack/mcp/auth/; src/aistack/api/dashboard.py and the page; src/aistack/bundled/setup-aistack.md; docs/OPERATING.md (recovery hands out a link).

ADR: needed. It amends ADR-0003 and ADR-0019 with a third kind of bootstrap bearer under the same tag-based rule.

Tests: an HTTP test shows a computer invite from user A, redeemed with `join`, creates a machine for A and no new user; it works once, expires, and can be cancelled. The dashboard's Add a computer dialog shows a link.

### 23. Setup can be run again, and a stopped setup can finish

Closes: [PH-09](plot-holes.md#ph-09-setup-step-1-stops-at-already-connected-for-any-aistack-connection-a-pasted-team-invite-is-dropped-and-another-server-or-local-mode-dead-ends), [PH-10](plot-holes.md#ph-10-a-setup-that-stops-after-join-locks-the-newcomer-out-the-re-run-refuses-the-used-invite-then-the-username), [ENT-11](concurrency-and-reliability.md#ent-11-a-lost-join-response-locks-a-newcomer-out-of-their-username), [UX-11](ux.md#ux-11-joining-asks-for-the-name-you-want-to-go-by-but-join-needs-a-lowercase-username-and-has-no-place-for-the-full-name), [UX-12](ux.md#ux-12-an-existing-user-who-pastes-the-invite-pages-setup-sentence-may-never-be-put-in-the-team-setup-has-no-branch-for-a-team-code), [AUTO-21](automation.md#auto-21-joining-drops-the-name-the-person-gave-and-asks-questions-local-mode-answers-itself), [AUTO-25](automation.md#auto-25-join-first-alone-is-an-operator-step-that-protects-nothing-today). Also part 1 of [AUTO-05](automation.md#auto-05-after-moving-a-library-the-other-computers-stop-at-setup-step-1-and-quietly-stay-on-the-old-one): when `aistack` is connected to a different place than the one asked for, step 1 says so, removes the old connection, and goes on.
Largest effort among them: M.

Files: src/aistack/bundled/setup-aistack.md; src/aistack/services/onboarding_service.py (`join` takes a full name); src/aistack/mcp/tools/onboarding.py.

ADR: none needed.

Tests: Setup on a connected computer with a team invite joins the team instead of stopping; a join whose answer was lost can be completed; the name a person gives becomes their full name.

Outcome: ENT-11's idempotency key was not built. The answer is kept in a file until the agent is connected, which covers a setup that stops after joining. An answer lost on the network is completed by the operator's `aistack admin register-machine` (step 12b), which the setup text and the refusal both name. A key would need a migration, and it would let a replayed request mint a token. README's move to a server (AUTO-05's third fix) is now setup step 1's "another address, or a command" branch.

## Skill folders inside projects

The owner's next feature, placed here because it needs what comes before it: releases that computers actually update to (the bridge release depends on it), a log ordered safely (ENT-03), and machine removal settled. The design is [projects-design.md](projects-design.md) and the decision is the ADR draft below. The steps are the design's own, in its order.

### 24. Record the decision: ADR-0026 and the glossary

Effort S.

Add the ADR (Status: proposed) and the glossary terms Project, Project folder, and Repository's skill, with Avoid lists (workspace, repo skill, checkout skill). Add one line to DESIGN.md §3, and to README's ADR list. Note in DESIGN.md's 'Explicitly not built' that project folders are planned. Docs only, no code.

Files: `docs/adr/0026-skills-folders-inside-projects.md`; `CONTEXT.md`; `docs/DESIGN.md`; `README.md`.

ADR: [0026 Skills folders inside projects](../../adr/0026-skills-folders-inside-projects.md).

Tests: No new tests. The existing docs tests (test_dashboard_routes_are_documented) are unaffected.

### 25. Identify a project from its remote or its path

Effort S. **Trust boundary.**

Add the pure functions in services/projects.py:
- project_key(remote): drops the scheme, credentials, port and .git, lowercases, caps at 255, and returns None for file:// remotes and paths.
- local_project_key(machine_id, top_level).
- project_name(key_or_path).
- validated_here(path, remote): path at most 1024 characters, printable, absolute or ~, and not the home folder.
Errors never echo a remote. No database, no I/O.

Files: `src/aistack/services/projects.py`; `tests/services/test_projects.py`.

ADR: [0026 Skills folders inside projects](../../adr/0026-skills-folders-inside-projects.md).

Tests: - Parametrized cases: 'https://user:ghs_x@github.com/Owner/Repo.git', 'git@github.com:Owner/Repo.git' and 'ssh://git@github.com:22/owner/repo' all give 'github.com/owner/repo'.
- 'file:///srv/r.git', '/srv/r.git' and 'C:\\code\\r' give a local key.
- Empty input or a control character raises ValidationError, and the message contains no part of the input.
- caplog holds no 'ghs_'.
- '~', '/Users/maria' and 'C:\\Users\\maria' are refused as the home folder.

### 26. Add the project tables (one compatible migration)

Effort M. **Trust boundary.**

- Add the models Project, MachineProject (harness via harness_type('ck_machine_project_harness')) and MachineProjectSkill.
- A migration (the next free number) creates the three tables with every FK ON DELETE CASCADE and an index on machine_project.project_id, and sets older_releases_compatible = True. It declares its own harness tuple and imports no model.
- Add visibility.my_project and required_my_project: an unknown project and another user's answer alike.
- Add the DESIGN.md schema block.

Files: `src/aistack/db/models/project.py`; `src/aistack/db/models/machine_project.py`; `src/aistack/db/models/machine_project_skill.py`; `src/aistack/db/models/__init__.py`; `src/aistack/db/migrations/versions/<next>_projects.py`; `src/aistack/services/visibility.py`; `docs/DESIGN.md`; `tests/db/test_schema.py`.

ADR: [0026 Skills folders inside projects](../../adr/0026-skills-folders-inside-projects.md).

Tests: - The existing tests 'fresh database gets exactly the schema the models describe' and 'every migration says whether older releases still work' pass.
- New test: an older release's rebuild empties a copy that holds project rows. It deletes only the tables from before the project migration, in sorted order, with project rows present. It fails without the cascades, as reproduced by proto/old_rebuild.py.
- Run the schema tests with TEST_DATABASE_URL on PostgreSQL.

### 27. Project placements in the services, and a removed skill wanted nowhere

Effort M. **Trust boundary.**

- New services/project_service.py:
  - register_folder: creates or refreshes machine_project and returns first_sync, meaning last_synced_on was null. Uses a savepoint race as record_sync does.
  - add_folder (dashboard), remove_folder, set_enabled, decisions(machine_project), placed_elsewhere(user, project, machine).
- skill_service.remove_from_my_skills also disables machine_project_skill rows.
- sync_service._desired reads an archived skill as DISABLED in every folder. This changes no state reachable today; it covers placements that an older release's removal leaves enabled.

Files: `src/aistack/services/project_service.py`; `src/aistack/services/skill_service.py`; `src/aistack/services/sync_service.py`; `tests/services/test_project_service.py`; `tests/services/test_sync_service.py`.

ADR: [0026 Skills folders inside projects](../../adr/0026-skills-folders-inside-projects.md).

Tests: - Two first registrations racing at a threading.Barrier report exactly one first_sync. The test fails without the savepoint.
- Removing a skill from the Library disables its project placements.
- An archived skill with an enabled project placement, inserted directly as R0 would leave it, is reported under ask as disabled and never installed.
- The existing global sync matrix tests pass unchanged.

### 28. Replay project events before anything records them (bridge release)

Effort M. **Trust boundary.**

- In library_log: add the kinds project_folder_added, project_folder_removed, skill_placed_in_project and skill_pushed_to_project, with apply branches through project_service.
- Replay validates key, name, harness and path as the tools would.
- A _REPLAY_ONLY set makes record() refuse these kinds.
- Add the AGENTS.md rule: a new event kind is replayed one release before it is recorded.
- Ship this as its own release, R1.

Release gate: #160 supplies the reader. Keep project events replay-only until a release carrying it has been out for at least a week. The owner cuts both releases.

Files: `src/aistack/services/library_log.py`; `AGENTS.md`; `tests/mcp/test_library_log.py`.

ADR: [0026 Skills folders inside projects](../../adr/0026-skills-folders-inside-projects.md).

Tests: - _snapshot includes project, machine_project and machine_project_skill.
- Hand-built project events give the same snapshot when applied on top and when rebuilt, over several random-order seeds.
- A forged event with a key containing '@', a control character, or more than 255 characters is refused, and the refusal names its log file.
- library_log.record() refuses a replay-only kind.

### 29. Sync a project folder

Effort M. **Trust boundary.**

sync_service.sync takes an optional project folder and the repository's names:
- Decisions come from machine_project_skill.
- Repository names are excluded from install, update, ask and backup, and returned as left_to_repository when enabled.
- refresh_sync_skill is false for a project.
- first_sync comes from register_folder, with from_other_computers on first sync.
- A here lookup returns {key, name, managed} and stores nothing for an unmanaged project.

Files: `src/aistack/services/sync_service.py`; `src/aistack/services/project_service.py`; `tests/services/test_sync_service.py`.

ADR: [0026 Skills folders inside projects](../../adr/0026-skills-folders-inside-projects.md).

Tests: - The Desired x Observed matrix, parametrized over the global folder and a project folder, gives identical verdicts.
- A name in repository with an enabled placement is never installed and appears in left_to_repository.
- Two paths (clones) of one project share decisions.
- from_other_computers lists only other computers' enabled, non-archived placements in this project, and only on first sync.
- A here for an unmanaged repository writes no row.
- Sync writes nothing except machine_project.

### 30. Server-mode tools take a project

Effort M. **Trust boundary.**

- sync gains here {path, remote}, project (a key) and repository (names). Its report gains project, left_to_repository and from_other_computers. Its digest commands move out of the description into the skill.
- get_skill, push_skill and disable_skill gain project. get_skill's folder is relative to the top level for a project.
- UploadTicket gains an optional project_id claim. The upload route re-checks the project folder before the first write.
- Logs carry project_id, never path or remote.

Files: `src/aistack/mcp/tools/sync.py`; `src/aistack/mcp/tools/skills.py`; `src/aistack/services/transfer_ticket.py`; `src/aistack/mcp/routes/transfer.py`; `src/aistack/services/skill_service.py`; `tests/mcp/test_sync_over_http.py`; `tests/mcp/test_push_over_http.py`; `tests/mcp/test_install_over_http.py`; `tests/services/test_transfer_ticket.py`; `tests/mcp/test_tool_descriptions.py`.

ADR: [0026 Skills folders inside projects](../../adr/0026-skills-folders-inside-projects.md).

Tests: In-process HTTP with a bearer:
- sync with here returns managed false, and a project sync registers the project.
- push_skill with project, then the upload, places the skill in the project folder only.
- An upload after the folder was removed is refused, and no revision is stored.
- Another user's key gets the same NotFound sentence as an unknown key.
- A canary 'ghs_' remote never appears in captured logs or results.
- Every description stays at or under 2048 characters.
- OUTSIDER_VIEW is unchanged, because no new tool is added.

### 31. Teach the server's sync-aistack skill the project steps

Effort M. **Trust boundary.**

The skill gains:
- Step 1b: top level and remote, credentials stripped (sed and PowerShell forms), and a refusal for the home folder.
- Send here only when the sync tool's schema has it.
- Classify a project folder with the three git ls-files commands.
- Project install: write info/exclude lines for the folder and the staging folder, check that ls-files is empty and check-ignore passes, do a staged install under the top level, and give the reload hint when the folder was created.
- Project removal checks.
- The 'add this project to aistack' phrase.
- The first-sync offer, the both-folders question scoped to the project, and rename advice for undecided+unknown.

Files: `src/aistack/bundled/skills/sync-aistack/SKILL.md`; `docs/DESIGN.md`; `tests/mcp/test_sync_over_http.py`; `tests/e2e/test_project_skill_steps.py`.

ADR: [0026 Skills folders inside projects](../../adr/0026-skills-folders-inside-projects.md).

Tests: - The existing check that the bundled skill passes push validation still passes.
- A new e2e test runs the skill's git commands, extracted from the skill, against a temporary repository with a linked worktree, a tracked skill and an untracked skill. After an install and a removal, 'git status --porcelain' and 'git diff' are unchanged, and the installed folder is ignored in the worktree.
- One recorded run each with Claude Code and with Codex, in a repository and in a worktree, before the feature is called supported.

Outcome: the e2e test runs the skill's own commands: its three listings, its install guard twice, an install and a removal, in a clone and its linked worktree, and its credential-stripping of a remote. The recorded agent runs are not done yet, so no page or README calls project folders supported.

### 32. Local mode: git-hardened project folders

Effort L. **Trust boundary.**

- New services/local_projects.py:
  - It resolves the checkout from here with 'git -c core.fsmonitor=false', the environment stripped of GIT_* (move _git_environment out of library_repo into a shared helper), and timeouts.
  - It refuses the home folder, anything under AISTACK_HOME, and a skills folder whose realpath leaves the top level.
  - It classifies folders, and observes personal folders only.
  - Install writes the exclude lines, re-checks check-ignore, then calls local_skills.install and returns folder_created.
  - Remove refuses repository folders.
  - make_personal handles an explicit push of an unignored folder.
- The local tools gain here and project and record the new events. Remove them from _REPLAY_ONLY only in a release that ships at least a week after R1.
- Update the local sync-aistack skill.

Files: `src/aistack/services/local_projects.py`; `src/aistack/services/library_repo.py`; `src/aistack/mcp/tools/local.py`; `src/aistack/services/library_log.py`; `src/aistack/bundled/local/sync-aistack/SKILL.md`; `tests/services/test_local_projects.py`; `tests/mcp/test_local_mode.py`; `tests/mcp/test_library_log.py`.

ADR: [0026 Skills folders inside projects](../../adr/0026-skills-folders-inside-projects.md).

Tests: Run against real temporary repositories:
- Tracked folders and untracked, unignored folders are never written or deleted: git status and git diff are unchanged.
- Install adds each exclude line once, and the folder is ignored from a linked worktree too.
- Refused cases: a repository at HOME, one under AISTACK_HOME, and a '.claude' symlinked to HOME/.claude.
- A repository whose .git/config sets core.fsmonitor to a script that writes a marker file leaves no marker.
- folder_created is true only when the install made the folder.
- The random-sequence replay test includes project actions.

### 33. Dashboard API for project folders

Effort M. **Trust boundary.**

- dashboard_service.state adds machines[].projects (key, name, and folders with harness, path and last_synced_on) and placements[].project.
- _machines counts harnesses known from machine_project.
- set_on_machine takes a project.
- New actions POST /api/machines/{machine_id}/projects and /projects/remove, with the key in the body. In local mode they record events.
- Update DESIGN.md's routes table.

Files: `src/aistack/services/dashboard_service.py`; `src/aistack/api/dashboard.py`; `docs/DESIGN.md`; `tests/api/test_dashboard_over_http.py`; `tests/api/test_local_dashboard.py`.

ADR: [0026 Skills folders inside projects](../../adr/0026-skills-folders-inside-projects.md).

Tests: - /api/state lists only the caller's projects.
- Placing into another user's project or machine gets the same 404 as an unknown one.
- Adding a project known from another computer creates folder rows with a null path.
- Removing a project folder cascades its placements and leaves the Library and the other computers untouched.
- The route-documentation test passes.
- A POST without X-AIStack-Request is refused.

Outcome: built for a server. In local mode each action would record a project event, which waits for the release step 32 needs (ADR-0026), so the two new routes are server-only and the localhost dashboard refuses a placement with `project`. Local mode's half moves to step 32.

### 34. Dashboard page: projects in the computer tree

Effort L.

In dashboard.html:
- targets() includes project folders.
- The computer tree gets project leaves beside Global under each agent, and '+ Add a project'.
- Route #/f/<machine>/<agent>/<key>, with a project variant of folderView: header, 'not synced here yet' card, foot note, and the Stop managing… confirm.
- The picker and whereItIs label folders as '<agent> in <project>'.
- An 'Add a project' dialog with two choice-cards.
- A 'repo' icon.
- A help line when Global and a project both hold a skill for one agent.
Also: demo_seed seeds a project, and design-system.md documents the Projects pattern.

Files: `src/aistack/bundled/dashboard.html`; `docs/design-system.md`; `scripts/demo_seed.py`; `tests/ui/test_dashboard_page.py`; `tests/ui/test_local_dashboard_page.py`.

ADR: [0026 Skills folders inside projects](../../adr/0026-skills-folders-inside-projects.md).

Tests: Playwright, finding elements by role and by the words a person reads:
- Open 'aistack' under macbook > Claude Code, Add skills, then confirm the placement with project in /api/state.
- The skill panel ticks 'Claude Code in aistack'.
- 'Stop managing aistack on macbook…' removes it from the tree and from /api/state.
- The empty state and the not-synced card read correctly.
- axe is clean in both themes, and there is no horizontal scroll at 390px.
- CI runs Chromium, Firefox and WebKit.

## Make the page calm, accessible and honest

Keyboard, screen reader and wording fixes. None is dangerous, and together they decide whether the dashboard feels finished.

### 35. Keyboard and screen reader

Closes: [UI-04](ui.md#ui-04-no-skip-link-18-tab-stops-before-the-first-control-in-main-and-more-for-every-team-and-computer), [UI-05](ui.md#ui-05-focus-falls-to-body-after-every-sidebar-navigation-and-after-actions-that-remove-their-own-button), [UI-06](ui.md#ui-06-the-phone-drawer-is-not-modal-tab-walks-out-from-under-the-scrim-into-the-page-behind), [UI-07](ui.md#ui-07-confirm-dialogs-open-with-focus-on-the-destructive-button-holding-enter-on-leave-team-leaves-the-team), [UI-08](ui.md#ui-08-an-actions-outcome-toast-is-inserted-while-the-modal-is-still-open-then-disappears-on-its-own-after-6s-or-10s-warnings-included), [UI-10](ui.md#ui-10-inputs-selects-and-the-focused-menu-item-fall-below-31-non-text-contrast), [UI-11](ui.md#ui-11-icon-only-controls-the-design-system-forbids-the-member-remove-trash-and-the-phones-library-pill-whose-name-becomes--connected), [UI-12](ui.md#ui-12-the-back-button-leaves-an-open-destructive-dialog-on-top-of-a-different-view), [UI-13](ui.md#ui-13-switches-the-name-contradicts-the-visible-word-when-off-a-disabled-switchs-explanation-cannot-be-reached-tooltips-cannot-be-dismissed), [UI-14](ui.md#ui-14-row-buttons-whose-names-do-not-say-which-skill-or-group-add-to-computer-take-update-add-to-library-people), [UI-15](ui.md#ui-15-table-and-landmark-semantics-rows-with-different-cell-counts-aria-label-on-a-plain-div-avatar-letters-read-aloud-the-account-bar-outside-every-landmark), [UI-16](ui.md#ui-16-page-titles-the-team-tabs-share-one-title-and-titles-are-joined-with----which-the-design-system-forbids).
Largest effort among them: M.

Files: src/aistack/bundled/dashboard.html; docs/design-system.md; tests/ui/test_dashboard_page.py.

ADR: none needed.

Tests: A skip link reaches main in one Tab; focus lands on the new page's heading after navigation; the drawer traps focus; confirm dialogs open on Cancel; toasts are announced and stay until dismissed when they report an action; axe reports no violation on any screen.

### 36. The pages before sign-in, the icon, and local mode's remembered choices

Closes: [UI-17](ui.md#ui-17-the-signed-out-and-invite-pages-have-no-lang-no-dark-theme-no-main-landmark-and-the-signed-out-pages-title-does-not-say-signed-out), [STD-18](industry-standards.md#std-18-the-pages-a-newcomer-sees-first-fail-wcag-22-level-a-and-dashboard-messages-disappear-on-a-timer), [UI-22](ui.md#ui-22-no-icon-is-declared-so-every-page-load-asks-for-faviconico-gets-404-and-the-browser-tests-fail-in-a-full-browser), [UI-09](ui.md#ui-09-local-mode-forgets-the-theme-accent-and-picked-agents-every-run-each-dashboard-gets-a-new-port-and-so-a-new-origin), [UX-02](ux.md#ux-02-a-sign-in-link-works-once-but-the-wording-says-five-minutes-and-reopening-it-says-you-are-not-signed-in-even-to-a-signed-in-browser).
Largest effort among them: M.

UI-22 is done: every page names the logo inline (`ICON_LINK` in `aistack.bundled`), and the invite page's policy allows that one image.

Files: src/aistack/api/dashboard.py (signed-out page); src/aistack/mcp/routes/invite.py; src/aistack/mcp/routes/setup.py; dashboard.html (`aistack dashboard` reuses its last port when free).

ADR: none needed.

Tests: axe finds no violation on the signed-out, invite and setup pages in both themes; the browser tests pass in a full Chromium; a second `aistack dashboard` keeps the theme.

### 37. Shorter text, and words that say what is true

Closes: [UI-23](ui.md#ui-23-explanations-sit-on-the-page-where-one-line-and-a-click-would-do-dialogs-footnotes-and-zero-value-tiles-clutter-the-screens-people-open-most), [UX-04](ux.md#ux-04-where-it-lives-on-a-server-says-everyone-on-this-server-shares-it-about-a-private-library-and-suggests-setting-aistack-up-again), [UX-05](ux.md#ux-05-skills-you-wrote-and-shared-show-in-your-library-as-coming-from-the-team-n-skills-from-a-team), [UX-09](ux.md#ux-09-tool-specific-error-sentences-reach-local-mode-and-the-dashboard-call-get_skill-with-its-team-the-server-holds-no-decision-a-python-function-name), [UX-13](ux.md#ux-13-pending-invites-made-close-together-cant-be-told-apart-and-the-invite-dialog-says-to-send-one-link-to-the-people), [UX-14](ux.md#ux-14-with-an-empty-library-add-skills-says-everything-in-your-library-is-here-already-and-still-offers-add), [UX-15](ux.md#ux-15-removal-confirmations-and-toasts-misstate-what-happens-and-leave-out-what-stays-and-what-is-irreversible), [UX-19](ux.md#ux-19-ticking-computers-in-the-skill-panel-and-then-clicking-share-with-a-team-or-remove-from-library-discards-the-ticks-without-a-word), [UI-18](ui.md#ui-18-type-rules-broken-rail-names-at-105px-avatars-at-11px-monospace-uppercase-letters-and-usernames-in-monospace), [UI-19](ui.md#ui-19-with-the-graphite-accent-the-current-sidebar-item-looks-the-same-as-a-hovered-one), [UI-20](ui.md#ui-20-add-an-agent-cannot-be-undone-a-picked-agent-stays-on-that-computer-in-this-browser-forever).
Largest effort among them: M.

Files: src/aistack/bundled/dashboard.html; docs/design-system.md (the one-line rule and word budget); services whose sentences name tools (UX-09). Also the running release on the Settings page, moved here from step 17 (STD-08).

ADR: none needed.

Tests: Each renamed control changes its UI test in the same commit; no dialog intro exceeds 25 words; the server's Where it lives no longer says the Library is shared.

### 38. Bring DESIGN.md, OPERATING.md and the README back in line with the code

Closes: [PH-17](plot-holes.md#ph-17-design-operating-and-context-describe-a-server-that-has-since-changed), [IMP-10](improvements.md#imp-10-designmd-the-document-that-wins-on-conflict-contradicts-the-code-in-a-dozen-places), [IMP-14](improvements.md#imp-14-readme-has-drifted-adr-list-size-claims-a-stale-known-limit-a-built-roadmap-item-and-old-screenshots), [IMP-13](improvements.md#imp-13-try-it-in-two-minutes-dead-ends-after-five-minutes-and-the-contributor-test-instructions-skip-the-browser-tests), [STD-12](industry-standards.md#std-12-the-documented-deployment-publishes-plain-http-on-every-interface-and-keeps-logs-without-limit), [SEC-12](security.md#sec-12-the-documented-run-commands-expose-the-plain-http-port-the-quick-start-on-every-interface-with-a-public-code-and-the-tls-proxy-pattern-still-publishing-8000), [SEC-11](security.md#sec-11-setup-fills-its-urls-from-the-host-header-and-sends-no-cache-control-so-a-caching-proxy-could-serve-a-poisoned-copy), [SEC-13](security.md#sec-13-local-mode-on-a-shared-computer-aistack_home-is-world-readable-and-the-one-use-sign-in-link-is-visible-on-the-browsers-command-line).
Largest effort among them: M.

Files: docs/DESIGN.md; docs/OPERATING.md; README.md; CONTEXT.md; compose.yaml; src/aistack/mcp/routes/setup.py (Cache-Control); src/aistack/bootstrap/context/application_context.py (AISTACK_HOME 0700).

ADR: none needed.

Tests: `test_dashboard_routes_are_documented` still passes; a new test that every ADR file is listed in README; `/setup` answers `no-store`.

## Features worth their effort

Ranked by value for effort in improvements.md.

### 39. See what changed before taking an update, and get an older revision back

Closes: [IMP-08](improvements.md#imp-08-no-way-to-see-what-a-teammate-changed-before-taking-an-offered-update), [PH-08](plot-holes.md#ph-08-it-stays-in-your-history-is-a-promise-nothing-can-keep-no-tool-page-or-script-reads-or-restores-an-older-revision).
Also: the second half of [UX-06](ux.md#ux-06-sharing-over-a-teammates-unrelated-namesake-is-flagged-only-afterwards-and-teammates-who-took-the-original-are-offered-it-as-an-ordinary-update) (a nullable flag on `skill_version`, set when a share went over an unrelated namesake, carried in `team_updates`; a migration with `older_releases_compatible = True`), moved here from step 10.
Largest effort among them: M.

Files: src/aistack/services/skill_service.py (`diff`, `restore_revision`); src/aistack/api/dashboard.py; dashboard.html (a diff in the update row; History in the skill panel).

ADR: none needed.

Tests: An update offer shows the changed lines; restoring revision 1 makes revision 3 with revision 1's files and every computer updates on its next sync.

### 39b. Restore an older revision, and bring back a removed skill, in local mode

Split from step 39, which shipped History and Restore on a server only; step 40 did the same with Bring back. Bringing back a skill is `skill_service.bring_back`, with an event of its own under the same rule. A restore in local mode is a change to the Library, so it is recorded as an event (ADR-0025), and a new event kind is replayed by one release before any release records it (ADR-0026). So: a `skill_restored` event carrying the skill's name and the restored archive goes into `library_log._REPLAY_ONLY`, applied through `skill_service.restore_revision`'s storing half, in one release; the localhost dashboard gets the routes, and the event is recorded, in a release at least a week later.

Files: src/aistack/services/library_log.py; src/aistack/api/dashboard.py (`local=True` on the history, restore and bring-back routes); tests/mcp/test_library_log.py.

ADR: none needed.

Tests: The replay test's random sequences include a restore; a restore made in local mode reaches a second computer's copy.

### 40. Sync reports what is true

Split from "Cheaper syncs", which was three PRs. This one makes sync and the dashboard agree with the Library: a skill folder that is a git clone hashes as current, an unsubscribed group's updates are offered nowhere, leaving a team takes its mutes along, a removed skill is asked about as removed, and a skill that can never be backed up says why, without a push.

Closes: [ENT-05](concurrency-and-reliability.md#ent-05-syncs-file-listing-includes-a-nested-git-that-push-leaves-out-so-a-skill-folder-that-is-a-git-clone-never-shows-as-current-and-restore-deletes-its-git), [IMP-02](improvements.md#imp-02-unsubscribing-from-a-group-stops-syncs-update-offers-but-not-the-dashboards), [DB-13](schema.md#db-13-group-unsubscriptions-survive-leaving-a-team-so-a-returning-member-silently-misses-updates), [PH-11](plot-holes.md#ph-11-after-removing-a-skill-from-the-library-a-computer-that-never-decided-about-it-is-asked-enableskip-forever-and-the-skill-can-no-longer-be-found), [IMP-16](improvements.md#imp-16-a-skill-that-can-never-be-backed-up-is-listed-under-backup-on-every-sync).
Largest effort among them: M.

Files: src/aistack/services/sync_service.py, reconciliation inputs only; src/aistack/services/dashboard_service.py; src/aistack/services/team_service.py; src/aistack/mcp/tools/sync.py; bundled sync skills.

ADR: none needed.

Tests: a `.git` inside a skill folder does not make it 'unknown'; an unsubscribed group's updates are not offered on the dashboard either; leave and rejoin starts subscribed; a removed skill is asked about with a remove option; a skill that cannot be backed up is reported under `cannot_back_up` with its reason.

### 40b. Fewer calls per sync

Closes: [IMP-11](improvements.md#imp-11-a-first-sync-with-many-skills-costs-one-tool-call-per-backup-and-in-a-github-library-one-commit-and-push-per-skill), and [IMP-12](improvements.md#imp-12-tool-results-and-listings-spend-the-agents-context-on-what-it-never-uses-and-two-descriptions-have-no-room-left) but get_skill's result (step 40d).
Largest effort among them: M.

Files: src/aistack/mcp/tools/sync.py, skills.py and local.py (`push_skill(names=...)`, `list_skills(team, query)`, descriptions dedented); bundled sync skills.

ADR: none needed.

Tests: one push_skill call backs up a list, refusing the bad names; in local mode the Library is shared once for it; list_skills narrows by team and words; every description keeps 100 characters free.

### 40d. Sync without copying digests or running seven commands per skill

Split from 40b: it changes what a transfer ticket can do, so it is a **trust boundary**, and part of it waits for a release.

Closes: [AUTO-18](automation.md#auto-18-a-server-mode-sync-makes-the-model-copy-every-file-digest-and-run-about-seven-commands-per-installed-skill), and the get_skill half of [IMP-12](improvements.md#imp-12-tool-results-and-listings-spend-the-agents-context-on-what-it-never-uses-and-two-descriptions-have-no-room-left).
Largest effort among them: M.

Two questions to settle first. A download URL in sync's `install` and `update` entries skips get_skill, which is where the revision a folder last installed is recorded (`edited_from` reads it): the download route would have to record it, so its ticket carries the harness and the project folder. And an observe ticket, a five-minute upload URL for the shasum output, is a new transfer route that parses text: it gets push validation's rigor. Dropping `files` and `content_hash` from get_skill's result removes result fields, which the versioning rule makes a new minor (AGENTS.md, Operations): do it in the release that moves to 0.2, with `file_count` added a release before.

Files: src/aistack/mcp/tools/sync.py; src/aistack/mcp/routes/transfer.py; src/aistack/services/transfer_ticket.py; bundled sync skills.

ADR: none needed, unless the download route records installs: then a short one, since today only get_skill does.

Tests: One sync with three missing skills installs all three from the URLs it returned, byte for byte, and records each folder's revision; a sync through the observe URL returns the same report as the same digests passed as arguments.

### 40c. A session start that stays quiet when nothing changed

Closes: [AUTO-24](automation.md#auto-24-the-session-start-hook-runs-a-full-sync-at-every-startup-even-when-nothing-changed), and the cheap half of [IMP-15](improvements.md#imp-15-one-team-update-is-offered-once-per-folder-and-again-on-every-sync-after-it-was-declined) (ask once per skill across folders; skipping a revision needs an ADR amending ADR-0015).
Largest effort among them: S.

Files: src/aistack/bootstrap/__main__.py (`status --hook`); bundled setup and sync skills.

ADR: none needed.

Tests: `status --hook` prints nothing when the folder matches the Library, and one line after a skill is added.

### 41. One log: a line for every change, one format, no SDK chatter

Split from "Audit trail, logs and an export", which was three PRs.

Closes: [STD-10](industry-standards.md#std-10-changes-made-on-the-dashboard-leave-no-log-line-shares-groups-group-privacy-takes-and-placements), [STD-11](industry-standards.md#std-11-the-server-log-mixes-two-formats-and-fastmcps-multi-line-rich-lines-ignore-aistack_log_level), [IMP-18](improvements.md#imp-18-most-of-the-server-log-is-mcp-sdk-chatter).
Largest effort among them: M.

Files: src/aistack/services/skill_service.py and team_service.py (one INFO line per change, names through `loggable()` beside the ids); src/aistack/bootstrap/__main__.py (one log format, FastMCP's logger taken over, the SDK's per-request lines floored at WARNING).

ADR: none needed.

Tests: every mutator writes one line naming the change, the team and the user, held by a table a new mutator must join; after `configure_logging("ERROR")` nothing logs at INFO; the SDK's two loggers sit at WARNING.

### 41d. Download your Library, and the headers an https server sends

Closes: the export half of [STD-15](industry-standards.md#std-15-a-person-on-a-server-can-neither-export-their-library-nor-be-erased), [STD-13](industry-standards.md#std-13-no-hsts-even-when-aistack_public_url-is-https-inline-scripts-allowed-by-the-csp-and-a-server-banner-on-every-response).
Largest effort among them: M. **Trust boundary** (a route that returns file content, and the page's security headers).

Files: src/aistack/api/dashboard.py (`GET /api/library.tar.gz`, HSTS, a hash-based script-src, the `__Host-` cookie); src/aistack/mcp/mcp.py (`server_header=False`); docs/OPERATING.md (the Caddyfile's HSTS line).

ADR: none needed.

Tests: a person downloads their Library and it matches `aistack export`; on an https server /app sends HSTS and a script-src without 'unsafe-inline', and no `server` header; the browser tests pass in all three engines.

### 41e. The page's words in one table

Closes: [STD-20](industry-standards.md#std-20-the-dashboard-is-english-only-by-construction-locale-fixed-to-en-and-strings-inline).
Largest effort among them: M.

Files: src/aistack/bundled/dashboard.html (strings in one object; `Intl.PluralRules`).

ADR: none needed.

Tests: the browser tests pass unchanged, which is the proof that no word moved.

Held for the owner (2026-10-16): no translation is planned, and moving every string of a 3,000-line page into a table is a large diff with no reader today. Suggested: do it when a translation is wanted, together with that translation.

### 41b. The operator can forget a person

Closes: the erasure half of [STD-15](industry-standards.md#std-15-a-person-on-a-server-can-neither-export-their-library-nor-be-erased). Step 41 gives a person their Library as a download; nothing yet erases them.
Largest effort among them: M. **Trust boundary** (it deletes, and it changes what provenance shows).

Files: src/aistack/services/operator_service.py (`forget`: `offboard` first, so teams keep an admin and every computer goes; then their personal team's skills archived, `full_name` cleared, and the username renamed to `former-<8 hex>`); src/aistack/bootstrap/admin_cli.py (`aistack admin forget USERNAME`); docs/OPERATING.md ("Forget a person"); CONTEXT.md ("Pushed by").

ADR: [ADR-0034](../../adr/0034-a-forgotten-persons-revisions-stay-under-a-pseudonym.md), proposed, waiting on the owner: a forgotten person's revisions stay, and `pushed_by` shows the pseudonym. Draft it as proposed with the code, and accept it in the same PR once the owner agrees on how provenance reads afterward. Deleting their revisions instead would remove skills other people took into their Libraries, which ADR-0015 rules out.

Tests: after `forget` on both databases, member lists and revisions show `former-…`, `full_name` is null, the person's computers are gone, and a team they solely ran has the named successor; a second `forget` of the same person is refused with a sentence.

### 41c. Metrics for the operator, behind a token

Closes: [STD-19](industry-standards.md#std-19-the-log-is-the-only-way-to-observe-a-server-no-metrics-no-request-ids-no-version).
Largest effort among them: M. **Trust boundary** (a new route that answers a bearer).

Files: src/aistack/bootstrap/configuration/settings/settings_config.py (`AISTACK_METRICS_TOKEN`, a `SecretStr`, validated as the invite code is); src/aistack/mcp/routes/metrics.py (`/metrics` in the Prometheus text format; 404 without the setting and without the bearer, compared in constant time); src/aistack/mcp/mcp_error_handler.py and src/aistack/mcp/routes/route_error_handler.py (count each call by tool or route and outcome where they already time it, and put a request id on each log line); the startup line names the version; docs/OPERATING.md.

ADR: none needed. `/health` stays as it is: it answers without a credential, so it carries no counts.

Tests: with the token set, the bearer gets `aistack_tool_calls_total{tool="sync",outcome="ok"}`; without the setting, without the bearer and with a wrong one it answers 404 alike; the token never reaches the log (the container job's grep).

### 42. Tests and checks the code is missing

Closes: [IMP-03](improvements.md#imp-03-the-log-replay-test-cannot-catch-a-localhost-dashboard-write-that-forgets-its-log-event), [IMP-04](improvements.md#imp-04-admin-and-destructive-dashboard-paths-never-run-in-any-test-privacy-of-an-existing-group-moving-or-removing-a-team-skill-subscribing-and-console-errors-are-mostly-unchecked), [IMP-17](improvements.md#imp-17-no-static-check-guards-the-python-or-the-pages-1876-line-script-and-the-page-ships-an-untested-200-line-fake-backend), the Trivy image scan from [STD-07](industry-standards.md#std-07-nothing-scans-or-updates-dependencies-and-the-shipped-lock-pins-pyjwt-2130-which-has-14-published-advisories) (report-only until it has an allowlist), and the macOS job from [IMP-01](improvements.md#imp-01-the-windows-job-gates-neither-merging-nor-publishing-and-local-mode-then-updates-itself-from-pypi) (a `macos-latest` job running the Windows job's tests, in the publishing jobs' `needs`).
Largest effort among them: S.

Files: tests/mcp/test_library_log.py; tests/api/test_dashboard_over_http.py; pyproject.toml (ruff); .github/workflows/tests.yaml (ruff, `node --check` on the page's scripts).

ADR: none needed.

Tests: The replay test fails when a localhost-dashboard write forgets its event; admin and destructive dashboard paths each have an HTTP test; ruff and the script check run in CI.

### 43. Finish the security pass this audit could not

Closes: no single finding.
Largest effort among them: M.

This area got only a light pass in the audit, the one area that did.

Files: src/aistack/services/skill_archive.py, skill_validation.py, content_hash.py, local_skills.py; src/aistack/mcp/routes/transfer.py; both sync-aistack skills (their shell steps); src/aistack/bootstrap/self_update.py.

ADR: none needed.

Tests: A written review in docs/audits/ with crafted archives (confusables, case folding, pax tricks, a skill named like the staging folder), the install path under concurrent sync, and what `self_update` runs and from where.

## Every finding has a step

Every finding in the nine area files is closed by one of the steps above, except where a step says it only reduces it.
