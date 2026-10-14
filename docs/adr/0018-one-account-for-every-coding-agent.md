# One account for every coding agent on a computer, Codex first

Status: proposed, 2026-10-14. Not built. Accepting it is the go-ahead for the work in #62.

AIStack installs skills for Claude Code only. A person who also uses Codex keeps a second copy of the same skills by hand, which is the drift AIStack exists to end. Codex reads the same `SKILL.md` format (a `name` and a `description`), from `~/.agents/skills`, and picks up a new skill without a restart. So does any tool that follows the shared Agent Skills convention for that folder.

## The model

**A harness is a skills folder with a name.** What AIStack manages on a computer is a folder of skills, not a program. Claude Code reads `~/.claude/skills`. Codex reads `~/.agents/skills`, and so may other tools. A harness entry in the code is: a key (`claude_code`, `codex`), a display name, its skills folder per operating system, and how to connect it to an MCP server. Adding the next tool is one entry, and a tool that reads a folder already listed needs no entry at all.

**One token per computer, shared by every harness on it.** A token is a person on one computer (ADR-0015). Claude Code and Codex on the same MacBook are the same person on the same computer, so both use its token. Codex holds it in `~/.codex/config.toml` as the `Authorization` header of a streamable HTTP server, as Claude Code holds it in its own configuration.

**The decision stays per computer; a harness can be left out.** "This skill should be on this computer" remains one `machine_skill` row (ADR-0004). By default it applies to every harness on the computer, because people want the same skills in every tool, and making them choose twice per skill is the work AIStack should remove. A rare exception is a row in a new table, `machine_skill_harness_off`: this skill is on for this computer but not for this harness. No per-harness copy of every decision exists.

**Sync runs per harness.** The agent says which harness it is: `sync(local, harness)`, and the hashes it sends are of that harness's folder. The server compares them with the computer's decisions, minus that harness's exceptions. The reconciliation table (ADR-0007) does not change: a skill left out of one harness reaches it as `disabled`, which already means "ask about the folder, never delete it". A sync without `harness` is Claude Code, so a computer set up before this keeps working with the skill file it already has.

**Which harnesses a computer has is recorded when it first syncs.** `machine_harness` holds the computer, the harness, and when it last synced. That is what the dashboard shows as the tools on a computer, and "last sync" stops being a guess.

## What the user sees

- Setup asks nothing new. The setup page tells the agent to connect itself, and an agent knows whether it is Claude Code or Codex. Setting up the second tool on a computer that already has a token is "add Codex to aistack" in the first tool, which returns one command, like `add_machine` does for a second computer.
- `sync-aistack` is installed into each harness's folder, so "sync aistack" works in both.
- On the dashboard, a computer lists its skills with one switch per harness, both on by default (the navigation prototype for #62).

## Not doing

- **Tools without `SKILL.md`.** Cursor rules, Copilot instructions and the like need their own format. That is the rules resource type, later, not a harness.
- **Projects.** Skills inside a repository (`.claude/skills`, `.agents/skills`) are shared by git with everyone who clones it. AIStack managing them too would fight git over one folder, and would need to know where the repository lives on each computer. If people ask for it, the repository's remote URL is a key that is the same on every computer, and sync already runs inside the project. Until then, no.
- **A different set of skills per harness by default.** It is possible, as an exception, and it stays one.

## Consequences

- Migration 0003: `machine_harness` and `machine_skill_harness_off`.
- `sync`, `get_skill` and `push_skill` learn which folder they are working in; `get_skill`'s install steps name the folder instead of `~/.claude/skills`. The tool descriptions are near their 2,048-character limit, so the folder comes back in the result rather than in the description.
- One full sync run from a real Codex session, as was done for Claude Code, before this is called supported.
