# Rules are the second resource

Status: accepted, 2026-10-21. Amends ADR-0018, which deferred instruction files, and ADR-0026, which kept AIStack to what git ignores and never looked for files on disk. ADR-0006 (sync never deletes), ADR-0010 (no file content over MCP), ADR-0011 (one content hash) and ADR-0035 (the program does the disk work) apply unchanged.

Rules are the Markdown files a coding agent reads as instructions: `~/.claude/CLAUDE.md`, a repository's `AGENTS.md`, `.claude/rules/*.md`, `.cursor/rules/*.mdc`, `GEMINI.md`. People write them by hand, keep them in three different kinds of place, and want to see and edit them where they see their skills. Research: [docs/research/coding-agent-config-layout.md](../research/coding-agent-config-layout.md).

## Decisions

**A rule is in one of three places, and the place decides who owns it.**

| Place | Example | Owner | History |
|---|---|---|---|
| Your rules for every project | `~/.claude/CLAUDE.md`, `~/.codex/AGENTS.md` | the person, in their Library | AIStack revisions |
| The repository's rules | a committed `AGENTS.md`, `CLAUDE.md`, `.cursor/rules/x.mdc` | the repository | git |
| Your rules for a project | `.claude/rules/aistack-<name>.md`, git-ignored | the person, in their Library | AIStack revisions |

**Rules follow the person, not the computer.** A rule for every project reaches every computer the person has, in every agent it is used for. A rule for a project reaches every computer that has that project. There are no per-computer rule placements: a person who wants one computer to behave differently writes a project rule. The repository's rules already reach every clone through git.

**One file can serve several agents.** A rule names the agents it is used for ("Use this file for: Claude Code, Codex"). The program writes the same text to each agent's own file. Each agent's file is shown as it is, so what the page shows is what the agent reads; AIStack does not translate between formats.

**Every agent's files are listed in one table in code.** `services/agent_files.py` says, for each coding agent: its file for every project, the files it reads in a repository, where a personal project rule goes, and how a repository file is turned off for one person. The page and the program read the same table. v1 writes rules for Claude Code and Codex and shows the files of Gemini CLI, Cursor, GitHub Copilot CLI and opencode when they are on a computer.

**Personal project rules never stop the repository's.** Claude Code reads `AGENTS.md` only while no `CLAUDE.md` or `CLAUDE.local.md` exists, so AIStack never writes `CLAUDE.local.md`. Claude Code's personal project rules go to `.claude/rules/aistack-<name>.md`, which loads alongside everything else. Codex reads one file per folder, so its personal project rules go into `AGENTS.override.md` at the top level, which the program writes as the repository's `AGENTS.md` followed by the person's rules, under a first line that says AIStack made it. The program rewrites it whenever either part changes, which every session start checks. Both files are kept out of git through `.git/info/exclude`, as project skills are (ADR-0026).

**A repository's file can be turned off for one person.** For Claude Code the program adds the file to `claudeMdExcludes` in the project's `.claude/settings.local.json`; for Codex the override file leaves the repository's text out. The file itself is never moved, renamed or edited: it is tracked, and moving it would be a change to the repository. Other agents show the switch as unavailable, with the reason.

**A repository's file is edited on a computer and shared by a pull request.** Edit on the page saves the new text as a pending edit for that project; the program writes it into the working copy of the computer the person chose, if the file there still has the text the edit started from, and asks otherwise. Commit… takes a note saying what the change is about. The program makes a branch from the file's current commit with only that file changed, commits with the note as its message, pushes the branch, and opens a pull request with `gh` when it is installed and signed in, or prints the address that opens one. It never commits to the branch the person is on, so their other work never goes with it.

**Adding a project by its folder looks inside it once.** `aistack project add <folder>` is the explicit action ADR-0026 asks for, alongside the sentence said in a session. It records the project, then lists the repository's Markdown files: the agent files it knows from the table, and every other `.md` git tracks, by path and size. The page offers that list with the agent files ticked. Only ticked files are ever read again, and each sync uploads a ticked file's text when its hash changes, so the page shows the current text without the server ever reading a disk.

**Rules ride on `sync`.** `sync` takes an optional observation of rule files (agent, place, path, digest) and returns one action per file, as it does for skills: install, update, back up, a question, or nothing. A file's text moves through a signed transfer URL in that result, never through a tool argument or result (ADR-0010). Hashes come from `services/content_hash.py`, decisions from `services/reconciliation.py`, and the existing rules hold: sync never deletes, never overwrites an edit it has not seen, and backs up a rule it does not know without asking, because that space is private. No new MCP tool.

**Rules have tables of their own.** ADR-0007 waited for a second type to share identity, version and assignment; rules are that type. Moving skills into a generic model now would migrate every skill table before the first public release for no visible gain, so rules get `rule`, `rule_revision` (immutable, like `skill_version`), `rule_agent`, `machine_rule`, `project_file` and `project_file_edit`, and share the hashing and reconciliation code instead of the tables. A third resource type reopens the question.

**Size and secrets.** A rule is at most 64 KiB; the page warns when the files Codex reads in one project come to more than its 32 KiB default. Saving a rule that looks like it holds a credential (an `aist_` token, a private key block, a common cloud or chat token shape) shows a warning that names the line, and saves only when the person confirms. Nothing is blocked: rules are theirs.

## Not doing

- Teams sharing rules. A team shares a rule the way it shares a skill, through a member's Library, in a later release.
- Every Markdown file in a repository. READMEs and docs appear only if the person ticks them when adding the project.
- Writing rules for agents other than Claude Code and Codex in v1. Their files are shown.
- Translating one rule into each agent's format, or one generated section inside a file people also edit by hand.
- A per-computer rule.

## Consequences

- One migration creates the six tables, `older_releases_compatible = True`.
- `sync` gains optional arguments and result fields; older programs send none and see none.
- Local mode records rules as new Library log event kinds. Their replay ships one release before any release records them (ADR-0026), so local mode can show rules in the first release and edit them in the next.
- The program now runs git in a repository for two things: listing Markdown files when a project is added, and sharing an edit on its own branch. Both happen only after a person's explicit action.
- AGENTS.md and CONTEXT.md gain the terms and rules above.
