---
name: sync-aistack
description: Sync this machine's skills with the user's own skills on AIStack. Use when the user says "sync aistack", asks whether their skills are up to date, or starts a work session.
---

# Sync AIStack

Bring this machine's skills in line with the Library, the user's private space on the AIStack server. It mirrors their computers and is the only place this machine installs from. Sync when work starts, the way you would `git pull`.

## 0. Check that AIStack is connected

The `sync` tool and the others below come from the `aistack` MCP server. If they are not available in this session, stop: do not reach the server another way, such as `curl`, and never read a token out of a configuration file. Tell the user AIStack is not connected in this session, and what to do:

- If setup has just finished, restart Claude Code, or Codex if that is the agent you are, once. It reads its server list at startup.
- Otherwise run `claude mcp list` and say what it reports for `aistack`. Never run `claude mcp get aistack` or `codex mcp get aistack`: they print this computer's token in full. In Codex, `grep -c '^\[mcp_servers.aistack\]' ~/.codex/config.toml` says whether the connection is there; a count above 1 makes the whole file invalid, so keep one block. If the server cannot be reached, it is down or not reachable from this computer. If it reports an authentication failure, this computer's token no longer works: whoever runs the server can rotate it, or the user says "add my other computer" on a computer that is still connected and runs the command it gives here, after `claude mcp remove aistack --scope user`.

## 1. Find the skills folders on this computer

AIStack keeps two skills folders in line, and every tool call names one of them as its `harness`:

| `harness` | macOS and Linux | Windows | read by |
|---|---|---|---|
| `claude_code` | `~/.claude/skills` | `$HOME\.claude\skills` | Claude Code |
| `agents` | `~/.agents/skills` | `$HOME\.agents\skills` | Codex, Gemini CLI, Kimi Code, Cursor, Copilot CLI, opencode, Amp |

See which agents this computer has:

```bash
ls -d ~/.claude ~/.agents/skills ~/.codex ~/.gemini ~/.kimi-code ~/.cursor ~/.copilot ~/.config/opencode ~/.config/amp 2>/dev/null
```

On Windows, run `Test-Path` on the same paths under `$HOME`.

Sync `claude_code` when `~/.claude` exists. Sync `agents` when `~/.agents/skills` exists or any of the other paths does. Do steps 2 to 4 for each of those folders in turn, `claude_code` first, then steps 5 and 6 once, and pass that folder's `harness` to every `sync`, `get_skill`, `push_skill`, and `disable_skill` call. Do not ask the user which folders to sync, and say nothing about a folder no agent here reads.

When the session runs inside a git repository, find it first, as step 8 says: every `sync` call then names it, and step 8 syncs its own skills folders after the global ones.

## 2. List what is on disk

Get the sha256 of every file in the folder (`<folder>` below) from a shell. Do not read the files yourself; you only need their digests.

macOS and Linux:

```bash
cd <folder> 2>/dev/null && find -L . -mindepth 2 -type f \
  ! -name .DS_Store ! -path './.*' ! -path './synced/*' \
  -exec shasum -a 256 {} +
```

If `shasum` is missing, use `sha256sum` with the same arguments.

Windows (PowerShell):

```powershell
Get-ChildItem "<folder>" -Recurse -File |
  Where-Object { $_.FullName -notmatch '\\(synced|\.[^\\]*)\\' } |
  Get-FileHash -Algorithm SHA256 | ForEach-Object { "$($_.Hash)  $($_.Path)" }
```

Each line is a digest and a path. The first folder in the path is the skill; the rest is the file's path inside it. `./wizard/scripts/run.sh` belongs to skill `wizard` as `scripts/run.sh`.

Leave out the `synced` folder (Claude Code manages it for claude.ai skills) and any folder starting with a dot. No output means no local skills, which is a valid answer.

## 3. Call `sync`

Pass every skill, including ones that did not come from AIStack, and the folder's harness:

```json
{"local": {"wizard": {"SKILL.md": "<sha256>", "scripts/run.sh": "<sha256>"}}, "harness": "claude_code"}
```

With no local skills, pass `{"local": {}}` and the harness. Copy digests exactly as the shell printed them. Add `here` when step 8 found a repository.

