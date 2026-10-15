# Skill folders inside projects: the design

The decision is [ADR-0026 (proposed)](../../adr/0026-skills-folders-inside-projects.md); the build steps are in [PLAN.md](PLAN.md#skill-folders-inside-projects). This document holds the detail behind both. Where it says `<next>`, read the next free migration number when the work starts.

# Project skills folders: design notes (companion to ADR-0026)

Everything below was checked against `main` at `ac40dcb` on 2026-10-15. Where a claim rests on something I ran, the script is named in §9.

## 1. What a project is

### Identity

| Case | Key | Name shown |
|---|---|---|
| `origin` (or the only remote) is a URL or an scp-style address | `host/path`, lowercased. Scheme, user and password, port, a trailing `/` and `.git` are dropped. | Last segment of the path (`aistack`) |
| `https://user:ghs_…@github.com/Owner/Repo.git` | `github.com/owner/repo`. The token never reaches storage or a log. | `repo` |
| `git@github.com:Owner/Repo.git`, `ssh://git@github.com:22/owner/repo` | `github.com/owner/repo` (the same project) | `repo` |
| No remote, or a `file://` or path remote | `local/<machine id>/<first 16 hex of sha256(top level)>`, so the project exists on this computer only | Folder name of the top level |
| Several remotes, none of them `origin` | The first one `git remote` prints | |

The prototype is `<scratch>/projects-design/proto/project_key.py`, and it ran on all of the cases above. The function belongs in `services/projects.py`. It is pure: no session, no I/O.

### Per-computer facts

- **Paths differ per computer.** `machine_project.path` holds the top level last seen on that computer. It is for display only. The server never uses it to decide where files go, and never echoes it back inside a command.
- **Two clones of one repository on one computer** map to one `(machine, project)`, so they share decisions. Each clone is observed on its own at its own sync. Disabling a skill in one clone means the next sync of the other clone asks whether to remove it (disabled + present). The folder page says "Every copy of this repository on macbook shares these skills."
- **Worktrees** are clones in this sense. `git rev-parse --path-format=absolute --git-path info/exclude` in a linked worktree returns the main clone's `.git/info/exclude`, and `git check-ignore` honours it in both places (verified). So an exclude line written once covers every worktree, and a new worktree gets the project's skills silently at its first sync (enabled + absent = install).
- **Submodules** have their own top level and remote, so each is its own project.
- **Monorepos**: only the top level's two folders are managed. Claude Code and Codex read upward to the repository root, so a placement at the top level is seen from every package.
- **A repository whose top level is the home folder** (dotfiles kept in git at `~`) is not a project. Its `.claude/skills` is the global folder. Local mode refuses it in code. Server mode refuses `~`, `$HOME`, `/Users/<x>`, `/home/<x>` and `C:\Users\<x>`, and the skill tells the agent to skip it.

### The rule: what AIStack must never do

1. It never writes, renames or deletes anything inside a skill folder that git tracks (`git ls-files -- .claude/skills/<name>` prints anything).
2. It never writes a skill folder that git would commit: untracked and not ignored, as listed by `git ls-files --others --exclude-standard --directory`.
3. It never edits `.gitignore` or any other tracked file. The only file it adds to is the clone's own `.git/info/exclude`, one line per folder it writes, plus one line for its staging folder: `/.claude/skills/<name>/` and `/.claude/skills/.aistack-staging/`.
4. It never backs up a repository's skill folder, and never installs a Library skill over one.
5. It never scans the disk for repositories, and never records a repository the person did not add.
6. It never stores or logs a remote as it was sent, because a remote can carry a token.
7. It never follows a project skills folder whose real path leaves the top level (for example `.claude` linked to `~/.claude`).
8. It never puts `sync-aistack` in a project folder.

**Classification** uses three commands, each verified against a scratch repository with a tracked skill, a partly tracked one, an untracked one and an excluded one:

```bash
git -C <top> ls-files -- .claude/skills                                            # tracked: the repository's
git -C <top> ls-files --others --exclude-standard --directory -- .claude/skills    # would be committed: the repository's
git -C <top> ls-files --others --ignored --exclude-standard --directory -- .claude/skills  # ignored whole: personal
```

A folder that has even one tracked file belongs to the repository (`mixed/` in the test). A folder counts as personal only when the folder as a whole is ignored.

**Personal versus committed:**
- Committed skills, and those about to be committed, are git's. AIStack leaves them alone and does not show them.
- Ignored skills are personal and behave exactly like a global folder, including backup without asking, because the Library is private and git cannot commit them.
- An untracked, unignored folder becomes personal only through a deliberate `push_skill` with `project`, which first writes the exclude line. A tracked folder cannot be pushed from the project folder. A person who wants a copy in their Library copies it into a global folder.

## 2. Discovery and the wire

### Who discovers projects

The sync skill, running in the session's working directory, finds the top level and the remote on every sync and passes them as `here`. The report answers `project: {key, name, managed}`. Nothing is stored for an unmanaged project. The skill syncs project folders only when `managed` is true, or when the user has just asked to add the project.

### Server mode, global sync (old fields unchanged)

```json
{"local": {"wizard": {"SKILL.md": "9f2c…"}}, "harness": "claude_code",
 "here": {"path": "/Users/maria/code/aistack", "remote": "git@github.com:dchristopoulos/aistack.git"}}
```

The result has every field it has today, plus:

```json
"project": {"key": "github.com/dchristopoulos/aistack", "name": "aistack", "managed": true},
"left_to_repository": [], "from_other_computers": []
```

### Server mode, project folder sync

```json
{"local": {"aistack-api-notes": {"SKILL.md": "1b0e…"}}, "harness": "claude_code",
 "here": {"path": "/Users/maria/code/aistack", "remote": "git@github.com:dchristopoulos/aistack.git"},
 "project": "github.com/dchristopoulos/aistack",
 "repository": ["code-review", "drafted"]}
```

- `local` lists only the personal (ignored) folders.
- `repository` is every other folder name in the project folder.
- The call creates or refreshes `machine_project` for (this machine, project, harness). That is the opt-in, and it is the only thing this sync writes, like `machine_harness`.
- The report has the usual fields over the personal folders, and:
  - `left_to_repository`: names enabled here that the repository's own folder blocks. The agent says so once.
  - `first_sync`: true when this folder's `last_synced_on` was null.
  - `from_other_computers`: on first sync only. These are skills enabled in this project on the user's other computers, not archived, not decided here, and not on disk here.
- `sync_skill_url` is always null for a project.

### Other tools

- `get_skill(name, team?, harness?, project?)` returns `folder: ".claude/skills"`, relative to the top level, when `project` is set. Everything else is as today. The agent installs into `<top>/.claude/skills/<name>` following the skill's project steps (§2, "the skill").
- `push_skill(name, origin?, harness?, project?)`: the upload ticket gains an optional `project_id` claim. The upload route checks again that `machine_project(machine, project, harness)` exists before the first write. If it is gone: `NotFound`, "This project is no longer managed on this computer, so nothing was stored."
- `disable_skill(name, harness?, project?)`.
- A `project` key the caller does not manage, or another user's key, gets one sentence: "This computer does not manage a project '<key>'. Sync from inside the repository first, or add it on the dashboard."
- `here.remote` that cannot be parsed is answered without echoing it: "here.remote is not a git remote AIStack can read. Send what `git remote get-url origin` prints."

### Local mode (the process does the disk and git work)

```json
sync {"harness": "claude_code", "here": "/Users/maria/code/aistack"}
→ {..., "folders": ["claude_code", "agents"], "harness": "claude_code",
   "project": {"key": "github.com/dchristopoulos/aistack", "name": "aistack", "managed": true, "path": "/Users/maria/code/aistack"}}
sync {"harness": "claude_code", "here": "/Users/maria/code/aistack", "project": true}
→ {..., "left_to_repository": [], "from_other_computers": ["sql-style"], "first_sync": true}
get_skill {"name": "sql-style", "harness": "claude_code", "here": "/Users/maria/code/aistack", "project": true}
→ {..., "folder": "/Users/maria/code/aistack/.claude/skills/sql-style", "folder_created": true}
```

`push_skill` and `disable_skill` take the same `here` and `project`. The stdio process runs from its own folder (commit 8baf315), so `here` is the only way it learns the agent's repository.

### Tool description budget

These lengths were measured, against Claude Code's 2,048-character cut:

| Tool | Server mode | Local mode |
|---|---|---|
| `sync` | 2047 | 1787 |
| `get_skill` | 2033 | 1037 |
| `push_skill` | 1779 | 1280 |

The server's `sync` description hands its digest commands (about 300 characters) to the skill, which already holds them. Each new argument gets one line. Project install steps live in the skill, not in `get_skill`'s description. `test_tool_descriptions.py` guards the limit.

### The skill (server mode), step 1b and project folders, in short

```bash
git rev-parse --show-toplevel        # nothing printed: no project
git -C <top> remote                  # origin if listed, else the first
git -C <top> config --get remote.<r>.url | sed -E 's#^([a-z+]+://)[^/@]*@#\1#'   # PowerShell: -replace '^([a-z+]+://)[^/@]*@','$1'
```

- Send `here` only when the `sync` tool's input schema has `here`. FastMCP 3.4.7 refuses an unknown argument outright (verified), so a newer skill must not call an older server with it.
- Install into a project:
  1. `excl=$(git -C <top> rev-parse --path-format=absolute --git-path info/exclude)`.
  2. Append the folder's line and the staging line if missing (create the `info` folder if needed).
  3. `git -C <top> ls-files -- <folder>/<name>` must print nothing, and `git -C <top> check-ignore -q <folder>/<name>/` must succeed. Otherwise stop and tell the user.
  4. Do the usual staged install with `<skills>` = `<top>/<folder>`.
- If `<top>/<folder>` did not exist before the install: tell the user to run `/reload-skills` in Claude Code, or to restart Codex if the skill does not appear.
- At `first_sync` of a project folder, ask once about `from_other_computers`. If both project folders synced, ask once whether to use the same skills in both (as ADR-0021, scoped to the project).
- For `ask` with undecided + unknown in a project: say that pushing makes this copy the one every folder using that name gets, and suggest renaming it `<project>-<name>` when it is about this repository.

### Backward compatibility of the wire

All of these are additive:
- Optional arguments that default to the global folder.
- New report fields: `project`, `left_to_repository`, `from_other_computers`.
- An optional ticket claim.

An older sync skill never sends `here` or `project`, so it syncs global folders exactly as today. The server's first sync with it returns `sync_skill_url` (the skill differs from the bundled copy), and the new skill takes over.

## 3. Schema

There are three new tables and no change to an existing one.

**Why not a nullable `project_id` on `machine_skill`?**
- `sync_service._decisions` selects by `machine_id` and `harness` only (src/aistack/services/sync_service.py:242-246). Every release before this one would read a project placement as a global decision, and install the skill into `~/.claude/skills`.
- `dashboard_service._my_skills` (src/aistack/services/dashboard_service.py:203-209) would show it as a global placement.
- `UNIQUE (machine_id, harness, skill_id)` would have to become a four-column constraint. On SQLite that is a table rebuild, and `skill_service._machine_skill` (src/aistack/services/skill_service.py:560-564) would then pick one of two rows arbitrarily.

That is a reshape, so it would be `older_releases_compatible = False`. Separate tables are purely additive.

### PostgreSQL

```sql
CREATE TABLE project (
  project_id   UUID PRIMARY KEY,
  user_id      UUID NOT NULL REFERENCES "user"(user_id) ON DELETE CASCADE,
  key          VARCHAR(255) NOT NULL,          -- host/path, or local/<machine>/<hash>
  name         VARCHAR(64)  NOT NULL,          -- display only
  created_on   TIMESTAMP WITH TIME ZONE NOT NULL,
  CONSTRAINT uq_project_user_key UNIQUE (user_id, key)
);
CREATE TABLE machine_project (                  -- a project folder on a computer: the opt-in
  machine_project_id UUID PRIMARY KEY,
  machine_id   UUID NOT NULL REFERENCES machine(machine_id) ON DELETE CASCADE,
  project_id   UUID NOT NULL REFERENCES project(project_id) ON DELETE CASCADE,
  harness      VARCHAR(16) NOT NULL CONSTRAINT ck_machine_project_harness CHECK (harness IN ('claude_code','agents')),
  path         VARCHAR(1024) NULL,             -- top level last seen there; null when added on the dashboard
  created_on   TIMESTAMP WITH TIME ZONE NOT NULL,
  last_synced_on TIMESTAMP WITH TIME ZONE NULL,  -- null until its first sync: first_sync
  CONSTRAINT uq_machine_project_machine_project_harness UNIQUE (machine_id, project_id, harness)
);
CREATE INDEX ix_machine_project_project_id ON machine_project (project_id);
CREATE TABLE machine_project_skill (            -- desired state, as machine_skill
  machine_project_skill_id UUID PRIMARY KEY,
  machine_project_id UUID NOT NULL REFERENCES machine_project(machine_project_id) ON DELETE CASCADE,
  skill_id     UUID NOT NULL REFERENCES skill(skill_id) ON DELETE CASCADE,
  enabled      BOOLEAN NOT NULL,               -- false = explicit disable; no row = no decision
  revision     INTEGER NULL,                   -- last installed or pushed here (edited_from)
  created_on   TIMESTAMP WITH TIME ZONE NOT NULL,
  updated_on   TIMESTAMP WITH TIME ZONE NOT NULL,
  CONSTRAINT uq_machine_project_skill_folder_skill UNIQUE (machine_project_id, skill_id)
);
```

### SQLite

The same DDL, as SQLAlchemy renders it:
- `UUID` is `CHAR(32)`.
- Timestamps are `DATETIME`, stored as text and read through `as_utc()`.
- `BOOLEAN` is an integer.
- `user` needs no quoting.
- Cascades fire only with `PRAGMA foreign_keys=ON`, which the engine sets.

Lengths are enforced in the application (`path` ≤ 1024 and printable, `key` ≤ 255, `name` ≤ 64), because SQLite accepts oversized values.

### Migration sketch

```python
"""Skills folders inside a project (ADR-0026).

Three new tables, so every release that knows 0010 keeps working: none of them reads these, and
machine_skill is untouched. Every foreign key cascades: an older release rebuilding a GitHub
Library's copy empties the tables it knows (ADR-0025) and cannot empty these.
"""
revision = "<next>"
down_revision = "0010"
older_releases_compatible = True
_HARNESSES = ("claude_code", "agents")   # as this migration knows them; never follows the model
```

**Why the cascades are required, not tidy.** I ran today's `library_log.rebuild` (an older release, in effect) on a copy holding project rows. With `ON DELETE CASCADE` it emptied them. Without it, it failed with `IntegrityError: FOREIGN KEY constraint failed` on `DELETE FROM skill` and `DELETE FROM user`, and that computer could never rebuild again.

**Visibility.** `visibility.my_project(user_id, key)` and `required_my_project(...)` are the only lookups by key. An unknown project and another user's project raise the same `NotFound` with the same sentence.

## 4. Log events (local mode, ADR-0025)

### Today's behaviour (traced, and run)

- **An unknown kind.** `apply` raises `ValidationError` "…a change of a kind this release does not know… Update AIStack" (src/aistack/services/library_log.py:103-106). `_replay` wraps it, naming the file (lines 141-150), and the replay transaction rolls back.
  - At startup, `application_context.build_local_context` stores it as `_local_refusal` (src/aistack/bootstrap/context/application_context.py:130-135), and every tool answers with it.
  - At runtime, `library_before_read` raises inside `sync`, `list_skills`, `get_skill`, `open_dashboard` and `/api/state`. `push_skill` and `disable_skill` do not pull, so they still record and publish.
  - Safe, but the older computer is blocked until it updates.
- **An extra field on an existing kind** is silently ignored. A `skill_placed` event carrying `project` became a global `claude_code` placement on replay (`proto/extra_field.py`). A `skill_pushed` with a project would likewise enable the skill globally (library_log.py:114-117). So project changes cannot reuse existing kinds.

### New kinds

Each fits in `KIND_MAX_LENGTH = 32`. `project` is always the key, never a raw remote.

```json
{"kind": "project_folder_added",   "data": {"project": "github.com/dchristopoulos/aistack", "project_name": "aistack", "harness": "claude_code", "path": "/Users/maria/code/aistack", "target_machine_id": null}}
{"kind": "project_folder_removed", "data": {"project": "github.com/dchristopoulos/aistack", "harness": null, "target_machine_id": "<uuid>"}}
{"kind": "skill_placed_in_project","data": {"name": "sql-style", "project": "github.com/dchristopoulos/aistack", "harness": "claude_code", "enabled": true, "revision": 3, "target_machine_id": null}}
{"kind": "skill_pushed_to_project","data": {"name": "aistack-api-notes", "origin": null, "archive": "<base64 tgz>", "project": "github.com/dchristopoulos/aistack", "project_name": "aistack", "harness": "claude_code"}}
```

- `project_folder_added` is recorded at a project folder's first sync, and when the dashboard adds a known project to a computer (`target_machine_id` set, `path` null).
- `skill_pushed_to_project` is one event for the revision and its placement together. Two events could sort placement-before-push when they share a timestamp, and the placement would fail with NotFound.
- `skill_removed` is unchanged. In the new release, `remove_from_my_skills` also disables `machine_project_skill` rows.
- A `machine_project.last_synced_on` refresh is not logged, as `folder_synced` is logged only on a first sync.

### Replay

Replay goes through `project_service`, as every kind goes through a service. It validates the key, name, harness and path as the tools would. A forged event with an overlong key, a control character, or a key carrying `@` is refused, naming its file.

### Bridge rule

- **Release R1** ships migration <next>, `project_service`, and replay of the five kinds. A `_REPLAY_ONLY` set makes `library_log.record()` refuse these kinds, so nothing in R1 can write them.
- **Release R2** removes them from `_REPLAY_ONLY`. It ships no sooner than a week after R1, because `self_update` runs daily.

A computer still on R0 when R2's events arrive refuses as described above and asks to be updated. That was already the documented behaviour for any new kind. AGENTS.md records the rule.

## 5. Reconciliation

**`services/reconciliation.py` does not change.** The service computes the two facts for a project folder:

- **Desired**: the `machine_project_skill` row for (this machine's project folder, skill). It is enabled, disabled, or none. An archived skill reads as `disabled` in every folder (global too). In every state reachable today, removal already disabled every global row, so global behaviour does not change. The rule exists because an R0 computer's removal does not touch the project tables.
- **Observed**: the same hashing as today, over the personal (ignored) folders only.
- **Names under `repository`**: never reconciled, never `backup`, never `install`. They appear in `left_to_repository` only when enabled here.
- **Backup without asking**: an ignored, untracked folder whose name is not in the Library. It is placed in that project folder only, as ADR-0018 places a backed-up skill where it was found. A tracked or would-be-committed folder is never backed up.
- **Name collisions**: a personal `conventions` in project B, when the Library's `conventions` came from project A, is undecided + unknown, so sync asks. If the user pushes, A's unmodified copy becomes stale and is updated silently. That is today's contract for one name across two computers, but it is likelier across repositories, so the skill steers the user towards a rename (see open questions).
- **Global and project both holding a skill for one agent on one computer**: allowed. Claude Code uses the personal (global) copy, and Codex lists both. The dashboard warns, and sync does not ask.

## 6. The dashboard

### `GET /api/state` additions (additive keys)

```json
"machines": [{"id": "…", "name": "macbook", "os": "MACOS", "harnesses": ["claude_code", "agents"],
  "projects": [{"key": "github.com/dchristopoulos/aistack", "name": "aistack",
                "folders": [{"harness": "claude_code", "path": "/Users/dimitris/code/aistack", "last_synced_on": "2026-10-20T09:12:03+00:00"},
                            {"harness": "agents", "path": null, "last_synced_on": null}]}]}],
"skills": [{"name": "sql-style", "placements": [{"machine": "…", "harness": "claude_code", "project": null},
                                               {"machine": "…", "harness": "claude_code", "project": "github.com/dchristopoulos/aistack"}], …}]
```

`_machines` also counts harnesses known only from `machine_project`, so a computer whose only use of the agents folder is in a project still shows that agent.

### New and changed routes

A key contains slashes, so it travels in the body. Each of these goes in DESIGN.md's routes table; `test_dashboard_routes_are_documented` enforces that.

| Route | Body | Does |
|---|---|---|
| `POST /api/skills/{name}/machines/{machine_id}` | as today, plus optional `project` (a key) | Places the skill in that project folder, or takes it off |
| `POST /api/machines/{machine_id}/projects` | `project`, `harness` | Starts managing a project already known from another computer on this computer; no path until it syncs there |
| `POST /api/machines/{machine_id}/projects/remove` | `project`, optional `harness` (all when omitted) | Stops managing: deletes the folder rows, so placements cascade. Files stay on disk and stay excluded from git |

In local mode each action records its event.

### Computer tree

The sidebar follows design-system.md, "Project folders go beside Global":

```
Computers                         +
▾ ▭ macbook
    >_ Claude Code
       ▢ Global                   7
       ⑂ aistack                  2      (mono: a name a person types)
       ⑂ billing-api              0
    >_ Agents folder
       ▢ Global                   2
       ⑂ aistack                  1
    + Add an agent
    + Add a project
```

- The project icon is a new `repo` glyph in the page's icon set.
- Each leaf's `aria-label` reads "macbook / Claude Code, project aistack, 2 skills".
- The route is `#/f/<machine id>/<agent>/<enc(key)>`. `route()` splits on `/` before decoding, so an encoded key stays one part. An unknown key falls back to the agent's Global folder.

### Project folder page

The top bar path reads `dimitris / computers / macbook / Claude Code / aistack / /Users/dimitris/code/aistack/.claude/skills`. The header:

```
[⑂]  Claude Code in aistack on macbook                     [Copy from…] [+ Add skills]
     Project folder  /Users/…/aistack/.claude/skills   Read by Claude Code
     Repository  github.com/dchristopoulos/aistack, synced 2 hours ago
```

- The page title is "Claude Code in aistack on macbook".
- The table is the same as Global's: Skill, Source, Revision, Remove.
- The foot note reads: "AIStack writes only skill folders git ignores here, and hides each one it installs from git in this clone. Skills the repository commits are the repository's: they are not listed and never touched."
- A `.card.danger` at the foot holds "Stop managing aistack on macbook…". It opens `confirmDialog`: "AIStack stops syncing aistack's skills folders on macbook. The skills already there stay on disk and stay hidden from git; your Library and your other computers do not change."
- **Not synced here yet** (path null): a card says "aistack has not synced on desktop yet. Open a session inside the repository there and say `sync aistack`. Skills you add here wait until then."
- **Empty state**: `empty('repo', 'Nothing in Claude Code in aistack yet', 'Add skills from your library. They arrive the next time you say sync aistack in a session inside aistack on macbook.', [Add skills])`.

### Add a project dialog

It opens from "+ Add a project" under a computer and uses `choice-card`s:
1. **A repository you already use with AIStack**: radios list the projects known on other computers and not on this one, plus a radio for the agent (Claude Code, Agents folder). Add creates the folder rows, then opens the folder page.
2. **A repository on this computer**: "Open a coding agent session inside the repository on macbook and say this. It shows up here after that." It shows `copyField('add this project to aistack')`.

When nothing is known from elsewhere, only the second card shows.

### Skill panel, "Where it is"

There is still one `target-group` per computer, and each option names its folder in words:
- `Claude Code` (`~/.claude/skills`)
- `Agents folder` (`~/.agents/skills`)
- `Claude Code in aistack` (`aistack/.claude/skills`)
- `Agents folder in aistack`

Project options appear only for projects managed on that computer. When an agent's Global and one of its projects are both ticked, a `help` line says "Also in Claude Code's global folder: Claude Code uses that copy, and Codex lists both."

### Library, "Where it is" column

There is one line per computer. Global folders are named by agent, and project folders as "<agent> in <project>": `macbook  Claude Code, Agents folder, Claude Code in aistack`. Each name links to its folder. "Not on any computer" counts project placements as being on a computer.

The local-mode dashboard (`aistack dashboard`) is identical, because projects are the person's own.

## 7. Security checklist (trust-boundary review targets)

- A remote may carry a token. The server normalises it before anything is stored. It never logs `here`, the remote or the path; log lines carry `project_id`. Errors never echo a remote. The test is a canary `ghs_` remote absent from captured logs and results.
- Paths from the agent are display-only on the server: ≤ 1024 characters, printable, absolute or `~`. They are never placed into a returned command, because `get_skill` returns a relative folder.
- An upload ticket's `project_id` is checked again at upload against the ticket's machine, before any row is written.
- Local mode runs git as `git -c core.fsmonitor=false -c core.hooksPath=<empty dir>`, with the environment stripped of `GIT_*` (reuse `library_repo._git_environment`), a timeout, and `--` before every path.
- Local mode refuses:
  - a top level equal to `Path.home()`, or inside `AISTACK_HOME` (the Library clone);
  - a skills folder whose `realpath` leaves the top level;
  - any write to a tracked or would-be-committed folder.

  It writes the exclude line, then re-checks `check-ignore`, then installs through `local_skills.install`, which validates and re-hashes.
- Dashboard actions take `user_id` from the cookie. Machine and project are resolved through `visibility`, and another user's machine or project answers like an unknown one.
- Server mode cannot enforce the git rule: it is the agent's shell. The server refuses every name listed in `repository`, and the skill checks before writing. This is stated in the ADR.

## 8. Compatibility across releases

R0 is today's release (schema 0010). R1 is the bridge: <next>, the services, and replay. R2 adds project tools, the skill and the dashboard.

| Situation | R0 | R1 | R2 |
|---|---|---|---|
| Runs on a database a newer release migrated (server rollback, or a shared PostgreSQL Library in local mode) | Yes, because <next> is compatible. It sees no projects. Its "Remove from Library" leaves project placements enabled, and R2 reads them as disabled because the skill is archived. Its "Not on any computer" may count a project-only skill. | Yes | Yes |
| Replays a GitHub log holding project events | Refuses reads with "Update AIStack…" until self-update | Applies them | Applies them |
| Records project events | Never | Never (`_REPLAY_ONLY`) | Yes |
| Rebuilds a copy holding project rows (downgraded on one computer) | Works only because the FKs cascade (verified) | Yes | Yes |
| An older sync skill against this server | | Global only | Global only, then `sync_skill_url` delivers the new skill |
| R2's skill against an older server | Sends `here` only if the schema has it, because FastMCP 3.4.7 refuses unknown arguments | Same | |

## 9. What I ran (all under the scratch folder; nothing in the repository was changed)

- `<scratch>/projects-design/desc_len.py`: tool description lengths for both servers. Server `sync` is 2047 and `get_skill` is 2033.
- `<scratch>/projects-design/extra_arg.py`: FastMCP 3.4.7 answers an unknown tool argument with `ToolError … Unexpected keyword argument`.
- Shell session in `<scratch>/projects-design/gitlab/` (git 2.43):
  - the worktree's `--git-path info/exclude` is the main clone's file;
  - `check-ignore` honours it in both the clone and the worktree;
  - a tracked folder is never reported ignored;
  - the three `ls-files` commands classify tracked, partly tracked, untracked and excluded folders;
  - `git config --get remote.origin.url` returns embedded credentials verbatim;
  - a directory under a repository at the home folder resolves its top level to the home folder.
- `<scratch>/projects-design/proto/project_key.py`: the key normalisation on nine remotes.
- `<scratch>/projects-design/proto/old_rebuild.py`: today's `library_log.rebuild` empties project rows when the FKs cascade, and fails with `IntegrityError` when they do not.
- `<scratch>/projects-design/proto/extra_field.py`: a `skill_placed` event with an extra `project` field became a global `claude_code` placement, and an unknown kind was refused with the update sentence.

## Open questions for the owner

- Should backing up personal (git-ignored) project skills be silent, as for global folders, or asked once when a project is added? Some tools write generated skills into .claude/skills and gitignore them.
- Is sending `here` (top level and remote) on every sync acceptable to the owner? The server then learns which repositories a person opens, though it stores nothing for an unmanaged one. The alternative is sending it only after the person has added at least one project.
- Should a project's local path travel in the GitHub log and show on other computers' dashboards, or stay on the computer that synced it?
- One Library name is one skill (ADR-0015). Is steering renames ('<project>-<name>') enough for the many repositories that each have their own 'conventions' or 'architecture' skill, or does the owner want project-scoped names later? That would need its own ADR.
- Should the project folder page list the repository's committed skills read-only, so a person sees everything the agent loads there?
- Removing a project from a computer leaves its skills on disk, still excluded from git. Should the confirmation also offer 'and remove its skills', which disables each one so the next sync asks to delete it?
- The key lowercases the path, which merges two repositories that differ only in case on a case-sensitive self-hosted git server. Accept that, or lowercase only github.com, gitlab.com and bitbucket.org?
- A repository with several remotes and no origin is keyed by the first remote git lists. Clones can list them in different orders. Is that acceptable, or should the person pick one?
- Monorepo packages that keep their own .claude/skills are not managed. Wanted later?
- DESIGN.md roadmap item 8 says 'project-level precedence stays with item 9'. This ADR keeps teams out of project folders. Does the owner agree?
- Is a week between the bridge release and the release that records project events enough, given self_update runs daily and the package is not on PyPI yet (already known)?
- In server mode the git rule is held by the agent following the skill, backed by the server refusing listed names. Is that weaker guarantee acceptable, or should project folders be local-mode only at first?

## Not verified here

- That Claude Code loads <repo>/.claude/skills from the working directory up to the repository root comes from its docs, quoted in docs/research. Claude Code is closed source, so this was not run. In a linked git worktree, whether 'repository root' means the worktree's top level is not verified.
- Whether Claude Code needs /reload-skills when a project's .claude/skills folder is first created mid-session is unverified. The docs say this for 'a top-level skills directory created after the session started'.
- That Claude Code prefers the personal (global) copy over the project copy of a same-named skill comes from the docs only.
- That Codex scans .agents/skills from the working directory up to the repository root, and lists duplicates without precedence, comes from its docs and the research file. It was not run in a project or a worktree here, and live pickup of a newly created project folder is unverified.
- Gemini CLI reads workspace .agents/skills only in trusted folders. The research does not say whether it walks up from a subfolder to the git root.
- That Kimi Code reads project .agents/skills only at the git root, and the project folders of opencode, Cursor, Copilot CLI and Amp, come from docs and source cited in the research. None of these agents was run.
- Codex's project .codex/skills, in trusted projects, is read according to the research's source citation. AIStack would not manage it, and it was not checked.
- No coding agent was driven through the proposed sync-skill project steps. Whether agents follow about ten lines of git procedure reliably, including on Windows PowerShell where sed is unavailable, is untested.
- FastMCP refusing unknown tool arguments was verified only on the pinned 3.4.7.
- The bridge-release timing assumes self_update can upgrade from PyPI. aistack-mcp is not on PyPI today (already known), so in practice computers would not update themselves yet.
