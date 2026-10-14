# One account for every coding agent on a computer, Codex first

Status: accepted, 2026-10-14. Revised before acceptance with what each agent actually reads ([docs/research/coding-agent-config-layout.md](../research/coding-agent-config-layout.md)). Built in the steps #62 lists; the navigation in step 1 is merged.

AIStack installs skills for Claude Code only. A person who also uses Codex keeps a second copy of the same skills by hand, which is the drift AIStack exists to end. Codex reads the same `SKILL.md` format (a `name` and a `description`) from `~/.agents/skills`, and so do Gemini CLI, Kimi Code, opencode, Cursor, GitHub Copilot CLI and Amp: that folder is the shared Agent Skills convention. Claude Code does not read it. Two folders therefore reach nearly every coding agent in use.

## The model

**A harness is a skills folder with a name.** What AIStack manages on a computer is a folder, not a program. There are two: `claude_code` (`~/.claude/skills`, read by Claude Code) and `agents` (`~/.agents/skills`, read by Codex and the other agents above). The second is named after the folder, not after Codex, because placing a skill there places it in every agent that reads it, and the page says so by listing them. A harness entry in the code is a key, a display name, its folder per operating system, the agents that read it, and how each connects to an MCP server. Adding an agent that reads a listed folder is one line in that list; a new folder is a new entry. Codex is the first agent tested against `agents`.

- opencode, Cursor and Amp read both folders, so a skill placed in both appears twice there. The page warns when a skill is placed in both on one computer.
- Codex still reads its retired `~/.codex/skills`. AIStack never installs there, and sync does not report it.
- Claude Code, Codex and Kimi load a newly installed skill in the running session; Gemini and Copilot need `/skills reload`, and Amp a reload or a new thread. `get_skill`'s result says when the agent should tell the user to reload.

**A skill is placed in a folder, and each placement is its own decision.** Desired state becomes one `machine_skill` row per computer, harness and skill: `UNIQUE (machine_id, harness, skill_id)`. That is how people think about it ("put it in MacBook › Codex"), and it keeps every decision explicit:

- a skill backed up from the Codex folder is placed in Codex only, and does not appear in Claude Code by surprise;
- "off in Codex, never decided for Claude Code" can be said;
- the three states a decision can be in (on, off, none) are the same per folder, so the reconciliation table (ADR-0007) and the rule that sync never deletes (ADR-0006) apply unchanged, one folder at a time.

The first version of this record kept one decision per computer with a table of per-harness exceptions. It was dropped for the reasons above.

**One token per computer, shared by every agent on it.** A token is a person on one computer (ADR-0015). Codex holds it in `~/.codex/config.toml` as a static `Authorization` header (`http_headers`) on a streamable HTTP server, as Claude Code holds it in its own configuration.

**Sync can start itself.** A hook cannot call an MCP tool when a session starts, and sync is read-only with the agent acting on its report (ADR-0004, ADR-0006). So setup offers, as an opt-in step, a session-start command hook that only prints one line into the agent's context: run the `sync-aistack` skill. Claude Code (`SessionStart` in `~/.claude/settings.json`), Codex (`~/.codex/hooks.json`, which asks the user to trust it once), Gemini CLI and Copilot CLI support this. The hook holds no token and calls nothing. Syncing with no agent running is a separate decision (DESIGN.md §5).

**Sync runs per harness.** `sync`, `get_skill`, `disable_skill` and `push_skill` take `harness`; without it they mean Claude Code, so a computer set up before this keeps working with the skill file it already has. `get_skill` returns the folder to install into. `machine_harness` records which harnesses a computer has and when each last synced.

**Defaults, all explicit.**
- A new computer starts empty, and its page offers to copy another computer's placements.
- Connecting a second harness on a computer ("add Codex to aistack") copies that computer's existing placements into it. The user asked for the connection, so nothing is silent.
- A backed-up skill is placed where it was found.
- A skill taken from a team lands in the user's own skills, and the page asks where to place it.

## What the user sees

The dashboard's navigation is a rail (you, then your teams) and a list (built in #66, before the server knew about harnesses). Under you: the Library, with waiting updates, and your computers; a computer with more than one harness lists them under it, one with a single harness is one row. A harness page lists what is placed there, with Remove, and Add skills and Copy from… for many at once. Every skill shows compact tags of where it is placed. No grid of switches.

## Not doing

- **Projects.** Skills, instruction files and MCP definitions inside a repository are shared by git, and the repository already records what a project uses. Managing them too would fight git over the same files and need to know where the repository lives on each computer. If personal, gitignored files inside a project are ever wanted, a project is identified by its normalised git remote, and files git tracks are never touched.
- **Tools without `SKILL.md`.** Cursor rules, Copilot instructions and the like need their own format: the rules resource type, later.
- **Z.ai's GLM as a harness.** It is a model plan used inside Claude Code, Codex and others, not an agent with its own folder, so it is covered by whichever agent runs it.
- **Different content per harness** for one skill.
- **A generic resource model.** MCP server definitions come next, with their own tables and their own ADR (they are entries inside a config file the harness also writes, and they can hold secrets: only the name of an environment variable is ever stored). Instruction files (`CLAUDE.md`, `AGENTS.md`) follow with another ADR, because people edit them by hand. A generic model waits for a third type (ADR-0007).

## Consequences

- Migration 0003: `machine_skill.harness` (existing rows become `claude_code`, which on SQLite is a table rebuild run by `migrate_schema`), the new unique constraint, and `machine_harness`. The harness keys are `claude_code` and `agents`.
- `services/sync_service.py` reads decisions for one harness; `services/reconciliation.py` does not change.
- The tool descriptions are near their 2,048-character limit, so the install folder comes back in `get_skill`'s result rather than in its description.
- One full sync run from a real Codex session, as was done for Claude Code, before the `agents` folder is called supported; other agents are listed as reading it, not as tested.
