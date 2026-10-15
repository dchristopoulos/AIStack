---
name: sync-aistack
description: Sync this computer's skills with the user's own Library on AIStack. Use when the user says "sync aistack", asks whether their skills are up to date, or starts a work session.
---

# Sync AIStack

Bring this computer's skills in line with the Library, the user's private store of skills that every computer of theirs shares. AIStack runs on this computer as the `aistack` MCP server and reads and writes the skills folders itself, so this takes only tool calls. Sync when work starts, the way you would `git pull`.

## 0. Check that AIStack is connected

The `sync` tool and the others below come from the `aistack` MCP server. If they are not available in this session, stop: do not try to do their work another way. Tell the user AIStack is not connected in this session, and what to do:

- If setup has just finished, restart Claude Code, or Codex if that is the agent you are, once. It reads its server list at startup.
- Otherwise run `claude mcp get aistack` (in Codex, `codex mcp get aistack`) to see the command and settings it starts AIStack with, then run that command in a terminal with the same settings and `check` after it, for example `AISTACK_LIBRARY_REPO=<owner>/aistack-library ~/.local/bin/aistack-mcp check`. It says what is wrong: a database or repository it cannot reach, or a GitHub login that is missing. If the command itself is not found, AIStack is not installed: `uv tool install aistack-mcp`.

If the tools are there but answer with an error that says what to do, such as another computer having updated the Library, tell the user exactly that.

## 1. Find the skills folders on this computer

AIStack keeps two skills folders in line, and every tool call names one of them as its `harness`:

| `harness` | Folder | read by |
|---|---|---|
| `claude_code` | `~/.claude/skills` | Claude Code |
| `agents` | `~/.agents/skills` | Codex, Gemini CLI, Kimi Code, Cursor, Copilot CLI, opencode, Amp |

Call `sync` without a harness first: it syncs `claude_code`, and its `folders` field lists every folder this computer has an agent for. Do steps 2 and 3 for each of those folders in turn, `claude_code` first, then step 4 once. Do not ask the user which folders to sync, and say nothing about a folder no agent here reads.

## 2. Call `sync`

Call `sync` with the folder's `harness`. It reads the folder itself; send nothing else.

## 3. Act on the report

Work through the fields in this order, passing the same harness to every tool you call.

1. **`install`** and **`update`**: call `get_skill` with each entry's `name`. It installs the files itself. Do not ask first: this folder already chose these skills, and the local copy is missing or an unmodified older revision, so nothing can be lost.
2. **`backup`**: skills on disk that are not yet in the Library. Call `push_skill` with each name. Do not ask first: the Library is private and mirrors this computer.
3. **`ask`**: sync found something it will not decide for the user. Put each entry to them and act only on their answer. `desired` is enabled, disabled, or undecided here; `local` is current, stale, or unknown (edited). Offer exactly the listed `options`, in plain words. When an option has `overwrites_local`, say the files here will be replaced; with `loses_local_edits`, say their edits will be lost. Then: enable or restore is `get_skill`; push is `push_skill`; remove is `disable_skill`, which also deletes the folder; skip is nothing.
4. **`first_sync`**: true only the first time this folder syncs on this computer. Note it for step 4.

`up_to_date` counts enabled skills that already match and needs no action. `team_updates` is always empty here, because teams live on a server. Sync changes nothing and deletes nothing; only the calls you make afterwards do.

## 4. The first sync on this computer

When any folder reported `first_sync`, offer the Library itself. Call `list_skills`: the user's own skills (those whose `team` is null) that are in neither folder on disk after this sync, and not under `ask`, come from their other computers. If there are any, ask once, naming them: "Your Library has <names> from your other computers. Install them here?" Yes: `get_skill` each into `claude_code` when this computer has Claude Code, otherwise into `agents`. No: nothing; they can say "install <name>" whenever they want one. Ask this before the question above, so a skill installed now is counted when the folders are compared.

Only when you synced both folders and at least one reported `first_sync`. Take the skills from the Library in each folder: its skill folders on disk after this sync, less anything still under `ask`, less `sync-aistack`. If one folder has skills the other lacks, ask once, naming them: "Use the same skills in Claude Code and in Codex and the other agents? That adds <names> to Claude Code and <names> to the agents folder." Yes: `get_skill` each missing skill with the harness of the folder that lacks it. No: nothing, and it is not asked again.

## 5. Report

Say in a sentence or two what changed: what was installed or updated (between which revisions), what was backed up, and what is waiting on the user. When nothing changed, say everything is up to date.
