---
name: sync-aistack
description: Sync this computer's skills with the user's own Library on AIStack. Use when the user says "sync aistack", asks whether their skills are up to date, starts a work session, or wants their Library moved somewhere else.
---

# Sync AIStack

Bring this computer's skills in line with the Library, the user's private store of skills that every computer of theirs shares. AIStack runs on this computer as the `aistack` MCP server and reads and writes the skills folders itself, so this takes only tool calls. Sync when work starts, the way you would `git pull`.

## 0. Check that AIStack is connected

The `sync` tool and the others below come from the `aistack` MCP server. If they are not available in this session, stop: do not try to do their work another way. Tell the user AIStack is not connected in this session, and what to do:

- If setup has just finished, restart Claude Code, or Codex if that is the agent you are, once. It reads its server list at startup.
- Otherwise run `"$(uv tool dir --bin)/aistack-mcp" check` in a terminal (on Windows, `& "$(uv tool dir --bin)\aistack-mcp.exe" check`). It finds the Library this computer's agent uses by itself, and says what is wrong: a database or repository it cannot reach, or a GitHub login that is missing. For a Library in a database it asks for the address in `AISTACK_DATABASE_URL`; let the user set that in their own terminal, since it holds the password. If the command itself is not found, AIStack is not installed: `uv tool install aistack-mcp`, then `<that path> connect claude-code` (or `codex`). Never run `claude mcp get aistack` or `codex mcp get aistack`: they print the Library's settings in full, and a database address holds its password.

If the tools are there but answer with an error that says what to do, such as another computer having updated the Library, tell the user exactly that.

## 1. Find the skills folders on this computer

AIStack keeps two skills folders in line, and every tool call names one of them as its `harness`:

| `harness` | Folder | read by |
|---|---|---|
| `claude_code` | `~/.claude/skills` | Claude Code |
| `agents` | `~/.agents/skills` | Codex, Gemini CLI, Kimi Code, Cursor, Copilot CLI, opencode, Amp |

Call `sync` without a harness first: it syncs this computer's first folder and says which in `harness`, and its `folders` field lists every folder this computer has an agent for. Do steps 2 and 3 for each of those folders in turn, then steps 4 and 5 once. Do not ask the user which folders to sync, and say nothing about a folder no agent here reads.

## 2. Call `sync`

Call `sync` with the folder's `harness`. It reads the folder itself; send nothing else.

## 3. Act on the report

Work through the fields in this order, passing the same harness to every tool you call.

