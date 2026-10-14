---
name: sync-aistack
description: Sync this machine's skills with the user's own skills on AIStack. Use when the user says "sync aistack", asks whether their skills are up to date, or starts a work session.
---

# Sync AIStack

Bring this machine's skills in line with the Library, the user's private space on the AIStack server. It mirrors their computers and is the only place this machine installs from. Sync when work starts, the way you would `git pull`.

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

Sync `claude_code` when `~/.claude` exists. Sync `agents` when `~/.agents/skills` exists or any of the other paths does. Do steps 2 to 4 for each of those folders in turn, `claude_code` first, then step 5 once, and pass that folder's `harness` to every `sync`, `get_skill`, `push_skill`, and `disable_skill` call. Do not ask the user which folders to sync, and say nothing about a folder no agent here reads.

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

With no local skills, pass `{"local": {}}` and the harness. Copy digests exactly as the shell printed them.

## 4. Act on the report

Work through the fields in this order, passing the same harness to every tool you call.

1. **`sync_skill_url`**: usually `null`. When it is a URL, this folder's copy of this skill is missing or differs from the server's. Download it only if `<folder>` is the folder this very file, `sync-aistack/SKILL.md`, was loaded from: `curl -sS -o <folder>/sync-aistack/SKILL.md "<sync_skill_url>"`, without asking. It is AIStack's own file, so nothing of the user's is lost. For any other folder, ignore the URL and never create `sync-aistack` there: the agents reading that folder are not connected to AIStack, and the skill would tell them to sync. Step 5 never copies it either.
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

`latest_revision` and `pushed_by` describe the newest revision in the Library. Mention them when the user is choosing between their local copy and the stored one. A `push` adds a revision on top; older revisions stay in the history, and no teammate sees any of it until the user shares the skill.

When several skills need the same kind of answer, ask about them together and accept one answer for the group.

### Team updates

Each `team_updates` entry has `name`, `team`, `from_revision`, `to_revision`, and `pushed_by`. Tell the user which team changed the skill, between which revisions, and who pushed the new one. Then ask whether they want it.

- **Yes**: call `get_skill` with `name` and `team`, then install. This copies the team's latest revision into the Library and replaces the local folder.
- **No**: do nothing. The offer comes back on the next sync.

If the same skill is also in `ask` with `local` `unknown`, settle that entry first: accepting the team's version replaces the local folder, edits included.

To share a change the other way, the user asks for it ("share wizard with backend"), which is `share_skill`. Sync never shares.

## 5. Make the two folders match, once

Only when you synced both folders and at least one reported `first_sync`. Take the skills from the Library in each folder: its skill folders on disk after this sync, less anything still under `ask`, less `sync-aistack`. If one folder has skills the other lacks, ask once, naming them: "Use the same skills in Claude Code and in Codex and the other agents? That adds <names> to Claude Code and <names> to the agents folder." Yes: `get_skill` each missing skill with the harness of the folder that lacks it, and install. No: nothing, and it is not asked again, because `first_sync` is true only once.

## 6. Tell the user what happened

One short summary per folder, naming the agents that read it: what was installed, what was updated, what was backed up, what was asked and decided, and which team updates were accepted or left. For each update, say which revision it moved from and to, and who pushed the new one; a skill is instructions to an agent, so the user should know whose instructions just changed. If nothing needed doing, say that everything is up to date and how many skills that covers.
