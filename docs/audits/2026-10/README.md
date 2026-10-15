# AIStack audit, October 2026

An audit of `main` at `ac40dcb` from every angle: plot holes, security, the schema, industry practice, automation, UX, the UI, concurrency, and anything else worth doing. It ends in [PLAN.md](PLAN.md), the work as 43 pull-request-sized steps in order, and a design for the next feature, skill folders inside projects ([ADR-0026, proposed](../../adr/0026-skills-folders-inside-projects.md)).

## In short

AIStack's core holds up. Tokens and invite codes are stored only as hashes and compared the right way, nothing secret reached a log in a full debug run, a team you are not in is indistinguishable from one that does not exist, push validation stops every hostile archive the tests throw at it, and all 1,422 tests pass on SQLite and PostgreSQL.

The problems are at the edges of those designs, where a person's real life meets the product:

- **A newcomer cannot get in the way the README says.** Local mode is installed from PyPI, and `aistack-mcp` has never been published there. Anyone could register the name first, and every setup sentence would then run their code.
- **Taking people out does not take them out.** A removed team member's invite links still work, and can create new accounts. A stolen laptop's token keeps its dashboard sessions, its upload links, and any computers the thief added, even after the operator follows the documented runbook. The owner of the laptop cannot do anything about it themselves.
- **Some states have no way back.** A team whose last admin is gone, a team made by mistake, or a skill quietly replaced when you took a team skill with the same name as one of yours. Your history keeps the old revision, but nothing can bring it back.
- **The server is safe on one database and racy on the other.** SQLite's single write lock hides check-then-write races that PostgreSQL exposes. Two admins acting at once can leave a team with no admin. On SQLite, the same lock makes every read wait, so the server slows down and starts failing as it grows.
- **Operations are documents, not tools.** Backups work, but restoring one is undocumented and the obvious way silently restores nothing. Every build calls itself 0.1.0, and the operator's tasks are Python pasted from Markdown.

## Top ten things to do

