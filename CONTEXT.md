# AIStack

A self-hosted, open-source control plane for AI development configuration. Each user keeps their skills in a private space that mirrors their machines, and shares them with teams and groups. The dashboard is where people see and manage this; MCP connects a coding agent to their account. Rules, agents, hooks, and MCP server definitions are planned after skills.

## Language

**Harness**:
A skills folder with a name, which the coding agents that read it load skills from (ADR-0018). Two exist: `claude_code` (`~/.claude/skills`, read by Claude Code) and `agents` (`~/.agents/skills`, read by Codex, Gemini CLI, Kimi Code, opencode, Cursor, GitHub Copilot CLI, and Amp). A skill is placed in a harness on a computer, and sync runs one harness at a time.
_Avoid_: Agent (that means a subagent definition), provider, IDE, "Codex" for the `agents` folder (it reaches every agent that reads it)

**Project**:
A git repository, known by its remote written as `host/path` (`github.com/dchristopoulos/aistack`), so the same repository is one project on every computer wherever its clone sits (ADR-0026). A repository with no remote, or whose remote is a path on disk, is a project of one computer. A folder outside git, or a repository whose top level is the home folder, is not one. A person's project is recorded only once they add it.
_Avoid_: Workspace, repo (in prose), checkout, folder

**Project folder**:
A harness's skills folder at a project's top level: `.claude/skills` for `claude_code`, `.agents/skills` for `agents`. A skill is placed in a project folder on a computer as it is placed in a global one, and every clone and worktree of the project on that computer shares the placements. AIStack writes only skill folders git ignores there.
_Avoid_: Project skills directory, local folder, repo folder

**Repository's skill**:
A skill folder inside a project folder that git tracks, or would commit because it is untracked and not ignored. It belongs to the repository: AIStack never reads, writes, backs up or replaces it, and installs no Library skill of that name there.
_Avoid_: Repo skill, checkout skill, committed skill, team skill (that is a skill shared into a team)

**Resource**:
The umbrella term for anything AIStack manages: a skill, rule, agent, hook, or MCP server definition.
_Avoid_: Config item, asset

**Canonical Skill**:
The authoritative skill stored in the AIStack server: frontmatter, instruction body, and any bundled files.
_Avoid_: Remote skill, cloud skill, original, proxy skill (dead concept, see ADR-0001)

**Install**:
A full local copy of a canonical skill, materialized into a harness's skill directory. After install the skill runs natively with no AIStack dependency.
_Avoid_: Clone, stub, proxy

