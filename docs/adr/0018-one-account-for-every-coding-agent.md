# One account for every coding agent on a computer, Codex first

Status: proposed, 2026-10-14; revised the same day after review. Not built. Accepting it is the go-ahead for the work in #62.

AIStack installs skills for Claude Code only. A person who also uses Codex keeps a second copy of the same skills by hand, which is the drift AIStack exists to end. Codex reads the same `SKILL.md` format (a `name` and a `description`), from `~/.agents/skills`, and picks up a new skill without a restart. So does any tool that follows the shared Agent Skills convention for that folder.

## The model

**A harness is a skills folder with a name.** What AIStack manages on a computer is a folder, not a program. Claude Code reads `~/.claude/skills`; Codex reads `~/.agents/skills`, and so may other tools. A harness entry in the code is a key (`claude_code`, `codex`), a display name, its folder per operating system, and how to connect it to an MCP server. Adding the next tool is one entry; a tool that reads a folder already listed needs none.

**A skill is placed in a folder, and each placement is its own decision.** Desired state becomes one `machine_skill` row per computer, harness and skill: `UNIQUE (machine_id, harness, skill_id)`. That is how people think about it ("put it in MacBook › Codex"), and it keeps every decision explicit:

- a skill backed up from the Codex folder is placed in Codex only, and does not appear in Claude Code by surprise;
- "off in Codex, never decided for Claude Code" can be said;
- the three states a decision can be in (on, off, none) are the same per folder, so the reconciliation table (ADR-0007) and the rule that sync never deletes (ADR-0006) apply unchanged, one folder at a time.

The first version of this record kept one decision per computer with a table of per-harness exceptions. It was dropped for the reasons above.

**One token per computer, shared by every harness on it.** A token is a person on one computer (ADR-0015). Codex holds it in `~/.codex/config.toml` as the `Authorization` header of a streamable HTTP server, as Claude Code holds it in its own configuration.

**Sync runs per harness.** `sync`, `get_skill`, `disable_skill` and `push_skill` take `harness`; without it they mean Claude Code, so a computer set up before this keeps working with the skill file it already has. `get_skill` returns the folder to install into. `machine_harness` records which harnesses a computer has and when each last synced.

**Defaults, all explicit.**
- A new computer starts empty, and its page offers to copy another computer's placements.
- Connecting a second harness on a computer ("add Codex to aistack") copies that computer's existing placements into it. The user asked for the connection, so nothing is silent.
- A backed-up skill is placed where it was found.
- A skill taken from a team lands in the user's own skills, and the page asks where to place it.

## What the user sees

The dashboard's navigation becomes a rail (you, then your teams) and a list. Under you: your skills, waiting updates, and your computers; a computer with more than one harness lists them under it, one with a single harness is one row. A harness page lists what is placed there, with Remove, and Add and Copy from… for many at once. Every skill shows compact tags of where it is placed. No grid of switches.

## Not doing

- **Projects.** Skills, instruction files and MCP definitions inside a repository are shared by git, and the repository already records what a project uses. Managing them too would fight git over the same files and need to know where the repository lives on each computer. If personal, gitignored files inside a project are ever wanted, a project is identified by its normalised git remote, and files git tracks are never touched.
- **Tools without `SKILL.md`.** Cursor rules, Copilot instructions and the like need their own format: the rules resource type, later.
- **Different content per harness** for one skill.
- **A generic resource model.** MCP server definitions come next, with their own tables and their own ADR (they are entries inside a config file the harness also writes, and they can hold secrets: only the name of an environment variable is ever stored). Instruction files (`CLAUDE.md`, `AGENTS.md`) follow with another ADR, because people edit them by hand. A generic model waits for a third type (ADR-0007).

## Consequences

- Migration 0003: `machine_skill.harness` (existing rows become `claude_code`, which on SQLite is a table rebuild run by `migrate_schema`), the new unique constraint, and `machine_harness`.
- `services/sync_service.py` reads decisions for one harness; `services/reconciliation.py` does not change.
- The tool descriptions are near their 2,048-character limit, so the install folder comes back in `get_skill`'s result rather than in its description.
- One full sync run from a real Codex session, as was done for Claude Code, before this is called supported.