1. **`install`** and **`update`**: call `get_skill` with each entry's `name`. It installs the files itself. Do not ask first: this folder already chose these skills, and the local copy is missing or an unmodified older revision, so nothing can be lost.
2. **`backup`**: skills on disk that are not yet in the Library. Call `push_skill` once with all of them as `names`: one call, and on GitHub one push. Tell the user about any in `refused`. Do not ask first: the Library is private and mirrors this computer. `cannot_back_up` lists skills a push would refuse, each with its `reason`: tell the user once what to fix, and do not push them.
3. **`ask`**: sync found something it will not decide for the user. Put each entry to them and act only on their answer. `desired` is enabled, disabled, or undecided here; `local` is current, stale, or unknown (edited). When `removed_from_library` is true, the user removed the skill from their Library, so say that the question is whether to delete the folder here. Offer exactly the listed `options`, in plain words. When an option has `overwrites_local`, say the files here will be replaced; with `loses_local_edits`, say their edits will be lost. When `edited_from` is lower than `latest_revision`, the copy here is an edit of an older revision and another computer pushed since: say that `push` makes this copy the latest in place of that change, which their other computers then lose too, and offer `skip` while they compare. Then: enable or restore is `get_skill`; push is `push_skill`; remove is `disable_skill`, which also deletes the folder; skip is nothing.
4. **`first_sync`**: true only the first time this folder syncs on this computer. Note it for step 4.
5. **`library_reachable`**: false when the Library's GitHub repository could not be reached, so this compared against this computer's copy. Tell the user `library_problem` as it is, before the rest of the report.
6. **`new_computer`**: true once, when this home folder was restored here from another computer's backup. Tell the user AIStack now counts this as a computer of its own, and that the computer it came from keeps its skills as they were. Its skills folders are offered like any new computer's.
7. **Rules**: `sync` also writes the user's rules itself: each agent's file for every project (`~/.claude/CLAUDE.md`, Codex's `AGENTS.md`) and their own rules in each project added on this computer. `rule_changes` says what it wrote or kept in the Library; mention them. `rule_failures`: tell the user each. `rule_questions`: a rule file edited here and on the page, or a rule no longer wanted. Ask the user about each, naming its `file`, and offer exactly its `options`: restore writes the Library's text over the file, push keeps the file's text in the Library, remove deletes the file (or its part of `AGENTS.override.md`), skip changes nothing. Say so when an option has `overwrites_local` or `loses_local_edits`; `edited_from` below `revision` means the rule was also edited on the page. Then call `sync` once more with every answer as `rule_choices`: `{"<key>": "<choice>"}`.

`up_to_date` counts enabled skills that already match and needs no action. `team_updates` is always empty here, because teams live on a server. Sync changes no skill and deletes nothing unasked; only the calls you make afterwards do.

## 4. The first sync on this computer

When any folder reported `first_sync`, offer the Library itself. Call `list_skills`: the user's own skills (those whose `team` is null) that are in neither folder on disk after this sync, and not under `ask`, come from their other computers. If there are any, ask once, naming them: "Your Library has <names> from your other computers. Install them here?" Yes: `get_skill` each into `claude_code` when this computer has Claude Code, otherwise into `agents`. No: nothing; they can say "install <name>" whenever they want one. Ask this before the question above, so a skill installed now is counted when the folders are compared.

Only when you synced both folders and at least one reported `first_sync`. Take the skills from the Library in each folder: its skill folders on disk after this sync, less anything still under `ask`, less `sync-aistack`. If one folder has skills the other lacks, ask once, naming them: "Use the same skills in Claude Code and in Codex and the other agents? That adds <names> to Claude Code and <names> to the agents folder." Yes: `get_skill` each missing skill with the harness of the folder that lacks it. No: nothing, and it is not asked again.

## 5. In Codex, keep the connection current

Later releases add settings to Codex's connection. Run `sed -n '/^\[mcp_servers\.aistack\]/,/^\[/p' ~/.codex/config.toml | grep -cE '^(startup_timeout_sec|tools\.(sync|list_skills|get_skill|push_skill)\.approval_mode)'`, which counts them without showing the connection's other lines. If it prints less than 5, run `<aistack-mcp> connect codex`: it rewrites the connection with the current settings and keeps the Library's place. Say so in one line.

## 6. Report

Say in a sentence or two what changed: what was installed or updated (between which revisions), what was backed up, and what is waiting on the user. When nothing changed, say everything is up to date.

## Moving the Library

When the user wants their Library somewhere else, such as from this computer only to a private GitHub repository or a database their other computers share:

1. Run `<aistack-mcp> move github`, `<aistack-mcp> move postgresql`, or `<aistack-mcp> move here`, with the full path. It moves the Library this computer's agent uses, with its history, placements and removals, and leaves the old place as it was.
   - GitHub: it signs in as setup's choice 2 does; tell the user the code it prints, then run it again. Give `owner/name` after `github` to use a repository other than their own `aistack-library`.
   - PostgreSQL: the user sets `AISTACK_MOVE_TO_URL` to the new database's address in their own terminal and runs the command there, since the address holds the password. The database must be empty.
   - It refuses a place that already holds a Library, and a Library from before AIStack kept a log of its changes. For that one, use the old way: `<aistack-mcp> export ~/aistack-library`, set AIStack up in the new place, copy the exported folders into a skills folder, and sync.
2. Run `<aistack-mcp> connect claude-code` (or `codex`). It connects to the place the move recorded and replaces the old connection. For PostgreSQL, the user runs it in their own terminal with `AISTACK_DATABASE_URL` set to the new address. Restart once.
3. Tell the user their other computers stay on the old place until each is set up again with the new one. A Library moved to this computer only is reached from no other computer.