**Sync**:
Reconciling a machine's actual local state (what's on disk) with its desired state on the server (which of its user's own skills are enabled for that machine). Installs the missing, updates the stale, backs up what the Library does not have yet, offers team updates, and asks the user about everything else. Never deletes local files, never flips enabled silently, never applies a teammate's change, and is not discovery (that's `list_skills`). See ADR-0004, ADR-0006, ADR-0015.
_Avoid_: Pull, update-all

**Name**:
The stable machine-friendly identifier of a canonical skill, taken from its frontmatter `name` (e.g. `unslop`). Used in tool calls and directory names; there is no separate slug or display-name field: pretty rendering is a UI concern.
_Avoid_: Slug, skill id, display name

**Revision**:
The server-side integer that orders a skill's versions. Distinct from the author's optional frontmatter `version` string, which is preserved and shown when present.
_Avoid_: Version number (ambiguous)

**Vault**:
The canonical skills one place holds: a user's Library, or a team. A skill name is unique within a vault. Only the Library is installed from; a team's vault is shared into and taken from. Before ADR-0015 a server was a single vault everyone installed from; it became the team `everyone`, an ordinary team since ADR-0019.
_Avoid_: Registry, marketplace, "the vault" for the whole server

**Library**:
A user's personal team: private, a mirror of what is on their computers, and the only place their machines install from. On the wire it is a skill whose `team` is null; in code it keeps its older name, as in `visibility.my_skills`.
_Avoid_: My skills (its name until #62), personal vault, private team, workspace, home

**Log**:
In local mode, the list of events that built a Library: one per change, recorded in the same transaction (`library_event`) and, for a Library on GitHub, one file each in the repository (ADR-0025). Replaying it in order gives the same Library on any computer.
_Avoid_: history (git's word for commits), changelog, journal

**Copy**:
The SQLite database on one computer that holds a GitHub Library, built by replaying the log, and safe to delete: it is rebuilt from the repository.
_Avoid_: cache (it is the Library the tools read), mirror, replica

**Team**:
A set of people who share skills (ADR-0015). A member shares into it and takes from it; nothing installs from it directly. Every team is created by a user and joined with its invite code or invite link. Until ADR-0019 every user was also in a server-wide team, `everyone`; an upgraded server keeps it as an ordinary team.
_Avoid_: Org, tenant, workspace, account

**Group**:
A named set of skills and members inside a team, identified by its path: `backend`, `backend/aistack`. Private (only the people added to it see it) or open (whoever sees the group above it does).
_Avoid_: Folder, sub-team, role, channel

**Team admin**:
A member who manages a team's invite code, members, groups, and where its skills sit. Whoever creates a team is its first admin, and a team always has one while anyone is in it. An admin can let a member invite, which lets them make the invite link and nothing else.
_Avoid_: Owner, moderator

**Back up**:
Putting a local skill into the Library (`push_skill`). Sync lists what needs it and the agent does it without asking, because nothing is shared.
_Avoid_: Import, upload (as a term of art), publish

**Share**:
Copying the latest revision of one of your own skills into a team or one of its groups. The team's copy has its own history from then on.
_Avoid_: Publish, push to a team, release

**Take**:
Copying a team skill's latest revision into the Library, which is how it is installed and how an offered update is accepted. The copy stays yours if you leave the team.
_Avoid_: Subscribe, follow, fork, pull

**Team update**:
A team's copy being newer than the one you took. Always an offer the user answers, never applied by sync.
_Avoid_: Auto-update, notification (as a term of art)

**Unsubscribe**:
Asking not to be offered team updates from a group or the groups under it. It hides nothing.
_Avoid_: Mute, leave (that is for teams), hide

**Invite code**:
Two different things. The server's invite code is operator config and admits a new person to the server (`join`). A team's invite code is made by a team admin, starts with `aistinv_`, and admits an existing user to that team (`join_team`), or a new person to the server and that team at once (`join`, ADR-0019). Say which one.
_Avoid_: Bare "invite code" where both could be meant, password, key

**Dashboard**:
The web application at `/app` where a user sees their skills, machines, teams, and groups and manages them. Signed into by a short-lived link from `open_dashboard`; there are no passwords (ADR-0017).
_Avoid_: Admin panel, console, UI (as a term of art)

**Machine**:
A registered computer belonging to one user, authenticating with its own permanent token. The unit that enabled skills (and later, local resources) are scoped to.
_Avoid_: Device, host

**Enabled**:
Desired state: this one of the user's own skills should exist in this harness on this machine. Set by install ("install X" = enable + materialize), by backing a skill up, or by a toggle on the dashboard; cleared by remove. Sync enforces it. A row with `enabled = false` means explicitly disabled; no row means no decision: the sync contract treats these differently.
_Avoid_: Installed (that's actual state on disk), active

**Pushed by**:
The AIStack user who pushed a revision into their own skills or shared it with a team. A copy taken from a team keeps the name of whoever shared it there. A person the operator forgot shows as their pseudonym, `former-member-` and four random hex characters (ADR-0034). Pure provenance: it never claims authorship, because people back up and share third-party skills.
_Avoid_: Author, created by, uploaded by

**Origin**:
Optional source URL on a canonical skill (GitHub repo, marketplace page), recorded at the first push when known and never overwritten. It is a record only: the check for an unrelated skill sharing a name is now made when sharing, from whether the sharer's copy is linked to the team's (ADR-0015).
_Avoid_: Upstream, remote

**Transfer URL**:
A short-lived signed URL on the AIStack server that carries one skill archive in one direction. `push_skill` returns an upload URL and `get_skill` a download URL; the agent moves the bytes with `curl` and `tar`. See ADR-0010.
_Avoid_: Presigned link, download link (as a term of art), manifest (the inline form was replaced)

**Ticket**:
The signed payload inside a transfer URL: purpose, machine, user, skill, expiry, and a MAC. A credential for five minutes. A dashboard link and a dashboard session are tickets too, each with its own purpose.
_Avoid_: Token (that means a machine token), session, nonce

**Orphan** _(retired by ADR-0015)_:
Was: a skill on disk that the shared vault did not know, reported and never pushed unasked. Now such a skill is backed up to the Library, which is private. See **Back up**.
_Avoid_: Using the word for anything current

**Adopt**:
Enabling a skill on this machine that already exists both on disk and in the Library (pushed from another of the user's machines, say), so future revisions flow to it. Always a question, never silent, because adoption means later revisions overwrite that folder.
_Avoid_: Auto-enable, link

**Admin**:
The server's operator role, distinct from a team admin: the first user to join (`is_admin`). Nothing reads it today, so it grants no power. The server can only observe join order, not who deployed it: in practice the operator joins first, alone, before sharing the invite code. Server-level powers are `aistack admin` commands documented in `docs/OPERATING.md` (revoke a machine, recover a locked-out user); the dashboard has no page for them.
_Avoid_: Owner, superuser