If `sync` fails with HTTP 413, "Request body too large", the listing was too big to send: a skill folder almost always holds a `node_modules` or `.git` folder with thousands of files. Find it with `find <folder> -mindepth 2 -type d \( -name node_modules -o -name .git \) -prune`, tell the user which skill it is in, and ask them to move it out of the skills folder. Then list and sync again.

## 4. Act on the report

Work through the fields in this order, passing the same harness to every tool you call.

1. **`sync_skill_url`**: usually `null`. When it is a URL, this folder's copy of this skill is missing or differs from the server's. Download it only if `<folder>` is the folder this very file, `sync-aistack/SKILL.md`, was loaded from: `curl -sS --create-dirs -o <folder>/sync-aistack/SKILL.md "<sync_skill_url>"`, without asking. It is AIStack's own file, so nothing of the user's is lost. For any other folder, ignore the URL and never create `sync-aistack` there: the agents reading that folder are not connected to AIStack, and the skill would tell them to sync. Step 5 never copies it either.
2. **`install`** and **`update`**: call `get_skill` with each entry's `name` and follow its install steps, into the `folder` it returns. Do not ask first. This folder already chose these skills, and the local copy is missing or is an unmodified older revision, so nothing can be lost.
3. **`backup`**: names of skills on disk that are not yet in the Library. For each, call `push_skill` with the name and follow its upload steps. Do not ask first. The Library is private, so a backup shares nothing with anyone. (An older server called this field `orphans` and asked before pushing; that rule is retired.)
4. **`ask`**: sync found something it will not decide for the user. Put each entry to them as described under "Asking" and act only on their answer.
5. **`team_updates`**: a team holds a newer revision of a skill the user took from it or shared with it. Each is an offer, described under "Team updates". Ask every time, including for an offer the user declined on an earlier sync.
6. **`first_sync`**: true only the first time this folder syncs on this computer. Note it; it is used once both folders are done (step 5).

**`up_to_date`** is a count of enabled skills that already match. It needs no action.

Sync changes no decision and deletes nothing. Only the calls you make afterwards do.

### Asking

Each `ask` entry names the skill, what the server holds for this machine (`desired`), and what is on disk (`local`).

| `desired` | meaning |
|---|---|
| `enabled` | this machine manages the skill |
| `disabled` | the user removed it from this machine, or from the Library, and the folder is still on disk |
| `undecided` | it is in the Library and on disk, but this machine never chose it |

| `local` | meaning |
|---|---|
| `current` | identical to the latest revision in the Library |
| `stale` | identical to an older revision (`local_revision`); nothing was edited |
| `unknown` | matches no revision: the user edited it, or it is a different skill with the same name |

Offer exactly the `options` listed, no others. Each `choice` maps to something you already know how to do:

| `choice` | do this |
|---|---|
| `enable` | `get_skill`, then install. This machine manages the skill from now on |
| `restore` | `get_skill`, then install. The skill was already managed here; this puts the stored copy back over the local edits |
| `push` | `push_skill`, then upload the local folder. It becomes the newest revision in the Library |
| `remove` | delete the local folder. The server already records that this machine should not have it |
| `skip` | nothing. Sync asks again next time |

Each option carries two flags. State them whenever they are true:

- `overwrites_local`: say that the files in the local folder will be replaced.
- `loses_local_edits`: say plainly that the user's local edits exist nowhere else and will be gone. Suggest `push` first if they might want them.

Word the question from the facts. For `undecided` + `current`: "wizard is already on this machine and matches your copy on AIStack. Want AIStack to keep it updated here from now on?" For `enabled` + `unknown`: "You've edited wizard locally. Restore the stored version (your edits will be lost), back up your version as a new revision, or leave it for now?"

When `edited_from` is lower than `latest_revision`, the local copy is an edit of an older revision, and another computer pushed since: "You edited wizard here from revision 1, and revision 2 was pushed from another computer since. Backing up yours makes it the latest in place of revision 2's changes, and your other computers then take yours." Say that before they choose `push`, and offer to leave it (`skip`) while they compare the two.

`latest_revision` and `pushed_by` describe the newest revision in the Library. Mention them when the user is choosing between their local copy and the stored one. A `push` adds a revision on top; older revisions stay in the history, and no teammate sees any of it until the user shares the skill.

When several skills need the same kind of answer, ask about them together and accept one answer for the group.

