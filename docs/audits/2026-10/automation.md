# Work users do that we could automate

Every step a person does by hand, or has to understand, in setup, adding a computer or an agent, moving a Library, recovering a lost laptop, joining a team, syncing, updating, and the operator's own tasks; with what the product could do itself instead.

How far this was checked: each finding below was reproduced or traced line by line by the auditor who raised it, and **Confirmed** means exactly that. The independent second pass that tries to refute each finding ran only for the authorization and UX findings: the account's weekly limit stopped the rest. Where the main session re-checked a finding itself, its entry says so. Treat **Suspected** findings, and anything marked High or Critical without a second pass, as needing a reproduction before the fix lands; the reproduction is described in each.

| Id | Finding | Severity | Status | Effort |
|---|---|---|---|---|
| [AUTO-01](#auto-01-local-setups-claude-mcp-add-fails-as-written-for-the-github-and-postgresql-choices) | Local setup's `claude mcp add` fails as written for the GitHub and PostgreSQL choices | High | Confirmed | S |
| [AUTO-02](#auto-02-on-a-server-a-person-cannot-cut-off-their-own-lost-or-stolen-computer) | On a server, a person cannot cut off their own lost or stolen computer | High | Confirmed | M |
| [AUTO-03](#auto-03-terminal-commands-silently-open-a-different-empty-library-unless-the-agents-settings-are-repeated) | Terminal commands silently open a different, empty Library unless the agent's settings are repeated | Medium | Confirmed | M |
| [AUTO-04](#auto-04-setup-and-both-sync-skills-run-claude-mcp-get-aistack-which-prints-the-machine-token-or-the-database-password-in-full) | Setup and both sync skills run `claude mcp get aistack`, which prints the machine token or the database password in full | Medium | Confirmed | S |
| [AUTO-05](#auto-05-after-moving-a-library-the-other-computers-stop-at-setup-step-1-and-quietly-stay-on-the-old-one) | After moving a Library, the other computers stop at setup step 1 and quietly stay on the old one | Medium | Confirmed | M |
| [AUTO-06](#auto-06-moving-a-library-is-a-hand-re-import-that-loses-history-placements-and-removals-though-publishing-the-existing-log-already-works) | Moving a Library is a hand re-import that loses history, placements and removals, though publishing the existing log already works | Medium | Confirmed | M |
| [AUTO-07](#auto-07-a-computer-on-an-upgraded-library-is-told-to-run-uv-tool-upgrade-by-hand-while-the-self-updater-sits-out-its-24-hour-wait) | A computer on an upgraded Library is told to run `uv tool upgrade` by hand, while the self-updater sits out its 24-hour wait | Medium | Confirmed | S |
| [AUTO-08](#auto-08-a-github-library-that-cannot-be-reached-or-whose-login-was-revoked-syncs-as-up-to-date-from-a-stale-copy) | A GitHub Library that cannot be reached or whose login was revoked syncs as 'up to date' from a stale copy | Medium | Confirmed | S |
| [AUTO-09](#auto-09-a-computer-connected-with-add_machine-is-never-offered-the-session-start-hook-and-a-codex-only-one-never-gets-the-sync-skill) | A computer connected with add_machine is never offered the session-start hook, and a Codex-only one never gets the sync skill | Medium | Confirmed | S |
| [AUTO-10](#auto-10-adding-a-computer-on-a-server-takes-four-hops-and-moves-a-permanent-token-between-machines-a-one-use-computer-invite-would-make-it-one-paste) | Adding a computer on a server takes four hops and moves a permanent token between machines; a one-use computer invite would make it one paste | Medium | Confirmed | M |
| [AUTO-11](#auto-11-running-setup-in-the-second-agent-on-an-already-connected-computer-registers-the-same-computer-twice-and-the-two-then-undo-each-other) | Running setup in the second agent on an already-connected computer registers the same computer twice, and the two then undo each other | Medium | Confirmed | S |
| [AUTO-12](#auto-12-local-setup-makes-the-agent-hand-assemble-five-config-edits-the-installed-program-could-make-itself) | Local setup makes the agent hand-assemble five config edits the installed program could make itself | Medium | Confirmed | M |
| [AUTO-13](#auto-13-the-documented-offboarding-leaves-a-team-whose-only-admin-left-with-no-admin-anyone-can-reach) | The documented offboarding leaves a team whose only admin left with no admin anyone can reach | Medium | Confirmed | M |
| [AUTO-14](#auto-14-the-documented-commands-generate-an-invite-code-the-operator-never-sees-and-restart-does-not-rotate-it) | The documented commands generate an invite code the operator never sees, and 'restart' does not rotate it | Medium | Confirmed | S |
| [AUTO-15](#auto-15-operator-tasks-are-python-copied-from-markdown-edited-by-hand-and-run-untested) | Operator tasks are Python copied from Markdown, edited by hand and run untested | Medium | Confirmed | M |
| [AUTO-16](#auto-16-an-upgrade-relies-on-the-operator-remembering-to-back-up-first-the-server-could-snapshot-sqlite-itself-before-migrating) | An upgrade relies on the operator remembering to back up first; the server could snapshot SQLite itself before migrating | Medium | Confirmed | S |
| [AUTO-17](#auto-17-behind-a-tls-proxy-without-aistack_public_url-the-server-silently-hands-out-http-addresses) | Behind a TLS proxy without AISTACK_PUBLIC_URL, the server silently hands out http:// addresses | Medium | Confirmed | S |
| [AUTO-18](#auto-18-a-server-mode-sync-makes-the-model-copy-every-file-digest-and-run-about-seven-commands-per-installed-skill) | A server-mode sync makes the model copy every file digest and run about seven commands per installed skill | Medium | Suspected | M |
| [AUTO-19](#auto-19-every-way-to-set-up-another-computer-in-local-mode-and-the-self-updater-depend-on-pypi) | Every way to set up another computer in local mode, and the self-updater, depend on PyPI | Medium | Confirmed | S |
| [AUTO-20](#auto-20-computers-cant-be-renamed-or-removed-and-a-reinstall-leaves-vm-and-vm-2-forever) | Computers can't be renamed or removed, and a reinstall leaves 'vm' and 'vm-2' forever | Low | Confirmed | M |
| [AUTO-21](#auto-21-joining-drops-the-name-the-person-gave-and-asks-questions-local-mode-answers-itself) | Joining drops the name the person gave and asks questions local mode answers itself | Low | Confirmed | S |
| [AUTO-22](#auto-22-the-invite-page-makes-an-existing-user-pick-the-code-out-of-a-setup-sentence) | The invite page makes an existing user pick the code out of a setup sentence | Low | Confirmed | S |
| [AUTO-23](#auto-23-an-agents-configuration-is-written-once-at-setup-and-never-updated-though-later-releases-changed-it) | An agent's configuration is written once at setup and never updated, though later releases changed it | Low | Confirmed | S |
| [AUTO-24](#auto-24-the-session-start-hook-runs-a-full-sync-at-every-startup-even-when-nothing-changed) | The session-start hook runs a full sync at every startup even when nothing changed | Low | Suspected | S |
| [AUTO-25](#auto-25-join-first-alone-is-an-operator-step-that-protects-nothing-today) | 'Join first, alone' is an operator step that protects nothing today | Info | Confirmed | S |

Many of the steps people take by hand could be done by the product, and several of the manual paths are broken, dead-end, or quietly do the wrong thing. Local setup asks the agent to assemble five config edits by hand. One of them, the `claude mcp add` for the GitHub and PostgreSQL choices, fails exactly as written. Terminal commands like `aistack-mcp dashboard` and `export` silently open a separate, empty Library unless the agent's settings are repeated. The troubleshooting steps tell the agent to run `claude mcp get`, which prints the machine token or the database password in full. Moving a Library, adding a second computer, and switching agents each have a path that ends at setup's "already connected, stop" step or registers the same computer twice. The same Library-moving path silently splits a person's computers across two Libraries. On a server, nobody can cut off their own stolen laptop: it takes the operator running a hand-edited Python script, and until then the thief's pushes reach the owner's other computers without a question. The operator's own jobs (rotating the invite code, offboarding someone, backing up before an upgrade, recovering a locked-out user) are copy-and-edit scripts or doc steps. Some of them don't work as described: "restart" does not rotate the code, and offboarding a team's only admin leaves the team with no admin anyone can reach. What already works well: GitHub sign-in reduced to one code, `sync-skill` writing its own file, the server's sync skill refreshing itself, and the event log every local Library records. A prototype showed that log can move a Library to GitHub in one step with history kept.

### AUTO-01: Local setup's `claude mcp add` fails as written for the GitHub and PostgreSQL choices

**Confirmed.** Severity **High**, effort **S**. Hurts: a newcomer choosing either Library option setup recommends for more than one computer, with Claude Code

**Where.** src/aistack/bundled/local/setup.md:69

**What is wrong.** Step 6 writes `claude mcp add --scope user -e AISTACK_LIBRARY_REPO='<owner>/aistack-library' aistack -- <aistack-mcp>`. In Claude Code, `-e, --env <env...>` takes any number of values, so it also takes `aistack` as an environment value. The command exits 1 with "error: missing required argument 'commandOrUrl'" and adds nothing. Choice 1 (no -e) works. README:310 admits setup's own `claude mcp add` was never run.

**How it was confirmed.** Claude Code 2.1.300 with a scratch HOME (agents/automation/claudehome): `claude mcp add --scope user -e AISTACK_LIBRARY_REPO='demo-owner/aistack-library' aistack -- /opt/fake/bin/aistack-mcp` → exit 1, and `claude mcp list` → "No MCP servers configured". With the name first (`claude mcp add --scope user aistack -e AISTACK_LIBRARY_REPO=... -- /opt/fake/bin/aistack-mcp`) → "Added stdio MCP server aistack", and ~/.claude.json holds the env. `claude mcp add --help` shows `-e, --env <env...>`, and its own example puts the name first.

**Proposed fix.** Put the name first in setup.md:69: `claude mcp add --scope user aistack -e AISTACK_LIBRARY_REPO='<owner>/aistack-library' -- <aistack-mcp>` (same for AISTACK_DATABASE_URL). Better, let the program run it (AUTO-12). Add a static test in tests/bootstrap that pulls every `claude mcp add` line out of src/aistack/bundled/**/*.md and checks that the server name comes before any `-e`, `--env`, `-H` or `--header` flag.

**Done when.** The documented line, run against Claude Code 2.1.x in a scratch HOME, leaves `aistack` in `claude mcp list`. The static test fails on today's setup.md and passes after the fix.

### AUTO-02: On a server, a person cannot cut off their own lost or stolen computer

**Confirmed.** Severity **High**, effort **M**. Hurts: anyone with two or more computers who loses one; their other computers are exposed until an operator acts

**Where.** src/aistack/api/dashboard.py:181-301 (no computer action); src/aistack/mcp/tools/onboarding.py:94-173 (add only); docs/OPERATING.md:127-158; src/aistack/services/sync_service.py:262-266

**What is wrong.** Computers can be added (`add_machine`) but never removed or given a new token by their owner: no tool and no dashboard action does it. The only way is for the operator to save a Python script from OPERATING.md, edit it and run it inside the container. Until then the stolen computer's token keeps working:
- It can push a new revision of any skill the owner has enabled, and each of the owner's other computers installs it on its next sync without asking (README sync table: "Enabled here, an older unmodified revision → Updated").
- It can open the dashboard.
README Known limits lists revoking as a script. But this leaves the user with nothing to do in the hours that matter, and on a server whose operator is away the window has no end. `machine_harness.last_synced_on` is written on every sync and read by nothing, so neither the user nor the operator's list script can see which computer has gone stale.

**How it was confirmed.** Read the route list in api/dashboard.py (181-301): only skill, account and team actions. grep of dashboard.html finds no rename, remove or revoke for a computer. The machine-scope tools include add_machine and nothing that removes a machine. grep for last_synced shows only the writes in sync_service.py:262-266. The auto-update behaviour comes from the reconciliation rows for desired=enabled with local=stale.

Re-checked by the main session: api/dashboard.py registers no machine route, and the dashboard has no control that removes or renames a computer.

**Proposed fix.** Add `onboarding_service.remove_machine(session, user_id, machine_id)`:
- It deletes the caller's own machine only. Someone else's machine, or an unknown id, gets NotFound with the same sentence.
- It refuses the caller's last computer: "Add another computer first, or ask whoever runs the server."

Expose it as `@_action('/machines/{machine_id}/remove', local=False)`, with a "Remove this computer" button on the computer's page. Its confirm text says the token stops working at once.

Also:
- Return `last_synced_on` per harness from `dashboard_service._machines` (dashboard_service.py:126) and show it.
- Optionally add "Reconnect this computer", which rotates the token and returns add_machine's command and Codex block (the operator's rotate script as a button for the owner).

Trade-off: a stolen dashboard session could remove the owner's other computers. The operator can undo that, and the stolen token can already push.

Local mode needs a `machine_removed` log event later. Release it as read-only first, then start writing it, per ADR-0024.

**Done when.** In tests/api/test_dashboard_over_http.py:
- After POST /api/machines/&lt;id&gt;/remove, that machine's token gets 401 on /mcp.
- Another user's machine id answers exactly like an unknown one.
- Removing the last computer is refused.

A UI test removes a computer by finding the button by its name.

Related: [AUTO-20](#auto-20-computers-cant-be-renamed-or-removed-and-a-reinstall-leaves-vm-and-vm-2-forever), [IMP-06](improvements.md#imp-06-the-dashboard-cannot-say-when-a-computer-last-synced-or-which-revision-it-holds), [IMP-09](improvements.md#imp-09-a-person-cannot-retire-revoke-or-rename-their-own-computer-only-the-operator-can), [PH-13](plot-holes.md#ph-13-owners-cannot-rename-or-remove-a-computer-and-nothing-shows-when-a-computer-last-synced), [SEC-01](security.md#sec-01-a-stolen-machine-token-outlives-the-documented-revocation-sibling-tokens-dashboard-sessions-and-upload-urls-keep-working), [STD-04](industry-standards.md#std-04-a-person-cannot-see-when-each-computer-last-connected-or-remove-a-lost-one-and-a-stolen-tokens-push-lands-silently-on-their-other-computers).

### AUTO-03: Terminal commands silently open a different, empty Library unless the agent's settings are repeated

**Confirmed.** Severity **Medium**, effort **M**. Hurts: local-mode users with a GitHub or PostgreSQL Library; anyone following the Move flow

**Where.** src/aistack/bundled/local/setup.md:103; src/aistack/bootstrap/configuration/settings/settings_config.py:109-159; src/aistack/bootstrap/__main__.py:76-172; src/aistack/bundled/local/sync-aistack/SKILL.md:15,59

**What is wrong.** Where the Library lives is stored only in the agent's MCP config, as `-e AISTACK_LIBRARY_REPO` or `AISTACK_DATABASE_URL`. `aistack-mcp dashboard`, `export` and `check` read only environment variables. Without them each one silently opens, or creates, `~/.aistack/aistack.db`: a separate this-computer Library. It registers the computer there and reports success.
- Setup step 8 tells the user "`aistack-mcp dashboard` in a terminal does the same without an agent". That is false for choices 2 and 3.
- In the Move flow, `export` reports "Exported 0 skills" if the agent leaves out the settings.
- To run these commands correctly, the agent is told to copy the settings out of `claude mcp get`, password included.

**How it was confirmed.** Ran in agents/automation/ghonly:
- `AISTACK_HOME=<scratch> AISTACK_LIBRARY_REPO=<bare repo standing in for GitHub> aistack check` → "Your Library lives in the GitHub repository …".
- The same command without the variable → "AIStack is ready. Your Library lives on this computer only.", and a new aistack.db appeared beside github-copy.db.
- `aistack export` without the variable → "Exported 0 skills", while the repository's Library holds 2.

**Proposed fix.** Have `check`, which setup already runs once with the place set, write the place to AISTACK_HOME, for example `library.json`:
- `{"kind":"github","repository":"owner/name"}`, `{"kind":"postgresql","host":…}` (never the password) or `{"kind":"this_computer"}`.
- `LocalSettings` falls back to it when no variable is set.
- If the variable and the file disagree, or the file says postgresql and no URL is set, refuse with one sentence instead of opening another Library.

Then terminal commands work with no settings, and the sync skill's step 0 and Move step 1 stop reading `claude mcp get`. A second agent's setup on the same computer can also reuse the place.

**Done when.** A test runs `check` with AISTACK_LIBRARY_REPO, then `check` and `export` without it:
- They report the same repository and create no aistack.db.
- With a conflicting variable, the command exits non-zero and names both places.

Related: [AUTO-05](#auto-05-after-moving-a-library-the-other-computers-stop-at-setup-step-1-and-quietly-stay-on-the-old-one), [AUTO-06](#auto-06-moving-a-library-is-a-hand-re-import-that-loses-history-placements-and-removals-though-publishing-the-existing-log-already-works), [PH-14](plot-holes.md#ph-14-readmes-move-to-a-teams-server-starts-with-an-export-that-cannot-see-a-github-or-postgresql-library-and-reports-exported-0-skills), [UX-18](ux.md#ux-18-the-move-here-dialog-says-the-same-thing-for-every-destination-wrong-for-only-this-computer-silent-on-history-and-restart).

### AUTO-04: Setup and both sync skills run `claude mcp get aistack`, which prints the machine token or the database password in full

**Confirmed.** Severity **Medium**, effort **S**. Hurts: every user who re-runs setup or troubleshoots a connection; the credential lands in the transcript and is often repeated to the user

**Where.** src/aistack/bundled/setup-aistack.md:19-33; src/aistack/bundled/skills/sync-aistack/SKILL.md:15; src/aistack/bundled/local/setup.md:9; src/aistack/bundled/local/sync-aistack/SKILL.md:15,59

**What is wrong.** Setup's "is it already set up" check and both sync skills' troubleshooting step tell the agent to run `claude mcp get aistack` and "say what it reports".
- In server mode that command prints the machine token in full, under Headers.
- In local mode with PostgreSQL it prints the whole AISTACK_DATABASE_URL, password included, under Environment.

The local sync skill then has the agent copy those settings onto a command line to run `check`. This contradicts setup's own "Never print it back in full" and AGENTS.md's rule that a token appears only in the join/add_machine result. `claude mcp list` answers the same question (is it there, does it connect) without showing either.

**How it was confirmed.** Claude Code 2.1.300, scratch HOME, fake values:
- After `claude mcp add --transport http … --header "Authorization: Bearer aist_FAKE…"`, `claude mcp get aistack` printed `Authorization: Bearer aist_FAKE…` in full. The add command itself printed [REDACTED].
- After `claude mcp add --scope user aistack -e AISTACK_DATABASE_URL='postgresql://demo:FAKEPASSWORD123@…'`, `claude mcp get aistack` printed the password.
- `claude mcp list` printed only the name, URL or command, and status.

**Proposed fix.** Wherever the question is "is it there" or "does it work", replace `claude mcp get aistack` with `claude mcp list`, and `codex mcp get` with `codex mcp list`. Add the sentence "do not run `claude mcp get aistack`: it prints the credential". For local troubleshooting, run `<aistack-mcp> check` with no settings once AUTO-03 lands. Add a test over src/aistack/bundled that fails when `mcp get aistack` appears.

**Done when.** No bundled file contains `mcp get aistack`, and the new test passes.

### AUTO-05: After moving a Library, the other computers stop at setup step 1 and quietly stay on the old one

**Confirmed.** Severity **Medium**, effort **M**. Hurts: someone with two or more computers moving between PostgreSQL and GitHub, or moving local mode onto a team's server

**Where.** src/aistack/bundled/dashboard.html:2203-2213; src/aistack/bundled/local/setup.md:9; src/aistack/bundled/setup-aistack.md:33; README.md:30; src/aistack/bundled/local/sync-aistack/SKILL.md:55-61

**What is wrong.** After the move, the dashboard says "Your other computers then need the same setup, pointed at the new place." On each of those computers, setup's step 1 finds `aistack` connected and stops: "this computer is already connected". So the computer stays on the old place. That place still works (a database or repository), and the computer keeps backing up to it. The person's computers are now split across two Libraries, and nothing says so.

The same step 1 stops README's move onto a team's server: server setup sees local mode's `aistack` and stops. Only the computer that runs the move is told to remove the old connection (sync skill "Moving the Library" step 2).

**How it was confirmed.** Read the text:
- local setup.md:9 and setup-aistack.md:33 stop on any connected `aistack`.
- dashboard.html:2211 sends the other computers to "the same setup".
- The local sync skill's lines 59-61 cover only the computer running the move.
- README.md:30 never says to remove the local-mode connection before connecting to a server.

**Proposed fix.** 1. In setup step 1 of both files: if `aistack` is connected and the user asked for a different place or a server, run `<aistack-mcp> check` (with AUTO-03, no settings needed) to see where it points. If that differs, say so, remove the old connection (`claude mcp remove --scope user aistack`, or replace the Codex table), and continue at step 2.
2. Make a move announce itself. The move records a `library_moved` event in the old Library, naming the new place (kind and repository or host, no secret). On a computer still on the old place, every tool then answers: "Your Library moved to &lt;place&gt; on &lt;date&gt;; set AIStack up again with that place to follow it." This is a new event kind: release it as read-only first, then start writing it, per ADR-0024.
3. Add the `claude mcp remove` step to README.md:30.

**Done when.** A local-mode test records a move in a SQLite or PostgreSQL Library; a second process on the old Library then gets the moved sentence from `sync`. A setup text test finds the "different place" branch in step 1 of both setup files.

Related: [AUTO-03](#auto-03-terminal-commands-silently-open-a-different-empty-library-unless-the-agents-settings-are-repeated), [AUTO-06](#auto-06-moving-a-library-is-a-hand-re-import-that-loses-history-placements-and-removals-though-publishing-the-existing-log-already-works), [PH-14](plot-holes.md#ph-14-readmes-move-to-a-teams-server-starts-with-an-export-that-cannot-see-a-github-or-postgresql-library-and-reports-exported-0-skills), [UX-18](ux.md#ux-18-the-move-here-dialog-says-the-same-thing-for-every-destination-wrong-for-only-this-computer-silent-on-history-and-restart).

### AUTO-06: Moving a Library is a hand re-import that loses history, placements and removals, though publishing the existing log already works

**Confirmed.** Severity **Medium**, effort **M**. Hurts: anyone moving from this computer or PostgreSQL to GitHub (the dashboard's Move here…)

**Where.** src/aistack/bundled/local/sync-aistack/SKILL.md:55-61; src/aistack/bootstrap/__main__.py:146-172; src/aistack/services/skill_service.py:383-396; docs/adr/0025-a-github-library-is-a-log-each-computer-replays.md:25

**What is wrong.** The documented move is: export, set up again, copy the folders into a skills folder, and let sync back them up. That way:
- Revision history is lost.
- Which computer had which skill is lost, so each other computer asks "manage it here?" for every skill.
- Every Library skill is installed on this computer.
- Skills removed from the Library come back. Export skips archived skills, the new Library has no archived marker for them, and sync backs up any such folder still on a computer without asking.

Yet every local Library already records its complete event log in library_event. ADR-0025 says "a Library can later move to GitHub by publishing what it already has".

**How it was confirmed.** Prototype in agents/automation/prototype_move.py:
- It read `library_log.unpublished()` from a copy of the scratchpad local2 this-computer Library: 7 events (machine_added, two skill_pushed, two skill_placed, two folder_synced).
- It published them with `LibraryRepo.publish()` into a bare repository standing in for GitHub.

drive_after_move.py then started local mode over stdio with AISTACK_LIBRARY_REPO set:
- list_skills returned both skills at revision 1.
- sync reported first_sync false (same computer, placements kept) and the same question about the locally edited `wizard` that the old Library gave.
- No skill folder was copied.

**Proposed fix.** Add `aistack-mcp move github|postgresql|this-computer`:
- github: sign in and find the repository (github_setup), refuse a repository whose log already holds another Library, then publish the current Library's events.
- postgresql: replay the events into the new database through `library_log.apply`, in one transaction.
- Then print the new agent settings (or write them, with AUTO-12).

Keep `export` for moving onto a team server. The sync skill's "Moving the Library" becomes one command and a restart.

**Done when.** A test moves a SQLite Library that holds a removed skill and two computers' placements to a stand-in repository. A second computer on that repository sees the same revisions and placements, and the removed skill stays removed: sync does not list its folder under backup.

Related: [AUTO-03](#auto-03-terminal-commands-silently-open-a-different-empty-library-unless-the-agents-settings-are-repeated), [AUTO-05](#auto-05-after-moving-a-library-the-other-computers-stop-at-setup-step-1-and-quietly-stay-on-the-old-one), [PH-14](plot-holes.md#ph-14-readmes-move-to-a-teams-server-starts-with-an-export-that-cannot-see-a-github-or-postgresql-library-and-reports-exported-0-skills), [UX-18](ux.md#ux-18-the-move-here-dialog-says-the-same-thing-for-every-destination-wrong-for-only-this-computer-silent-on-history-and-restart).

### AUTO-07: A computer on an upgraded Library is told to run `uv tool upgrade` by hand, while the self-updater sits out its 24-hour wait

**Confirmed.** Severity **Medium**, effort **S**. Hurts: someone with two computers, on the day one of them updates and changes the shared Library's schema or log

**Where.** src/aistack/bootstrap/context/application_context.py:105-112; src/aistack/services/library_log.py:103-106; src/aistack/bootstrap/__main__.py:64-69; src/aistack/bootstrap/self_update.py:48-50; docs/adr/0024-older-releases-keep-working-through-additive-upgrades.md:17

**What is wrong.** When another computer upgrades the shared Library beyond this release, local mode answers every tool with "Run `uv tool upgrade aistack-mcp` in a terminal, then restart your coding agent". The self-updater that could do this already starts on the same launch. But it returns early if it checked in the last 24 hours, and the timestamp is written before the check. So on the day a release lands, the person has to open a terminal. ADR-0024 still says "a restart is the fix in nearly every case" because setup used to run `uvx aistack-mcp@latest`; since setup moved to `uv tool install`, that is no longer true.

**How it was confirmed.** Traced the code:
- serve_local builds the context. With a refusal set, that function returns normally, and serve_local then calls self_update.start_in_background (__main__.py:64-69).
- check_and_upgrade returns None when the timestamp is younger than _CHECK_EVERY_SECONDS, before any version lookup (self_update.py:48-50).
- The refusal strings are at application_context.py:107-110 and library_log.py:103-106.

**Proposed fix.** When build_local_context sets a newer-schema or unknown-event refusal, start the update with `force=True`, which skips the 24-hour wait. The refusal then says: "AIStack is updating itself to read the Library another computer upgraded; restart your coding agent in a minute. If it still says this, run `uv tool upgrade aistack-mcp`." Do the same in `aistack check`. Amend ADR-0024's sentence.

**Done when.** In tests/bootstrap/test_self_update.py, `check_and_upgrade(force=True)` runs `uv tool upgrade` even when the timestamp is fresh. The application-context test shows the refusal naming the automatic update.

Related: [STD-08](industry-standards.md#std-08-every-build-calls-itself-010-so-adr-0024s-refusal-names-a-release-nobody-can-find), [STD-09](industry-standards.md#std-09-latest-is-every-commit-on-main-and-there-is-no-release-tag-or-changelog-to-stay-on), [STD-16](industry-standards.md#std-16-local-mode-installs-a-new-release-every-day-with-no-way-to-opt-out-or-pin-a-version).

### AUTO-08: A GitHub Library that cannot be reached or whose login was revoked syncs as 'up to date' from a stale copy

**Confirmed.** Severity **Medium**, effort **S**. Hurts: someone who follows README's lost-laptop advice (revoke GitHub CLI) or works offline; their other computers drift without a word

**Where.** src/aistack/services/library_sharing.py:28-41; src/aistack/mcp/tools/local.py:72-97; README.md:26

**What is wrong.** README's lost-laptop advice is to revoke GitHub CLI on github.com, which signs every computer out. After that, or when offline, the repository can't be reached. library_before_read then logs a WARNING to stderr and sync answers from the local copy. The sync result has no field for this, so the agent reports everything up to date while the copy may be days old. Only push_skill reports it, as `shared: false`. Nothing tells the person to run `aistack-mcp github` again.

**How it was confirmed.** Ran agents/automation/drive_after_move.py with the stand-in repository renamed away. stderr showed "The Library's repository could not be reached, so this computer works from its copy for now". The sync result's fields (install, update, backup, ask, team_updates, up_to_date, first_sync, folders, harness) said nothing about it.

**Proposed fix.** Have LibrarySharing.catch_up record the last failure. Local `sync` and `list_skills` then return `library_reachable` and a one-sentence `library_problem`.
- Signed out (`gh auth status` fails): "Run `<aistack-mcp> github` to sign in again; your changes wait on this computer until then."
- Otherwise, say the network could not reach the repository.

The tool description tells the agent to say it to the user. `aistack check` reports the same.

**Done when.** In test_library_github:
- With the remote unreachable, `sync` returns `library_reachable` false and a sentence.
- With a fake `gh` that reports signed out, the sentence names `aistack-mcp github`.

### AUTO-09: A computer connected with add_machine is never offered the session-start hook, and a Codex-only one never gets the sync skill

**Confirmed.** Severity **Medium**, effort **S**. Hurts: someone adding a second computer the recommended way; worst when Codex is the only agent there

**Where.** src/aistack/services/sync_service.py:172-174; src/aistack/mcp/tools/onboarding.py:94-173; src/aistack/bundled/setup-aistack.md:101-111; src/aistack/bundled/skills/sync-aistack/SKILL.md

**What is wrong.** The recommended way to add a second computer ("add my other computer") connects it with one pasted command.
- Only setup step 5 offers the session-start hook, so that computer never syncs by itself.
- A Codex-only computer never receives the `sync-aistack` skill. The server offers it only for Claude Code's folder, or when it is already in the agents folder.
- Without the skill, the first sync never offers the Library (that step lives only in the skill, which the `sync` tool points to). A new computer starts empty, so it gets nothing unless the person names skills one by one.

README's known limit about Codex-only computers is stale in wording, since add_machine now returns a Codex block, but still true in effect.

**How it was confirmed.** Ran agents/automation/probe_add_machine.py against my own server on port 8180:
- join, then add_machine('codex-only-box').
- With the new token, sync(harness='agents', local={}) → sync_skill_url null and first_sync true. A second call → null. With a local skill → null.
- sync(harness='claude_code') → URL set.

grep finds SessionStart only in the two setup files.

**Proposed fix.** Now:
- Add a first_sync step to the server's self-updating sync-aistack skill: "If ~/.claude/settings.json (or ~/.codex/hooks.json) has no AIStack SessionStart entry, offer it once", using setup's entry.
- Send add_machine's codex_config with the two commands that fetch the sync skill into ~/.agents/skills. The server's existing "already there" rule then keeps it current.
- Mention this in add_machine's description.

Longer term: AUTO-10.

**Done when.** A Codex-only computer added by add_machine has ~/.agents/skills/sync-aistack after following the returned text. A text test asserts that skills/sync-aistack/SKILL.md offers the hook on first_sync.

Related: [PH-06](plot-holes.md#ph-06-a-codex-only-second-computer-added-with-add_machine-never-gets-the-sync-skill-or-the-offer-of-the-library), [PH-15](plot-holes.md#ph-15-the-sync-tools-sync-skill-download-fails-on-exactly-the-computers-it-exists-for), [UX-07](ux.md#ux-07-a-second-computer-that-has-only-codex-never-gets-the-sync-skill-or-the-first-sync-library-offer-and-the-dashboard-shows-it-a-claude-code-folder-before-it-syncs).

### AUTO-10: Adding a computer on a server takes four hops and moves a permanent token between machines; a one-use computer invite would make it one paste

**Confirmed.** Severity **Medium**, effort **M**. Hurts: anyone with two computers; the operator recovering a locked-out user

**Where.** src/aistack/mcp/tools/onboarding.py:94-173; src/aistack/bundled/dashboard.html:1463-1470; docs/OPERATING.md:127-197

**What is wrong.** From the signed-in dashboard, adding a computer takes these hops:
1. Copy a sentence.
2. Say it to an agent on another computer that is already connected. It asks for, or guesses, the new computer's OS and agent, and returns a command holding a permanent token.
3. Carry that command to the new computer (chat, notes or email in between) and paste it into a terminal or config.toml.
4. Restart, then say sync.

The token sits in the first computer's transcript and in whatever carried it. The new computer skips everything setup does: the sync skill, the hook, the existing-connection check. The operator's recovery scripts print the same raw token, to send "over something private".

**How it was confirmed.** Counted from add_machine's description and result (onboarding.py:94-120), the dashboard dialog (dashboard.html:1464-1470, screenshot add-computer-desktop-light.png), README "For a second computer…", and OPERATING.md:127-158 and 180-197.

**Proposed fix.** Add a one-use, seven-day computer invite for the caller's own account, built like a team invite (ADR-0022): a row with a hashed `aistdev_` code.
- `add_machine`, or a dashboard button (`@_action('/machines/invite', local=False)`), returns `/invite/<code>`. That page gives the usual sentence: "Set up AIStack: fetch &lt;server&gt;/setup and follow it. Invite code: aistdev_…".
- `join` with that bearer registers a machine for the existing user. No username is asked; the new computer supplies its name and OS.
- The new computer then runs the whole setup.

Results:
- The token never leaves the computer that uses it.
- Codex or Claude Code is decided where it runs.
- The operator's recovery hands out a link instead of a token.

This needs an ADR amending ADR-0003 and ADR-0019 (a third kind of bootstrap bearer, under the same tag-based middleware rule).

**Done when.** An HTTP test shows a computer invite from user A, redeemed with `join`, creates a machine for A and no new user; it works once, expires, and can be cancelled. The dashboard's Add a computer dialog shows a link.

### AUTO-11: Running setup in the second agent on an already-connected computer registers the same computer twice, and the two then undo each other

**Confirmed.** Severity **Medium**, effort **S**. Hurts: a server user who switches from Claude Code to Codex (or back) on one computer

**Where.** src/aistack/bundled/setup-aistack.md:17-33,72

**What is wrong.** Setup's step 1 checks only the agent that is running. Run from Codex on a computer where Claude Code is already connected, it goes on to `join`. The username is taken, and setup sends the person to "add my other computer" from a connected computer, which registers this same computer a second time.

Both machine records then sync both folders, because each agent's sync-aistack syncs claude_code whenever ~/.claude exists, and each has its own desired state:
- Every Library skill is asked about again as undecided.
- A skill removed through one agent is reinstalled by the other agent's next sync ("Enabled here, not on disk → Installed").

Local mode is not affected: there the computer's identity is ~/.aistack/machine-id.

**How it was confirmed.** Read setup-aistack.md: step 1 runs only the running agent's own CLI, and step 3 handles a taken username by sending the person to add_machine. ADR-0018 and ADR-0021 set one token per computer. The conflict follows from the README sync table rows.

**Proposed fix.** - Step 1 checks both agents (`claude mcp list`, `codex mcp list`). If the other one is connected to this server, stop: "Claude Code on this computer is already connected and keeps Codex's folder current; say 'sync aistack' there."
- For someone who wants to talk to AIStack from both agents, add a step that copies the existing connection's header from one config file to the other without printing it (ADR-0018: a computer's agents share one token). Or use AUTO-10's invite with a same-computer flag.
- In the taken-username branch, first ask whether this computer is already connected through another agent.

**Done when.** A setup text test asserts that step 1 checks both agents. A manual Codex setup in a scratch home where Claude Code is already connected stops at step 1.

Related: [AUTO-21](#auto-21-joining-drops-the-name-the-person-gave-and-asks-questions-local-mode-answers-itself), [ENT-11](concurrency-and-reliability.md#ent-11-a-lost-join-response-locks-a-newcomer-out-of-their-username), [PH-09](plot-holes.md#ph-09-setup-step-1-stops-at-already-connected-for-any-aistack-connection-a-pasted-team-invite-is-dropped-and-another-server-or-local-mode-dead-ends), [PH-10](plot-holes.md#ph-10-a-setup-that-stops-after-join-locks-the-newcomer-out-the-re-run-refuses-the-used-invite-then-the-username), [UX-11](ux.md#ux-11-joining-asks-for-the-name-you-want-to-go-by-but-join-needs-a-lowercase-username-and-has-no-place-for-the-full-name), [UX-12](ux.md#ux-12-an-existing-user-who-pastes-the-invite-pages-setup-sentence-may-never-be-put-in-the-team-setup-has-no-branch-for-a-team-code).

### AUTO-12: Local setup makes the agent hand-assemble five config edits the installed program could make itself

**Confirmed.** Severity **Medium**, effort **M**. Hurts: every local-mode newcomer, on every OS; anyone moving a Library

**Where.** src/aistack/bundled/local/setup.md:20-95; src/aistack/bootstrap/__main__.py:175-208

**What is wrong.** For each OS, setup has the agent assemble these by hand:
- Find the program's own full path (`uv tool dir --bin`, plus the name, plus .exe on Windows).
- Quote the place for each shell.
- Run `claude mcp add` with its arguments in the right order. AUTO-01 shows how easily that goes wrong.
- Merge a table into ~/.codex/config.toml without duplicating it. A duplicate `[mcp_servers.aistack]` makes the whole file invalid, and the Move flow invites one.
- Merge a hook into ~/.claude/settings.json or ~/.codex/hooks.json, which means an LLM rewriting the person's settings file.

Count: 8 numbered steps, about 10 to 12 shell actions, 3 or 4 decisions, and one restart. `aistack sync-skill <folder>` already shows the pattern works: it replaced a file the agent used to write after the Windows UTF-16 bug.

**How it was confirmed.** Counted from setup.md; the AUTO-01 run.

**Proposed fix.** Add `aistack-mcp connect claude-code|codex [--hook]`. It runs with the same place `check` used, or the remembered one from AUTO-03, and does:
1. Runs `check`.
2. Writes sync-aistack into that agent's folder.
3. For Claude Code, runs `claude mcp add --scope user aistack [-e …] -- <its own absolute path>`, the path taken from sys.argv[0] or shutil.which.
4. For Codex, adds or replaces the table in config.toml and keeps everything else. Running it twice changes nothing.
5. With `--hook`, merges the SessionStart entry. Running it twice changes nothing, and it refuses to touch a file that is not valid JSON, saying so.

Setup steps 5 to 7 become one command. The agent still asks where the Library lives and whether to add the hook.

**Done when.** In tests/bootstrap:
- With a fake `claude` on PATH that records its arguments, `connect claude-code` passes the name before `-e` and an absolute path after `--`.
- Run twice on a config.toml with another server, `connect codex` leaves one aistack table and the other server untouched.
- The hook merge keeps existing hooks and does nothing the second time.

### AUTO-13: The documented offboarding leaves a team whose only admin left with no admin anyone can reach

**Confirmed.** Severity **Medium**, effort **M**. Hurts: the remaining members of a team; the operator

**Where.** docs/OPERATING.md:201-205; src/aistack/services/team_service.py:487-496

**What is wrong.** The "Someone left" procedure deletes the person's machines and rotates the server's code. Their team memberships stay, ADMIN included. Inside the product, leaving or demoting a team's last admin is refused (`_keep_an_admin`), but the operator procedure bypasses that check. A team whose only admin left can no longer, unless a member has can_invite:
- invite anyone,
- remove members,
- promote anyone,
- remove skills.

The remaining members cannot fix it, the doc says nothing, and the only remedy is hand-written SQL.

**How it was confirmed.** Ran agents/automation/probe_offboard.py against my own server:
- probe-lead2 created a team and invited probe-member2.
- The documented DELETE removed probe-lead2's machine.
- probe-member2's invite_to_team → "Only an admin of team 'probe-platform2', or a member an admin lets invite, can do that."
- list_teams still shows 2 members.

**Proposed fix.** Add `aistack admin offboard <username> [--hand-over <team>=<username> …]` (see AUTO-15), in a new services/operator_service.py that only the operator command can reach, never a tool or route. It:
1. Lists the person's teams.
2. Refuses while any team would be left with no admin anyone can reach, unless that team is handed over.
3. Removes the memberships.
4. Deletes the machines.
5. Reminds the operator to rotate the server's code.

Document it in OPERATING.md.

**Done when.** A service test: offboarding a sole admin without --hand-over is refused and names the team. With --hand-over, the named member is ADMIN and the leaver has no machines and no memberships.

Related: [AUTHZ-04](security.md#authz-04-the-team-keeps-an-admin-check-counts-first-and-writes-later-without-a-lock-on-postgresql-two-simultaneous-leaves-or-demotions-leave-a-team-with-no-admin), [AUTHZ-V01](security.md#authz-v01-offboarding-a-teams-only-admin-as-docsoperatingmd-says-leaves-the-team-with-an-admin-nobody-can-reach-and-no-way-to-name-a-new-one), [DB-05](schema.md#db-05-teams-can-be-left-with-no-admin-or-no-members-on-postgresql-the-last-admin-check-is-a-racy-count), [DB-07](schema.md#db-07-offboarding-a-teams-only-admin-leaves-the-team-permanently-unmanaged-and-no-operator-script-exists-to-repair-it), [ENT-01](concurrency-and-reliability.md#ent-01-two-admins-acting-at-once-on-postgresql-leave-a-team-with-no-admin), [PH-05](plot-holes.md#ph-05-taking-a-teams-only-admin-off-the-server-leaves-the-team-with-nobody-who-can-manage-it-and-operating-has-no-fix).

### AUTO-14: The documented commands generate an invite code the operator never sees, and 'restart' does not rotate it

**Confirmed.** Severity **Medium**, effort **S**. Hurts: the operator; teams on a server where someone left (the old code keeps admitting accounts)

**Where.** README.md:169-173; docs/OPERATING.md:8-13,21,27,30,228-230; compose.yaml

**What is wrong.** Every documented start command generates the code inline, as `-e AISTACK_INVITE_CODE="$(openssl rand -base64 24)"`, so it is never shown. The next paragraph says "write it down… there is no command that shows it afterwards", and the operator's very next step, joining first, needs it.

Rotation is documented as "Change AISTACK_INVITE_CODE and restart the container". But `docker restart` and `docker compose restart` reuse the environment the container was created with, so after someone leaves, the old code keeps admitting accounts. Going the other way, re-running the inline compose command on an upgrade silently rotates the code.

**How it was confirmed.** Read the commands and text. Docker fixes a container's environment when it is created; restart reuses it, and only recreating applies a change. No Docker daemon was available here to run it.

**Proposed fix.** - Accept `AISTACK_INVITE_CODE_FILE`, checked by `validate_invite_code` and never logged.
- Document generating the code once into a file the operator keeps, for example `openssl rand -base64 24 > invite-code.txt`, mounted read-only or placed in the volume.
- Rotation then becomes "write a new code to the file, then `docker restart aistack`".
- For the plain variable, OPERATING.md:228-230 says to recreate the container, not restart it.
- Note the change in DESIGN §9, which says the code comes "via env only".

**Done when.** test_settings_config: the server starts from AISTACK_INVITE_CODE_FILE and refuses a short code without echoing it. Following OPERATING.md's rotation steps against a container, the old code gets 401.

### AUTO-15: Operator tasks are Python copied from Markdown, edited by hand and run untested

**Confirmed.** Severity **Medium**, effort **M**. Hurts: the operator; users waiting on a recovery

**Where.** docs/OPERATING.md:101-230; README.md:347

**What is wrong.** Each operator task is: copy a Python block from the doc into a file, edit the names at the top, run `docker exec -i aistack python - < script.py`. When it produces a token, the operator carries it to the user, who runs two Claude Code commands. There is no Codex variant, and the result has no sync skill and no hook.

"Someone left" takes the list script, then the delete script once per machine with the names edited each time, then recreating the container with a new code. Seven scripts live only in Markdown and no test runs them, so AGENTS.md's "run a documented script against a real database before committing" depends on someone remembering.

**How it was confirmed.** Extracted the five Python blocks from OPERATING.md into agents/automation/opscripts/. Ran list, rotate, delete and list-teams against a copy of my server's SQLite database with DATABASE_URL set: all worked as written (token redacted in the output). grep: no test refers to them.

**Proposed fix.** Add `aistack admin machines|rotate|remove-machine|register-machine|teams|offboard|backup` subcommands in bootstrap/__main__.py, backed by a service module only the operator command can reach, opening the database through build_engine.
- rotate and register print a computer invite link (AUTO-10), or both the Claude Code command and the Codex block.
- machines shows the last sync per harness.

OPERATING.md shrinks to `docker exec aistack aistack admin …` lines. Server administration stays off the dashboard, as the known limit says.

**Done when.** tests/bootstrap/test_admin_cli.py runs every subcommand against SQLite and PostgreSQL, and OPERATING.md contains no Python blocks.

### AUTO-16: An upgrade relies on the operator remembering to back up first; the server could snapshot SQLite itself before migrating

**Confirmed.** Severity **Medium**, effort **S**. Hurts: the operator of a SQLite server; this-computer local Libraries upgraded by the self-updater

**Where.** docs/OPERATING.md:232-247,266-272,295; src/aistack/db/schema.py:68-90

**What is wrong.** An upgrade means: back up (two commands), pull, stop, remove, then re-run `docker run` with every original flag. "The way back from an upgrade you regret is the backup you took before it": if the operator forgot, there is none. At startup the server already knows whether migrations are pending, and it holds the SQLite file. A local this-computer Library upgraded by the self-updater has the same need.

**How it was confirmed.** Counted from the doc. migrate_schema only checks the current revision inside its transaction and copies nothing beforehand.

**Proposed fix.** In migrate_schema, before `connection.begin()`:
- When the database is SQLite and its revision is behind head, run `VACUUM INTO '<db folder>/aistack-before-<head>-<UTC time>.db'`. This runs outside any transaction and before the write lock. Keep the last three snapshots and log the path.
- On PostgreSQL, log one line recommending pg_dump.

Document `docker compose pull && docker compose up -d` as the upgrade path, so the flags live in a file.

**Done when.** test_schema: migrating a database from an older revision leaves a snapshot that opens at the old revision. A database already at head gets no snapshot.

Related: [PH-18](plot-holes.md#ph-18-operating-has-no-restore-procedure-no-guidance-for-a-new-server-address-and-a-recovery-script-that-crashes-on-a-typo), [STD-01](industry-standards.md#std-01-a-stopped-servers-data-lives-in-aistackdb-wal-and-the-obvious-restore-or-the-promised-upgrade-rollback-silently-restores-nothing).

### AUTO-17: Behind a TLS proxy without AISTACK_PUBLIC_URL, the server silently hands out http:// addresses

**Confirmed.** Severity **Medium**, effort **S**. Hurts: the operator of a VPS behind Caddy; users whose first token request goes out over plain http

**Where.** src/aistack/mcp/server_url.py:28-37; src/aistack/mcp/mcp.py:64-75; docs/OPERATING.md:52,66-78

**What is wrong.** uvicorn trusts X-Forwarded-Proto only from 127.0.0.1 by default. With Docker's published port, the proxy's connection usually arrives from the bridge gateway instead. The server then builds http:// URLs from the forwarded host name:
- the /setup page,
- add_machine's command (the token's first request goes to plain http, before any redirect),
- transfer links and dashboard links.

Nothing in the log says why. OPERATING.md asks the operator to remember AISTACK_PUBLIC_URL, but forgetting it is silent.

**How it was confirmed.** Against my own server on port 8180:
- `curl -H 'X-Forwarded-Proto: https' -H 'Host: aistack.example.com' http://127.0.0.1:8180/setup` → https URLs.
- The same with `--interface 127.0.0.2`, a peer that is not 127.0.0.1, standing in for the Docker gateway → `http://aistack.example.com/setup/sync-aistack/SKILL.md`.

That the Docker gateway is the source address is an assumption: no Docker daemon was available here.

**Proposed fix.** When AISTACK_PUBLIC_URL is unset and a request carries X-Forwarded-Proto, X-Forwarded-Host or Forwarded that uvicorn did not apply, log one WARNING per process: "Requests arrive through a proxy that says https, but AISTACK_PUBLIC_URL is not set, so this server hands out http:// addresses. Set AISTACK_PUBLIC_URL=https://&lt;host&gt;." Whether to also refuse to build commands in that state is for the security owners.

**Done when.** An HTTP test sends a forwarded header from an untrusted peer with no public URL set, and asserts the warning is logged once and contains no request path.

### AUTO-18: A server-mode sync makes the model copy every file digest and run about seven commands per installed skill

**Suspected.** Severity **Medium**, effort **M**. Hurts: every server user at every sync, including each session the hook starts; new computers most

**Where.** src/aistack/mcp/tools/sync.py:70-103; src/aistack/mcp/tools/skills.py:40-60,235-256; src/aistack/bundled/skills/sync-aistack/SKILL.md:36-70

**What is wrong.** In server mode:
- The agent hashes every file with shasum, then writes out every 64-hex digest as tool-call arguments.
- Each install or update is a get_skill call plus 6 or 7 shell commands: create the stage folder, clear it, curl, mkdir, tar, rm, mv, delete the archive.
- Each backup is a push_skill call plus tar, curl and delete.

README's measured run with 25 skills took 14 turns, about three minutes and $0.95. A first sync of a 25-skill Library on a new computer is about 25 tool calls and 150 commands, many of which Claude Code asks permission for. ADR-0010 keeps bytes out of tool arguments because model-generated text is slow and inexact; the same reasoning applies to digests. A mis-copied digest turns into a false "edited locally" question.

**How it was confirmed.** Counted from the tool descriptions and the skill; cost from README's "How the whole thing was verified". I did not observe a mis-copied digest, hence Suspected.

**Proposed fix.** Keep sync read-only (ADR-0006, ADR-0012), and:
1. Return a signed download URL with each `install` and `update` entry; those skills are already enabled, so no desired state changes. Or return one bundle URL holding all of them: one curl, one tar, then one move per skill.
2. Offer an observe ticket. `sync` called without `local` returns a five-minute upload URL; the agent pipes the shasum output to it with curl and gets the report back. The digests never pass through the model, and nothing is held on the server (ADR-0013).
3. On first_sync, include `in_library_elsewhere`, so the agent need not filter a full list_skills.

**Done when.** Over-HTTP tests:
- One sync with three missing skills returns one bundle URL, and installing from it produces the three folders byte for byte.
- A sync through the observe URL returns the same report as passing the same digests as arguments.

### AUTO-19: Every way to set up another computer in local mode, and the self-updater, depend on PyPI

**Confirmed.** Severity **Medium**, effort **S**. Hurts: a local-mode user adding a second computer or moving their Library today; any computer installed from a wheel or git

**Where.** src/aistack/bundled/dashboard.html:1462,1476-1485,2203-2212; src/aistack/bootstrap/self_update.py:24,54-58,65-69; src/aistack/bundled/local/setup.md:22-26; src/aistack/bootstrap/context/application_context.py:107-110

**What is wrong.** This follows from the package being missing on PyPI (already known):
- The dashboard's Add a computer dialog (GitHub and PostgreSQL) hands out `uvx aistack-mcp setup`, and its Move dialog leads to the same setup.
- Setup step 3 runs `uv tool install aistack-mcp`.
- The daily self-updater asks only pypi.org. A computer installed from a wheel or git, the only installs that work today, never updates. The failure is logged at INFO while the default log level is WARNING, so nobody sees it.
- Refusal messages tell the person to run `uv tool upgrade aistack-mcp`.

Someone whose first computer works has no sentence that works for the second.

**How it was confirmed.** Traced the strings and self_update.py, together with the PyPI 404 the main session already found.

**Proposed fix.** Publish the package (the pypi job needs a v-tag). Independently:
- Work out the install spec from the running copy: PEP 610 direct_url.json through importlib.metadata, or uv-receipt.toml.
- Use that spec in the dashboard's sentence (`uvx --from <spec> aistack-mcp setup`) and in setup step 3.
- Have self_update skip the PyPI lookup when the recorded source is not the package index, and let `uv tool upgrade` follow the recorded source.

**Done when.** For a copy installed from a wheel, the Add a computer sentence names that source. For a copy installed from git, self_update runs `uv tool upgrade` without querying pypi.org.

Related: [IMP-01](improvements.md#imp-01-the-windows-job-gates-neither-merging-nor-publishing-and-local-mode-then-updates-itself-from-pypi), [IMP-05](improvements.md#imp-05-setup-can-run-from-github-today-but-the-steps-it-prints-still-install-from-pypi-follows-from-the-known-missing-release), [LH-01](plot-holes.md#lh-01-local-mode-cannot-be-installed-aistack-mcp-is-not-on-pypi-and-no-release-has-ever-been-tagged), [STD-02](industry-standards.md#std-02-the-pypi-name-every-setup-sentence-runs-aistack-mcp-is-unregistered-and-anyone-can-take-it), [UX-10](ux.md#ux-10-the-dashboard-and-the-local-sync-skill-hand-out-uvx-aistack-mcp-setup-and-uv-tool-install-aistack-mcp-which-fail-today).

### AUTO-20: Computers can't be renamed or removed, and a reinstall leaves 'vm' and 'vm-2' forever

**Confirmed.** Severity **Low**, effort **M**. Hurts: someone with two Windows PCs, or who reinstalled or replaced a computer

**Where.** src/aistack/bootstrap/context/application_context.py:197-213; src/aistack/services/library_log.py:224-229; src/aistack/services/dashboard_service.py:126-147

**What is wrong.** Local mode names computers itself: "MacBook Pro M4 Pro" on a Mac, "Windows PC" for every Windows machine, the host name on Linux. A clash gets a "-2" suffix. A reinstall or a wiped ~/.aistack makes a new computer beside the old one.

No one can rename or remove a computer in either mode. So two Windows PCs read "Windows PC" and "Windows PC-2" forever, and old computers keep their placements. No last-synced time is shown to tell them apart.

**How it was confirmed.** Copied the scratchpad local2 Library, deleted its machine-id file, and ran `aistack check`. The machine table then held ('vm', LINUX) and ('vm-2', LINUX). api/dashboard.py has no rename or remove route.

**Proposed fix.** - A Rename action on a computer's page, `@_action('/machines/{id}/rename')`, through a service using the same name checks and per-user uniqueness. In local mode it records a `machine_renamed` event, released read-first per ADR-0024.
- Extend AUTO-02's remove action to local mode with a `machine_removed` event.
- Show the last sync per harness in the computer tree.

**Done when.** A UI test renames a computer by its label. A local-mode replay test carries the rename to a second computer.

Related: [AUTO-02](#auto-02-on-a-server-a-person-cannot-cut-off-their-own-lost-or-stolen-computer), [IMP-06](improvements.md#imp-06-the-dashboard-cannot-say-when-a-computer-last-synced-or-which-revision-it-holds), [IMP-09](improvements.md#imp-09-a-person-cannot-retire-revoke-or-rename-their-own-computer-only-the-operator-can), [LH-02](plot-holes.md#lh-02-a-home-folder-restored-onto-a-new-computer-makes-two-computers-one-the-machine-id-and-on-a-server-the-token-travel-with-it), [PH-13](plot-holes.md#ph-13-owners-cannot-rename-or-remove-a-computer-and-nothing-shows-when-a-computer-last-synced), [SEC-01](security.md#sec-01-a-stolen-machine-token-outlives-the-documented-revocation-sibling-tokens-dashboard-sessions-and-upload-urls-keep-working), [STD-04](industry-standards.md#std-04-a-person-cannot-see-when-each-computer-last-connected-or-remove-a-lost-one-and-a-stolen-tokens-push-lands-silently-on-their-other-computers).

### AUTO-21: Joining drops the name the person gave and asks questions local mode answers itself

**Confirmed.** Severity **Low**, effort **S**. Hurts: a newcomer joining a team

**Where.** src/aistack/mcp/tools/onboarding.py:56; src/aistack/bundled/setup-aistack.md:7-13; src/aistack/mcp/routes/invite.py:57-58; src/aistack/api/dashboard.py:215-218

**What is wrong.** The invite sentence says "Call me &lt;your name&gt;". Setup then asks for a lowercase handle and a computer name. The name the person gave is dropped, and they must type it again in dashboard Settings before teammates see it. Local mode already names the computer from its hardware; server setup asks instead.

**How it was confirmed.** `join(username, machine_name, os)` has no full-name parameter. `set_full_name` is reachable only through POST /api/account.

**Proposed fix.** Add an optional `full_name` to `join`, set through onboarding_service.set_full_name in the same transaction. Setup proposes a username from the given name, and names the computer the way local mode does, unless told otherwise. That makes one question ("OK to go by maria?") instead of three.

**Done when.** test_join_over_http: a join with full_name shows it among the team's members in /api/state. Setup's text asks at most for the invite code and a confirmation.

Related: [AUTO-11](#auto-11-running-setup-in-the-second-agent-on-an-already-connected-computer-registers-the-same-computer-twice-and-the-two-then-undo-each-other), [ENT-11](concurrency-and-reliability.md#ent-11-a-lost-join-response-locks-a-newcomer-out-of-their-username), [PH-09](plot-holes.md#ph-09-setup-step-1-stops-at-already-connected-for-any-aistack-connection-a-pasted-team-invite-is-dropped-and-another-server-or-local-mode-dead-ends), [PH-10](plot-holes.md#ph-10-a-setup-that-stops-after-join-locks-the-newcomer-out-the-re-run-refuses-the-used-invite-then-the-username), [UX-11](ux.md#ux-11-joining-asks-for-the-name-you-want-to-go-by-but-join-needs-a-lowercase-username-and-has-no-place-for-the-full-name), [UX-12](ux.md#ux-12-an-existing-user-who-pastes-the-invite-pages-setup-sentence-may-never-be-put-in-the-team-setup-has-no-branch-for-a-team-code).

### AUTO-22: The invite page makes an existing user pick the code out of a setup sentence

**Confirmed.** Severity **Low**, effort **S**. Hurts: a member invited to a second team

**Where.** src/aistack/mcp/routes/invite.py:56-67

**What is wrong.** For someone who already has an account, the page says to say "join a team with this code" "with the invite code above". But the code sits inside the setup sentence, so they copy the whole block or pick the code out by hand. The dashboard's own join dialog is not linked.

**How it was confirmed.** Read the page body in invite.py.

**Proposed fix.** Add a second copy block: "Join the AIStack team &lt;name&gt; with invite code aistinv_…". Add a link to `/app#/join` with the code in the URL fragment, which is never sent to the server or logged; it opens the dashboard's join dialog prefilled when the browser is signed in. Keep the existing CSP and referrer rules.

**Done when.** An invite-page test shows the second block. A UI test: a signed-in browser follows the link and joins with one click.

### AUTO-23: An agent's configuration is written once at setup and never updated, though later releases changed it

**Confirmed.** Severity **Low**, effort **S**. Hurts: Codex users set up before the list_skills approval or the startup timeout were added

**Where.** src/aistack/bundled/setup-aistack.md:85-97; src/aistack/bundled/local/setup.md:72-85; README.md:303

**What is wrong.** Setup writes the agent's config block once. Later releases changed it:
- The list_skills approval was added because Codex could not make the first-sync offer without it.
- local mode gained `startup_timeout_sec = 60`.

Computers set up earlier keep the old block, and nothing tells them. Yet the sync skill does update itself on every computer (sync_skill_url on a server, the local refresh in local mode).

**How it was confirmed.** README:303 records the change. No code and no skill step updates an existing config.

**Proposed fix.** Add a short step to both sync skills: in Codex, if the `[mcp_servers.aistack]` block lacks any of the current approval and timeout lines (listed in the skill), add them. Or, once AUTO-12 exists, have the skill run `connect codex`, which is safe to repeat.

**Done when.** A Codex config written before the change gains the list_skills approval after one sync (checked by hand). A skill text test lists the four approvals.

### AUTO-24: The session-start hook runs a full sync at every startup even when nothing changed

**Suspected.** Severity **Low**, effort **S**. Hurts: people who start many agent sessions a day

**Where.** src/aistack/bundled/local/setup.md:87-95; src/aistack/bundled/setup-aistack.md:101-111

**What is wrong.** The optional hook makes every new session sync before its first task. In server mode that is: list the folders, hash each one, two sync calls, and a summary. When nothing changed, those turns and seconds are spent for nothing. In local mode the program could answer the question itself, since it has the database and reads the folders in-process.

**How it was confirmed.** Read the hook text. Local sync reads the folders in-process (mcp/tools/local.py:72-97). The cost of a sync with nothing to do was not measured, hence Suspected.

**Proposed fix.** In local mode, make the hook command `<aistack-mcp> status --hook`. It prints the reminder only when sync would report something (install, update, backup, ask, or unseen GitHub events), and nothing otherwise. Keep the echo hook for server mode.

**Done when.** A test: `status --hook` prints nothing when the folder matches the Library, and one line after a skill is added.

### AUTO-25: 'Join first, alone' is an operator step that protects nothing today

**Confirmed.** Severity **Info**, effort **S**. Hurts: the operator

**Where.** docs/OPERATING.md:34; src/aistack/services/onboarding_service.py:149-172

**What is wrong.** The operator is told to "join first, alone, before you share the code: the first user to join becomes the server's admin". Nothing reads `is_admin` today except old migrations (0002, 0005), so the ordering rule costs a step and grants nothing.

**How it was confirmed.** grep is_admin across src/aistack: only the claim in onboarding_service, the model and its index, and migrations 0001, 0002 and 0005.

**Proposed fix.** Either drop the instruction until the admin flag grants something, or have the admin command (AUTO-15) and future admin buttons use it, and say what it grants.

**Done when.** OPERATING.md either says what the admin flag grants, or no longer has the sentence.

## Checked and holding up

- `aistack-mcp github` cuts GitHub sign-in to entering one code. The sign-in runs on its own, a re-run waits 90 seconds for approval, and it refuses a public repository (read bootstrap/github_setup.py).
- `aistack sync-skill <folder>` writes the skill file itself as UTF-8, so no agent writes it through a shell.
- The server's sync-aistack skill updates itself in Claude Code's folder through sync_skill_url (probe: set for harness claude_code).
- add_machine's command puts `--header` last, which Claude Code 2.1.300 reads correctly (scratch HOME, fake token).
- OPERATING.md's list, rotate, delete and list-teams scripts run as written against a copy of a real SQLite database (agents/automation/opscripts).
- A join refused for a taken username leaves the team invite usable, so the person can retry with another name (agents/automation/probe_invite_retry.py).
- In local mode, Claude Code and Codex on one computer share ~/.aistack/machine-id, so they count as one computer.
- Each local Library records a complete event log, and publishing it to a stand-in repository rebuilt the Library with its revisions and placements (agents/automation/prototype_move.py, drive_after_move.py).
- `aistack export` refuses a folder that already has files and writes through the same checks an install makes.
- My server's log held no `aist_` token after join, add_machine and invite probes.
- The invite page loads nothing from elsewhere (CSP), sends no referrer, and answers a wrong code exactly like any other; its sentence is built from the server's own address.
