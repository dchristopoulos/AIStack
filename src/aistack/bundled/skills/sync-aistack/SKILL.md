---
name: sync-aistack
description: Sync this machine's skills with the team's AIStack vault. Use when the user says "sync aistack", asks whether their skills are up to date, or starts a work session.
---

# Sync AIStack

Bring this machine's skills in line with what the AIStack vault says it should have. Sync when you start work, the way you would `git pull`.

## 1. List what is on disk

Get the sha256 of every file under the global skills directory from a shell. Do not read the files yourself; you only need their digests.

macOS and Linux:

```bash
cd ~/.claude/skills 2>/dev/null && find -L . -mindepth 2 -type f \
  ! -name .DS_Store ! -path './.*' ! -path './synced/*' \
  -exec shasum -a 256 {} +
```

If `shasum` is missing, use `sha256sum` with the same arguments.

Windows (PowerShell):

```powershell
Get-ChildItem "$HOME\.claude\skills" -Recurse -File |
  Where-Object { $_.FullName -notmatch '\\(synced|\.[^\\]*)\\' } |
  Get-FileHash -Algorithm SHA256 | ForEach-Object { "$($_.Hash)  $($_.Path)" }
```

Each line is a digest and a path. The first folder in the path is the skill; the rest is the file's path inside it. `./wizard/scripts/run.sh` belongs to skill `wizard` as `scripts/run.sh`.

Leave out the `synced` folder (Claude Code manages it for claude.ai skills) and any folder starting with a dot. No output means no local skills, which is a valid answer.

## 2. Call `sync`

Pass every skill, including ones that did not come from AIStack:

```json
{"local": {"wizard": {"SKILL.md": "<sha256>", "scripts/run.sh": "<sha256>"}}}
```

With no local skills, pass `{"local": {}}`. Copy digests exactly as the shell printed them.

## 3. Act on the report

- **`install`** and **`update`**: call `get_skill` for each name and follow its install steps. Do not ask first. These are skills this machine already chose, and the local copy is either missing or an unmodified older revision, so nothing can be lost.
- **`ask`**: sync found something it will not decide for the user. Put each one to them and act only on their answer.
- **`orphans`**: skills on disk that the vault has never seen. List them and offer to push. Never push one unasked: most are third-party skills the user only downloaded, and pushing records the user as the one who put them in the vault.
- **`sync_skill_url`**: usually `null`. When it is a URL, this skill is missing or older than the server's. Download it over this file without asking, then carry on: `curl -sS -o ~/.claude/skills/sync-aistack/SKILL.md "<sync_skill_url>"`. It is AIStack's own file, so there is nothing of the user's to lose.

Sync never deletes anything and never changes which skills are enabled. Only the user's answer does.

### Asking

Each `ask` entry says what the server holds for this machine (`desired`) and what is on disk (`local`):

| `desired` | meaning |
|---|---|
| `enabled` | this machine manages the skill |
| `disabled` | the user removed it from this machine earlier, and the folder is back |
| `undecided` | it is in the vault and on disk, but this machine never chose it |

| `local` | meaning |
|---|---|
| `current` | identical to the vault's latest revision |
| `stale` | identical to an older revision (`local_revision`); nothing was edited |
| `unknown` | matches no revision: the user edited it, or it is a different skill with the same name |

Offer exactly the `options` listed, no others. Each choice maps to something you already know how to do:

| `choice` | do this |
|---|---|
| `enable` | `get_skill`, then install. The machine manages the skill from now on |
| `restore` | `get_skill`, then install. The skill was already managed here; this puts the vault's copy back over the local edits |
| `push` | `push_skill`, then upload the local folder as a new revision |
| `remove` | delete the local folder. It is already disabled on the server |
| `skip` | nothing. Sync asks again next time |

Two flags on each option are not optional to mention:

- `overwrites_local`: say that the files in the local folder will be replaced with the vault's.
- `loses_local_edits`: say plainly that the user's local edits exist nowhere else and will be gone. Suggest `push` first if they might want them.

Word the question from the facts. For `undecided` + `current`: "wizard is already on this machine and matches the vault. Want AIStack to keep it updated from now on?" For `enabled` + `unknown`: "You've edited wizard locally. Restore the vault's version (your edits will be lost), push your version to the vault, or leave it for now?"

Before the user answers `push` for an `unknown` copy, tell them the vault's latest is revision `latest_revision`, pushed by `pushed_by`. Their push becomes the newest revision for everyone, and if that person changed the skill after the user's copy was taken, those changes are not in it. The older revisions stay in the vault.

When several skills need the same kind of answer, ask about them together and accept one answer for the group.

## 4. Tell the user what happened

One short summary: what was installed, what was updated, what was asked and decided, and which orphans exist. For each update, say which revision it moved from and to, and who pushed the new one; a skill is instructions to an agent, so the user should know whose instructions just changed. If nothing needed doing, say that everything is up to date and how many skills that covers.