### Team updates

Each `team_updates` entry has `name`, `team`, `from_revision`, `to_revision`, `pushed_by`, and `own_changes`. Tell the user which team changed the skill, between which revisions, and who pushed the new one. When `own_changes` is true, the user changed the skill since taking it, so say that too: "You changed wizard since you took revision 1 from backend. Taking ana's revision 2 replaces your changes on every computer that has it." Then ask whether they want it.

- **Yes**: call `get_skill` with `name` and `team`, then install. This copies the team's latest revision into the Library and replaces the local folder.
- **No**: do nothing. The offer comes back on the next sync.

If the same skill is also in `ask` with `local` `unknown`, settle that entry first: accepting the team's version replaces the local folder, edits included.

If `get_skill` with a team is refused because the user already has their own skill of that name that was not taken from that team, tell them what its sentence says and ask. Only if they agree, call it again with `replace` true.

To share a change the other way, the user asks for it ("share wizard with backend"), which is `share_skill`. Sync never shares.

## 5. The first sync on this computer

When any folder reported `first_sync`, offer the Library itself. Call `list_skills`: the user's own skills (those whose `team` is null) that are in neither folder on disk after this sync, and not under `ask`, come from their other computers. If there are any, ask once, naming them: "Your Library has <names> from your other computers. Install them here?" Yes: `get_skill` each into `claude_code` when this computer has Claude Code, otherwise into `agents`, and install it. No: nothing; they can say "install <name>" whenever they want one. Ask this before the question above, so a skill installed now is counted when the folders are compared.

Only when you synced both folders and at least one reported `first_sync`. Take the skills from the Library in each folder: its skill folders on disk after this sync, less anything still under `ask`, less `sync-aistack`. If one folder has skills the other lacks, ask once, naming them: "Use the same skills in Claude Code and in Codex and the other agents? That adds <names> to Claude Code and <names> to the agents folder." Yes: `get_skill` each missing skill with the harness of the folder that lacks it, and install. No: nothing, and it is not asked again, because `first_sync` is true only once.

Then the session-start hook, which setup offers and a computer added with "add my other computer" never saw. Look in the hook file of the agent you are, `~/.claude/settings.json` in Claude Code or `~/.codex/hooks.json` in Codex, for an entry whose command contains `run the sync-aistack skill`. If there is none, ask once whether this agent should sync AIStack at the start of every session, and recommend it. If they agree, add this entry to the list under `hooks.SessionStart`, creating the keys that are missing and keeping everything already in the file, and check that it is still valid JSON before saving it:

```json
{"matcher": "startup", "hooks": [{"type": "command", "command": "echo AIStack: before the first task, run the sync-aistack skill.", "timeout": 10}]}
```

It runs no program and holds no token. Codex asks the user to trust a new hook once, in `/hooks`; tell them to accept it.

## 6. In Codex, keep the connection current

Later releases approve more of what sync does without asking. Run `sed -n '/^\[mcp_servers\.aistack\]/,/^\[/p' ~/.codex/config.toml | grep -cE '^(tools\.(sync|list_skills|get_skill|push_skill)\.approval_mode)'`, which counts the approvals without showing the connection's other lines. If it prints less than 4, add whichever of these lines are missing directly under `[mcp_servers.aistack]` in `~/.codex/config.toml`, with your file-editing tool and without printing the file, because it holds this computer's token:

```toml
tools.sync.approval_mode = "approve"
tools.list_skills.approval_mode = "approve"
tools.get_skill.approval_mode = "approve"
tools.push_skill.approval_mode = "approve"
```

Say so in one line.

## 7. Tell the user what happened

One short summary per folder, project folders included, naming the agents that read it: what was installed, what was updated, what was backed up, what was asked and decided, and which team updates were accepted or left. For each update, say which revision it moved from and to, and who pushed the new one; a skill is instructions to an agent, so the user should know whose instructions just changed. If nothing needed doing, say that everything is up to date and how many skills that covers.

## 8. Skills folders inside a project

Some skills belong to one repository. Its skills folders sit at its top level: `<top>/.claude/skills` is `claude_code`, and `<top>/.agents/skills` is `agents`. The agents read them from every folder of the repository. Do this step only when the `sync` tool's input schema has `here`: an older server refuses it.

