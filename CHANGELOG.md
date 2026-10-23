# Changelog

One section per release, written when the release is cut, in the form of [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions follow [Semantic Versioning](https://semver.org/) below 1.0: a new patch release works beside the one before it, and a new minor (0.1 to 0.2) is one that older releases stop working with. Each minor's section opens with **Upgrade notes** that say what to do first.

The image tag `0.1` follows the releases of 0.1, and the package on PyPI is `aistack-mcp`. The tag pipeline publishes a release only when this file has a section for it, and uses that section as the GitHub Release's notes.

## 0.1.2 (2026-10-23)

Works beside 0.1.1: computers and servers on either release can share one database while they update. This release adds rules beside skills, organises the dashboard by project, and starts a coding agent with only the skills you choose.

### Upgrade notes

- Schema changes run at startup. On SQLite the server keeps a copy of the database from before the upgrade; on PostgreSQL, take a backup first.
- Run `aistack admin` from the upgraded server for recovery, offboarding and forgetting. An older release's `offboard` or `forget` does not know about computer codes and can leave a recovery code usable. Computers on older releases keep working.
- A computer still on 0.1.1 that shares a GitHub Library with one on 0.1.2 pauses reading that Library at the first rule change, and catches up with nothing lost once it updates itself, within a day ([ADR-0039](docs/adr/0039-local-mode-writes-rules-in-the-release-that-adds-them.md)).

### Added

- Rules, beside skills ([ADR-0036](docs/adr/0036-rules-are-the-second-resource.md)). Your rules for every project and your rules for one project are kept in the Library with their history, edited on the dashboard, and synced to every computer: Claude Code's `CLAUDE.md` and `.claude/rules/`, and Codex's `AGENTS.md` and `AGENTS.override.md`. A file you already wrote by hand is backed up as a rule at the first sync. Your rules for a project are written only to files git ignores, never to a file the repository tracks. A line that looks like a credential is pointed out before it is saved.
- A repository's own rule files show on its project's page. Turn one off for yourself without changing it for anyone else, or edit it on the page: the edit is written into your working copy, the page shows what it changes, and **Commit…** shares it with a note as a branch holding only that file, and a pull request when `gh` is signed in. Your working tree, index and branches are left as they were.
- The dashboard is organised by project ([ADR-0037](docs/adr/0037-the-page-is-organised-by-project.md)). The sidebar lists Library, Every project, Projects and Computers, with the computer you opened the page from marked "This one". A project's page shows each computer that has it and one table of its rules and skills with a column per coding agent; a tick turns one on or off for that agent on every computer. A **+** on each heading and item opens what can be added there.
- Add a project by its folder. **Projects → + → A folder on this computer…** looks inside the folder and shows a checklist of the agent files and other Markdown files git tracks, with the agent files ticked, and the repository's own skills. At the terminal, `aistack project add <folder>` does the same.
- Start Claude Code or Codex in a project with only the skills you choose, so the agent reads three skill descriptions instead of a hundred. **Start an agent…** on a project's page opens a terminal in one click in local mode; on a server it offers an `aistack://` link that opens one on this computer, or the command to copy ([ADR-0038](docs/adr/0038-the-page-asks-the-program-to-act-on-a-computer.md)). The program always says what it will start and waits for Enter. Needs Claude Code 2.1.169 or Codex 0.163 or later.
- `aistack start --agent claude-code|codex --skills a,b` starts an agent the same way from the terminal, in the current repository or one named with `--project`, and `--new-terminal` opens a new window for it. Your settings are not changed.
- `aistack link` registers the `aistack://` link on this computer, `aistack link remove` takes it off, and `aistack check` says whether it is in place. Setup and `aistack join` register it for you.
- A manual `aistack sync` covers every project you manage on this computer, not only the one it runs in, and groups what it says by project. The session-start hook still covers the session's own project.
- Connect another computer with a one-use code instead of carrying its permanent key ([ADR-0035](docs/adr/0035-the-program-does-the-mechanical-work.md)). **Computers → Add a computer** on the dashboard makes the code and the command to run on the new computer, `uvx aistack-mcp join <server> <code>`, and you approve the request it starts in the same dialog. A code works once and lasts 24 hours, or 1 hour or 7 days if you choose; its options set the name, the agents, an empty start, the session-start hook, and whether approval is needed. Codes in use are listed under Computers with their expiry and a Cancel code button. In chat, `add_machine(computer_code=true)` makes one.
- The `aistack` program on each computer does the mechanical work itself. `aistack join` installs AIStack, configures the agents it finds, installs your Library's skills and runs the first sync, and picks up where it stopped when run again. `aistack sync` on a server connection downloads, installs and backs up skills and rules, and leaves local edits, disabled skills and team offers for your agent to ask about. Setup can run `aistack sync --hook` at session start, which says nothing when nothing needs attention.
- A computer's connection can carry a fingerprint of its operating system's computer id. A connection copied onto another computer, as when a home folder is restored there, is refused before sync touches a skill folder; that computer gets its own code. Older clients that send no fingerprint are still accepted.
- Operators: `aistack admin register-machine <username> --computer-code` makes a one-use recovery code, valid for 24 hours and without approval, for someone with no computer left.
- `aistack --version` prints the release.

### Changed

- The signed-out page says in one line what AIStack is and offers two ways in: "I have AIStack on this computer" and "I'm new here". It and the invite pages share the dashboard's look, follow the system's light or dark theme, read at phone width, and have a Copy button beside every sentence to paste.
- The demo data uses names people use: computers such as "MacBook Pro M4 Pro" and "Work desktop", teams demo-team and side-projects, and projects demo-api and demo-website.
- Setup for a first computer installs the program and points the session-start hook at `aistack sync --hook` by its full path, in place of the old reminder line.
- `add_machine` with a name and an operating system, and `register-machine` with a computer name and `--os`, still return permanent-token setup for older callers, until a future minor release.
- Removing the computer that made a code, or rotating its token, cancels the code and its request. Offboarding and forgetting someone cancel their pending codes and requests, recovery codes included.
- Sign out shows its word beside the icon, the local Move dialogs are shorter, and removing a member says that the invite links they made stop working.
- The dashboard says when a computer acts as "the next time it syncs", a skill no team has as "Not shared", and a code's expiry as "tomorrow at 04:49". A computer's agents sit on the line under its name, and a success message leaves after eight seconds unless it is pointed at or focused; an error stays until dismissed.
- Both setup texts say which files setup changes on the computer, and that the `aistack://` link is registered, where, and how to remove it.

### Fixed

- A setup that was denied, expired or lost its key starts over from a new code instead of resuming the old request, and a computer removed on the dashboard can join again.
- One refused skill no longer stops sync for every other skill, and a second session starting at the same time waits up to 20 seconds for the first sync instead of skipping its project folder.
- Running `aistack join` again on a connected computer sets up its agents and hook again. The program is installed before the code is used, so a computer without uv no longer leaves a request waiting. A team update offered by several folders is listed once.
- A hook installed after accepting a public server over plain HTTP no longer refuses that server at every session start, and the plain-HTTP warning and the missing computer id note appear only in a manual sync.
- Focus stays in the Add a computer dialog while it refreshes, and moves to the next button when an action removes the one it was on.
- An admin saw a private group they are not in as an empty one, with a Subscribed switch the server refused and a place in the share picker. It now reads as private, and Team Settings says an admin sees its skills only from inside it or with sight of every group.
- A team invite code sent again by the person who used it, after the answer was lost, names the team again instead of being refused and counted as a failed attempt.
- The invite tool told members an admin lets invite that they could not, and the sync skill's manual hook step could add a second hook beside the program's.
- An install writes its files to disk before it replaces the old folder, so a power cut cannot leave a skill with empty files.
- A failed self-update in local mode is logged as a warning, without uv's output.
- `aistack check` on a computer connected to a server said the Library lived on this computer and set one up. It now signs in with the computer's key and names the server, or says why it cannot, and sets up nothing.
- `aistack project add` in local mode asked for Enter and then failed. It now says first that the dashboard looks inside the folder itself.
- A sync, a join or a project add that failed on the network said only that it could not finish. It now gives the cause in one line, never an address or a key.
- Every page title drew a focus ring that looked like a text field, and the sidebar's + menu opened under the list of teams beside it, its heading cut off.

### Security

- A code and the request it starts each carry a credential of their own, and the new computer's permanent key reaches it only through the program, kept in a protected file until setup finishes. A refused code is throttled like any refused credential.
- Replaying a Library's log places a skill only on the person's own computers, as it already did for project folders.
- A refused server address is no longer repeated in the error that refuses it.
- certifi 2026.10.19 fixes GHSA-6q48-6c7w-9gw2, and opentelemetry-api 1.45.1 fixes CVE-2026-114603.

## 0.1.1 (2026-10-19)

Works beside 0.1.0: computers and servers on either release can share one database while they update.

### Upgrade notes

- **The server's invite code now needs at least 24 characters, 10 of them different, and may not be an example from AIStack's own documents.** A server whose code is shorter refuses to start and says why. Generate a new one with `openssl rand -base64 24` before upgrading, and give it to anyone who has not joined yet. It can also come from a file, `AISTACK_INVITE_CODE_FILE` (docs/OPERATING.md).
- Five schema changes run at startup. On SQLite the server now keeps a copy of the database from before every upgrade; on PostgreSQL, take a backup first.
- `latest` is now the newest release only. Builds of `main` are published as `edge` and `sha-<commit>`. The commands in the README and docs/OPERATING.md run `:0.1`, which follows the releases of 0.1.
- Local mode now updates itself only within 0.1. `AISTACK_AUTO_UPDATE=off` in the agent's settings for AIStack turns it off.

### Added

- Remove and rename your own computers from the dashboard, and see when each one last synced and which computer added it.
- A home folder restored onto another computer becomes a computer of its own in local mode, instead of sharing the old computer's identity.
- Download your whole Library from Settings.
- Skills folders inside a repository (server mode): add a project to a computer, place skills in it, and see every project in the computer tree with a page of its own. AIStack only ever touches folders git ignores.
- Review what a team update changes before taking it, see a skill's history, and bring an older revision back.
- Delete a team, rename a group, and delete an empty group. The last member can leave a team, which deletes it.
- `aistack move` moves a local Library to GitHub, to PostgreSQL, or back to this computer, with its whole history.
- `aistack connect claude-code|codex` connects a coding agent in local mode in one command, and `aistack check`, `export` and `dashboard` find the Library the agent was set up with.
- Operators: `aistack admin` commands for listing machines and teams, rotating and registering machines, removing a machine, naming a team admin, offboarding, renaming and forgetting a person; `aistack backup` and `aistack restore`; Prometheus metrics behind `AISTACK_METRICS_TOKEN`; a request id on every log line, and one log line for every change a person makes.

### Changed

- Taking a team's skill asks first when it would replace a different skill of yours with the same name.
- Sharing over a skill in a group takes the right to share into that group.
- An invite stops working when its maker leaves the team or may no longer invite.
- Sync reports what is true: a skill that is a git clone reads as current, a removed skill is offered for deletion instead of reinstalled, and a skill no push would accept is reported once with the reason. A whole backup list is pushed in one call.
- A session starts quietly when there is nothing to sync.
- The dashboard works with a keyboard and a screen reader, fits long names and tables at every width, and the pages before sign-in have a dark theme.
- The image runs on Python 3.14. The package still supports Python 3.13.

### Fixed

- Two admins leaving or demoting each other at once could leave a team with no admin, and other changes to one team could race on PostgreSQL.
- Reading the dashboard, `/health` and the bearer check no longer waits for SQLite's write lock; a lock that times out answers with a sentence to try again.
- A GitHub Library replays its log in causal order, so a computer whose clock runs ahead no longer brings back an older edit.
- Local setup's `claude mcp add` command failed for a GitHub or PostgreSQL Library.
- A server started inside another application's project no longer takes over that project's database.

### Security

- Dashboard sessions and transfer URLs end as soon as the computer that opened them is removed or its token is rotated, and signing out ends the session on the server.
- Refused credentials are throttled per address, and a refused join never writes the invite code to the log or the answer.
- Stricter checks on uploaded archives and paths, including Windows short names, and a separate staging folder for each local install.
- Every build dependency and CI action is pinned and checked for known vulnerabilities; mcp 1.30.0 fixes CVE-2026-59951; the image carries an SBOM and provenance and is signed.

## 0.1.0 (2026-10-15)

The first release on PyPI and the first version-tagged image.

### Upgrade notes

- A server running an image from before this release upgrades in place at startup. Take a backup first (docs/OPERATING.md, Backups).
- Local mode installs with `uv tool install aistack-mcp` and updates itself within 0.1.

### Added

- Skills synced between a person's computers through their own Library, on a server, in a local SQLite file, in a GitHub repository, or in a PostgreSQL database.
- Teams and groups to share skills with, where a teammate's change is an offer to take, never an overwrite.
- The web dashboard, on a server and on `127.0.0.1` in local mode.
