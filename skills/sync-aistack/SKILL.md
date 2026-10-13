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

Sync never deletes anything and never changes which skills are enabled.

## 4. Tell the user what happened

One short summary. For each update, say which revision it moved from and to, and who pushed the new one; a skill is instructions to an agent, so the user should know whose instructions just changed. If nothing needed doing, say that everything is up to date and how many skills that covers.
