# One connected agent syncs every skills folder on its computer

Status: proposed, 2026-10-14. Amends ADR-0018, which planned a separate "add Codex to aistack" step per agent.

ADR-0018 made a harness a skills folder: `claude_code` (`~/.claude/skills`) and `agents` (`~/.agents/skills`, read by Codex, Gemini CLI, Kimi Code, Cursor, Copilot CLI, opencode and Amp). It still pictured each agent connecting to AIStack on its own, and a second agent on a computer being added by a command that copied the first one's placements. That is a step the person should not have to know about.

## Decisions

**The server tracks folders, not callers.** Every `sync`, `get_skill`, `push_skill` and `disable_skill` call names the folder it is about. Which program made the call does not matter, and the server does not try to find out: a token says who and which computer, and nothing in an MCP request reliably says which agent sent it.

**One connected agent is enough for a computer.** The `sync-aistack` skill finds the folders the computer's agents read (it looks for `~/.claude`, `~/.agents/skills`, `~/.codex`, `~/.gemini`, `~/.kimi-code`, `~/.cursor`, `~/.copilot`, `~/.config/opencode`, `~/.config/amp`) and syncs each in turn. Codex on a computer where Claude Code is connected gets its skills without connecting to anything. There is no second token and no "add Codex" command.

**The two folders are made to match once, by asking.** `sync` reports `first_sync` the first time a folder syncs on a computer. When either folder did, and they hold different skills, the skill asks once whether to use the same skills in both, naming what each would gain; yes is one `get_skill` per missing skill, in each direction. After that answer each folder is synced on its own, with no further questions.

**Setup runs from Claude Code or from Codex.** The setup page says how to connect either, with the same token and one paste. Codex holds the token as a static `Authorization` header in `~/.codex/config.toml`; its CLI cannot set one, so the agent writes that block.

**The sync skill goes where an agent talks to AIStack.** Anywhere else it would tell an agent with no connection to sync. The server offers to install or refresh `sync-aistack` in Claude Code's folder, which is how a computer connected by `add_machine` gets it, and in the shared folder only when it is already there, which is where setup puts it when Codex is the connected agent. The skill installs it only into the running agent's own folder, so Codex connected on a computer that also has Claude Code does not put it in Claude Code's.

## Consequences

- `sync` gains `first_sync`, from whether its `machine_harness` row was created by this call.
- The opt-in session-start hook (ADR-0018) is offered for Codex too, in `~/.codex/hooks.json`, which Codex asks the user to trust once.
- A person who talks to AIStack from two agents on one computer connects the second with the same token. That is not automated: one connected agent already keeps every folder current.