| # | Do this | Why | Findings | Plan step |
|---|---|---|---|---|
| 1 | Publish `aistack-mcp` to PyPI, and until then point every install sentence at the repository | The README's first instruction fails for every newcomer, and the unclaimed name is a supply-chain hole waiting to be used | [LH-01](plot-holes.md#lh-01-local-mode-cannot-be-installed-aistack-mcp-is-not-on-pypi-and-no-release-has-ever-been-tagged), [STD-02](industry-standards.md#std-02-the-pypi-name-every-setup-sentence-runs-aistack-mcp-is-unregistered-and-anyone-can-take-it) | 1 |
| 2 | Make an invite die with its maker's right to invite | A removed or demoted member can rejoin, or let strangers into the team, with links made earlier | [AUTHZ-01](security.md#authz-01-removing-demoting-or-offboarding-an-inviter-leaves-their-invite-links-working-so-the-person-can-rejoin-the-team-or-create-a-new-account-on-the-server) | 4 |
| 3 | Bind sessions and tickets to the computer that opened them; let a person remove their own computer | A lost laptop stays in the account after the documented revocation, and only the operator can act | [SEC-01](security.md#sec-01-a-stolen-machine-token-outlives-the-documented-revocation-sibling-tokens-dashboard-sessions-and-upload-urls-keep-working), [AUTO-02](automation.md#auto-02-on-a-server-a-person-cannot-cut-off-their-own-lost-or-stolen-computer), [STD-03](industry-standards.md#std-03-a-dashboard-session-cannot-be-ended-not-by-signing-out-and-not-by-deleting-the-machine-that-opened-it) | 8, 9 |
| 4 | Never let taking a team skill replace an unrelated skill of yours without asking | It replaces your skill on every computer at their next sync, and nothing brings it back | [PH-01](plot-holes.md#ph-01-taking-a-team-skill-whose-name-matches-one-of-your-own-silently-replaces-yours-on-every-computer), [UX-V01](ux.md#ux-v01-add-to-library-on-a-team-skill-named-like-an-unrelated-skill-of-your-own-replaces-yours-on-every-computer-with-no-warning-and-the-toast-says-added) | 10 |
| 5 | Lock the team row while admins and members change; let a team be deleted | On PostgreSQL a team can end with no admin, and a team made by mistake can never go away | [ENT-01](concurrency-and-reliability.md#ent-01-two-admins-acting-at-once-on-postgresql-leave-a-team-with-no-admin), [AUTHZ-V01](security.md#authz-v01-offboarding-a-teams-only-admin-as-docsoperatingmd-says-leaves-the-team-with-an-admin-nobody-can-reach-and-no-way-to-name-a-new-one), [AUTHZ-05](security.md#authz-05-the-only-member-of-a-team-can-never-leave-it-and-no-team-can-be-deleted-the-pages-own-demo-lets-them) | 5, 6 |
| 6 | Ship backup and restore commands, and test a restore in CI | The restore an operator reaches for after a bad upgrade, the one ADR-0024's refusal sends them to, silently does nothing | [STD-01](industry-standards.md#std-01-a-stopped-servers-data-lives-in-aistackdb-wal-and-the-obvious-restore-or-the-promised-upgrade-rollback-silently-restores-nothing) | 12 |
| 7 | Fix local setup's `claude mcp add`, and stop running `claude mcp get` | The command for GitHub and PostgreSQL Libraries fails as written, and the troubleshooting step prints the token or database password into the chat | [AUTO-01](automation.md#auto-01-local-setups-claude-mcp-add-fails-as-written-for-the-github-and-postgresql-choices), [AUTO-04](automation.md#auto-04-setup-and-both-sync-skills-run-claude-mcp-get-aistack-which-prints-the-machine-token-or-the-database-password-in-full) | 3 |
| 8 | Bump PyJWT, pin CI actions by commit, add Dependabot | 14 published advisories on the locked PyJWT (one applies, mildly), and the jobs that publish run actions by tags their owners can move | [STD-07](industry-standards.md#std-07-nothing-scans-or-updates-dependencies-and-the-shipped-lock-pins-pyjwt-2130-which-has-14-published-advisories), [PUSH-01](security.md#push-01-the-jobs-that-hold-publishing-credentials-run-third-party-actions-by-moving-tags-and-an-unpinned-poetry) | 2 |
| 9 | Scope the dashboard's and sync's queries to the caller, and let reads skip SQLite's write lock | Every page load counts the whole server's revisions while holding the only write lock; at about a gigabyte, refreshes fail with "database is locked" | [DB-01](schema.md#db-01-dashboard-list_skills-and-sync-count-every-revision-and-file-on-the-whole-server-for-each-request-under-sqlites-write-lock), [ENT-04](concurrency-and-reliability.md#ent-04-on-sqlite-every-read-waits-for-the-global-write-lock-past-5-s-auth-fails-with-a-bare-http-500-tools-fail-as-failed-unexpectedly-and-health-returns-503), [SEC-04](security.md#sec-04-unauthenticated-requests-take-sqlites-write-lock-token-checks-health-and-the-invite-page-all-run-begin-immediate) | 13, 14 |
| 10 | Order a GitHub Library's log by a hybrid clock | One computer with a fast clock makes the others keep its older edit and silently drop the newer one | [ENT-03](concurrency-and-reliability.md#ent-03-local-mode-orders-the-library-log-by-wall-clock-so-a-computer-whose-clock-runs-ahead-makes-copies-diverge-and-a-rebuild-silently-replaces-a-newer-edit) | 19 |

Next in line: a member who can only see a group can write into it by sharing without naming it ([AUTHZ-02](security.md#authz-02-a-member-who-can-only-see-a-group-an-open-groups-non-member-or-a-sees-all-groups-member-can-push-a-new-revision-into-that-groups-skill-by-sharing-without-a-group)), there is no rate limit on any credential ([SEC-02](security.md#sec-02-no-rate-limit-or-lockout-on-any-credential-check-and-the-invite-code-strength-check-accepts-trivially-guessable-codes)), and the desktop tables overlap between 821 and about 900px wide, where an iPad sits in portrait ([UI-01](ui.md#ui-01-between-821-and-900px-the-desktop-library-and-groups-tables-overlap-themselves-ipad-pro-11-portrait-834px)).

## The two questions asked during the audit

**Should the Library be hidden until its storage is set up?** No. Nudge instead ([UX-P01](ux.md#ux-p01-a-library-kept-on-this-computer-only-is-never-shown-as-at-risk-propose-a-nudge-not-a-gate)). There is no "not set up" state: setup asks where the Library lives before the dashboard can open, and "only this computer" is a real choice, a small SQLite file in `~/.aistack`. The Library is also the screen where the first backups appear and the product starts to make sense. The proposal: a dismissible notice while the Library lives only on this computer and holds skills, the hard stop that Add a computer already has, and a one-step `aistack move github` that keeps history ([AUTO-06](automation.md#auto-06-moving-a-library-is-a-hand-re-import-that-loses-history-placements-and-removals-though-publishing-the-existing-log-already-works)), so the notice is something people act on.

**Is the UI cluttered with text?** In places ([UI-23](ui.md#ui-23-explanations-sit-on-the-page-where-one-line-and-a-click-would-do-dialogs-footnotes-and-zero-value-tiles-clutter-the-screens-people-open-most)). Dialogs explain before they act, notes under tables repeat what their confirmations say, and three stat tiles say "0, everything is fine" on a normal day. The fix is one rule for the design system: one short line on the surface, the explanation one click away.

## The next feature: skill folders inside projects

[ADR-0026 (proposed)](../../adr/0026-skills-folders-inside-projects.md) and [projects-design.md](projects-design.md):

- **What a project is.** A project is a git repository, known by its normalised remote, so two clones on two computers are one project.
- **Folders.** Its folders are `<top level>/.claude/skills` and `<top level>/.agents/skills`, the two harnesses one level down.
- **What AIStack may touch.** AIStack writes only what git ignores. It never touches a skill the repository tracks, and it keeps its own folders out of git through `.git/info/exclude`, never `.gitignore`.
- **Choosing projects.** A project is managed once its owner says "add this project to aistack" inside it, never by scanning the disk.
- **Schema.** Placements go in three new tables, so `machine_skill` and every older release's reading of it stay unchanged.
- **Upgrades.** New log event kinds ship in a release that can read them before any release writes them. Without that, today's release would apply a project placement as a global one.

It sits in the middle of the plan (phase 6). It needs releases that computers actually update to, and a log that cannot reorder edits, first.

## The files

| File | What it covers | Findings |
|---|---|---|
| [security.md](security.md) | Sign-in, sessions, secrets, authorization, the build and dependencies | 23 (2 High) |
| [concurrency-and-reliability.md](concurrency-and-reliability.md) | Races on SQLite and PostgreSQL, errors under load, retries, restarts, limits, clocks | 13 (1 High) |
| [schema.md](schema.md) | Constraints, indexes, parity, migrations, upgrades, query cost | 15 (1 High) |
| [plot-holes.md](plot-holes.md) | Dead ends, unkept promises, two computers, two releases, two modes | 20 (1 Critical, 2 High) |
| [industry-standards.md](industry-standards.md) | Backups, sessions, releases, dependencies, logs, deployment, accessibility, i18n, each against a named standard | 20 (3 High) |
| [automation.md](automation.md) | Every step a person does by hand, and what the product could do instead | 25 (2 High) |
| [ux.md](ux.md) | Wording, flows, empty states, errors, what the agent says | 20 (1 High) |
| [ui.md](ui.md) | The design system, accessibility, responsive layout, both themes, and the screens as audited | 23 (1 High) |
| [improvements.md](improvements.md) | Tests, code health, performance, docs drift, cheap features | 18 (1 High) |
| [PLAN.md](PLAN.md) | 43 steps in order, each with its findings, files, ADR and tests | |
| [projects-design.md](projects-design.md) | The project-folders design in detail | |

177 findings: 1 Critical, 14 High, 81 Medium, 75 Low, 6 Info. 173 are Confirmed and 4 Suspected. Each has where, what, how it was confirmed, severity and who it hurts, the fix, the effort, and how to know it is done. Related findings in other files link to each other. Seven ADR drafts are in `docs/adr/` (0026 to 0032), all proposed.

## How the audit was done, and its limits

- **Ran the product as a newcomer.** The server came from source, filled with `scripts/demo_seed.py`. Local mode ran with `aistack check`, `aistack dashboard` and its MCP tools over stdio, in a scratch `HOME` and `AISTACK_HOME`. The dashboard was driven with Playwright in Chromium at 1440 and 390 px, in light and dark, with axe-core on every screen. All data is demo data; one screenshot showed a throwaway server's invite code and has it blacked out.
- **Read the documents and the code.** AGENTS.md, CONTEXT.md, README.md, DESIGN.md, the design system and every ADR first, then the code. Each area was audited on its own. Every race was driven to its exact window with a `threading.Barrier` on SQLite and PostgreSQL 16, and query costs were measured on databases seeded up to about a gigabyte. The probe scripts and tests are described in each finding and were not committed.
- **Second pass.** Each area was meant to get an independent pass that tries to refute every finding. That pass ran only for authorization and UX, which is where the dropped and corrected findings come from. There was no time for the rest. Several High findings were re-checked separately (each says so), one was corrected (STD-01), and two areas got only a lighter pass:
  - the push and dependency pass (the dependency scan, CI and container basics);
  - local mode (installation, and a computer restored from a backup).

  The remaining deep pass on archive validation, the install path and `self_update.py` is the last step of the plan. Before fixing a High or Critical finding that had no second pass, reproduce it first; each finding says how.
- **Tests on this commit:**
  - 1,422 passed and 74 skipped on SQLite and PostgreSQL.
  - The browser tests pass in Playwright's headless shell. In a full Chromium, 19 of 38 fail on the missing favicon ([UI-22](ui.md#ui-22-no-icon-is-declared-so-every-page-load-asks-for-faviconico-gets-404-and-the-browser-tests-fail-in-a-full-browser)).
