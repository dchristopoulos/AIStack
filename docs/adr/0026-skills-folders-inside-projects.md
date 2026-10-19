# Skills folders inside a project

Status: accepted, 2026-10-16. Amends ADR-0018, which left projects out and set the terms for taking them in: a project is known by its normalised git remote, and files git tracks are never touched. Research: [docs/research/coding-agent-config-layout.md](../research/coding-agent-config-layout.md).

Some skills belong to one repository, such as how its API is laid out or how it is released. Placed globally, they load in every session in every repository. Kept by hand in the repository's `.claude/skills`, they live on one computer, untracked, and are lost with the clone. The agents already read project folders. Claude Code reads `.claude/skills` from the working directory up to the repository's top level. Codex, Gemini CLI, Kimi Code, opencode, Cursor, Copilot CLI and Amp read `.agents/skills` the same way. Those are the two harness folders again, one level down.

## Decisions

**A project is a git repository, known by its remote.** Its key is the `origin` remote, or the only remote, written as `host/path`: scheme, credentials, port and `.git` are dropped, and the rest is lowercased (`github.com/dchristopoulos/aistack`). The same key on two computers is one project, wherever each keeps its clone. A repository with no remote, or whose remote is a path on disk, is a project of that computer alone. A folder outside a git work tree is not a project. Neither is a repository whose top level is the home folder, because its skills folders are the global ones.

**Its folders sit at the top level.** `<top level>/.claude/skills` is `claude_code` and `<top level>/.agents/skills` is `agents`, the harnesses a computer already has. Both agents read upward to the top level, so a skill placed there is seen from every folder of the repository.

**A skill placed in a project folder is one more placement.** Desired state is one row per computer, harness, project and skill, kept in tables of its own:
- `project`: the project.
- `machine_project`: a project folder on a computer. It records that the person chose to manage it, where it was last seen, and when it last synced.
- `machine_project_skill`: the placements.

The reconciliation table (ADR-0007) and the rule that sync never deletes (ADR-0006) apply unchanged, one folder at a time. Every clone and worktree of a project on one computer shares these decisions, so a new worktree gets the project's skills at its first sync.

**AIStack touches only what git ignores.** In a project folder, a skill folder that git tracks belongs to the repository. So does one git would commit, because it is untracked and not ignored. AIStack never writes, deletes, backs up or updates such a folder, and does not install a Library skill of that name there. A skill folder that git ignores is personal. Sync treats it as it treats a global folder, and backs it up without asking. Before AIStack writes a folder, it makes git ignore that folder in this clone through `.git/info/exclude`, which every worktree of the clone shares and git never commits. It never edits `.gitignore`, which belongs to the repository. A skill that the team commits stays git's to share.

**A project is managed once its owner says so, on a computer.** Every sync names the repository the session is in, and the report says whether this computer manages it. Two things start managing a project on a computer. One is saying "add this project to aistack" in a session inside it. The other is adding it on the dashboard to that computer when another computer already manages it. A repository someone only works in is never recorded.

**Every folder is named the same way on the wire.** `sync`, `get_skill`, `push_skill` and `disable_skill` take an optional `project`: the key that sync reported. Without it they mean the global folder, exactly as today.
- In server mode, `sync` also takes `here` (the top level and the remote, so the server computes the key) and `repository` (the names of the folders that belong to the repository).
- In server mode, `get_skill` returns a project's folder relative to the top level, so a path the agent sent never comes back inside a command.
- In local mode, the tools take the working directory and run git themselves.

**A project's first sync offers what the person's other computers have there.** The report lists the skills placed in that project on their other computers, and the agent asks once, as it does at a computer's first sync (ADR-0021).

**A new kind of log event is replayed one release before any release records it.** Local mode records project changes as four new event kinds (ADR-0025). A release that meets a kind it does not know stops reading the log until it is updated. So the release that replays these kinds ships first. The release that records them follows once computers have updated themselves, which `bootstrap/self_update.py` does daily. Adding a field to an existing kind is not an option: today's release would apply a project placement as a global one.

## Not doing

- **Skills a repository commits.** They are listed by name so that nothing collides with them. They are never read, backed up or shown. Git already shares them with everyone who clones the repository.
- **Folders outside git, nested skills folders, and other agents' project folders** (`.codex/skills`, `.gemini/skills`, `.kimi-code/skills`, `.github/skills`). A monorepo's top level already reaches every package below it.
- **One name for different skills.** A Library name is one skill (ADR-0015). A `conventions` skill that differs per repository needs a name per repository. Sync suggests one when a project's copy differs from the Library's.
- **Teams placing skills in repositories.** A team's skill reaches a computer only through its member's Library (ADR-0015). A team that wants a skill in a repository commits it there.
- **Following a repository that moves**, or treating a fork or a mirror as the same project. A new remote is a new project.
- **Looking for repositories on disk.** AIStack only ever sees the repository a session runs in.
- **Instruction files and MCP definitions inside a project.** They wait for their own records (ADR-0018).

## Consequences

- One migration creates the three tables and is `older_releases_compatible = True`. `machine_skill` is not touched. Every release before this one selects a machine's decisions by harness alone, so a project column there would read as a global placement.
- Every foreign key in the new tables cascades. An older release that rebuilds a GitHub Library's copy (ADR-0025) empties the tables it knows, and it cannot know these.
- A skill removed from the Library is wanted nowhere. Sync reads an archived skill as disabled in every folder. That also covers project placements that an older release's removal left enabled.
- In server mode the agent runs git, so the git rule is held by the steps in the `sync-aistack` skill and by the server refusing every name the agent listed as the repository's. Local mode holds the rule in code.
- An install that creates a project's skills folder mid-session may need `/reload-skills` in Claude Code, so the result says when the install created the folder.
- The `sync` tool description is at its limit, so its shell commands move to the `sync-aistack` skill to make room for the new arguments.
- AGENTS.md gains the two rules above: project folders are written only where git ignores them, and a new event kind is replayed one release before it is recorded.

The longer design, with wire examples, the schema for both databases, event formats, the page, open questions and what could not be verified, is in [the October 2026 projects design](https://github.com/dchristopoulos/AIStack/blob/v0.1.1/docs/audits/2026-10/projects-design.md).