### Find the repository

```bash
git rev-parse --show-toplevel
```

If it prints nothing, or the home folder, the session is in no project: skip this step. Otherwise the path it printed is `<top>`. Then the remote, `origin` if `git -C <top> remote` lists it, otherwise the first one listed, with any credentials in it removed, so a token never leaves this computer:

```bash
git -C <top> config --get remote.<remote>.url | sed -E 's#^([a-z+]+://)[^/@]*@#\1#'
```

In PowerShell: `(git -C <top> config --get remote.<remote>.url) -replace '^([a-z+]+://)[^/@]*@','$1'`. With no remote, the remote is `null`.

Pass `"here": {"path": "<top>", "remote": "<remote>"}` to every `sync` call, the global folders' too. The report's `project` then says the project's `key` and `name`, and whether this computer `managed` it already.

### Sync its folders

Sync a project's folders only when `project.managed` is true, or the user just said "add this project to aistack", which is how a project starts being managed on this computer. Do it for each harness step 1 chose, after the global folders, with `<folder>` being `.claude/skills` or `.agents/skills`.

If `<top>/<folder>` exists, `(cd <top>/<folder> && pwd -P)` must print a path inside `<top>`. A folder that leads elsewhere, such as a link to the global one, is skipped.

1. Sort its skill folders. Git decides which are the repository's and which are the user's:

   ```bash
   git -C <top> ls-files -- <folder>
   git -C <top> ls-files --others --exclude-standard --directory -- <folder>
   git -C <top> ls-files --others --ignored --exclude-standard --directory -- <folder>
   ```

   The first two list what the repository holds: what git tracks, and what it would commit. The name of each folder directly under `<folder>` in them goes in `repository`. The third lists the user's own folders, which git ignores whole. Only those are listed as in step 2 and sent in `local`.
2. Call `sync` with `local`, `harness`, `here`, `project` set to the key, and `repository`.
3. Act on the report as step 4 says, passing `project` to every `get_skill`, `push_skill` and `disable_skill` call, with these differences:
   - Every install follows "Install into a project" below.
   - `left_to_repository`: say once that the repository has its own skill of that name, so the Library's is not placed there.
   - `first_sync` with `from_other_computers`: ask once: "Your other computers use <names> in <project name>. Install them here too?" Yes: `get_skill` each with `project`, and install. When both of this project's folders synced and one reported `first_sync`, ask once, as step 5 does, whether to use the same skills in both.
   - `ask` with `undecided` and `unknown`: say that backing it up makes this copy the one every folder with that name gets. If it is about this repository, suggest renaming it `<project name>-<name>` first.
   - `remove`: delete the folder only when `git -C <top> ls-files -- <folder>/<name>` prints nothing and `git -C <top> check-ignore -q <folder>/<name>/` succeeds.
   - `sync-aistack` never goes in a project folder, and `sync_skill_url` is ignored there.

To back up a folder git would commit, the user must ask for it by name. Write its exclude line as below first, then `push_skill` with `project`. A folder git tracks is never pushed from here.

### Install into a project

Before every install into `<top>/<folder>`, make git ignore the skill's folder and the staging folder in this clone, and check that it does. The exclude file is the clone's own, shared by every worktree, and git never commits it. Never edit `.gitignore`.

```bash
excl=$(git -C <top> rev-parse --path-format=absolute --git-path info/exclude)
mkdir -p "$(dirname "$excl")"
grep -qxF '/<folder>/<name>/' "$excl" || echo '/<folder>/<name>/' >> "$excl"
grep -qxF '/<folder>/.aistack-staging/' "$excl" || echo '/<folder>/.aistack-staging/' >> "$excl"
git -C <top> ls-files -- <folder>/<name>
git -C <top> check-ignore -q <folder>/<name>/ && echo ignored
```

In PowerShell, read the same path into `$excl` and add each line with `Add-Content` when `Select-String -SimpleMatch` does not find it. `ls-files` must print nothing and the last line must print `ignored`. Otherwise stop and tell the user: the repository holds that folder. Then install as `get_skill` says, with `<skills>` being `<top>/<folder>`.

If `<top>/<folder>` did not exist before this install, tell the user to run `/reload-skills` in Claude Code, or to restart Codex if the skill does not appear.

