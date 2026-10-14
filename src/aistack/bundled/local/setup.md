# Set up AIStack on this computer

You are an AI coding agent. The user asked you to set up AIStack, which backs up their skills to a Library of their own and keeps every computer of theirs current. Here AIStack runs on this computer: your agent starts it, and only the Library's storage is shared between computers. Do the steps below in order, with your shell. It ends with one restart of your coding agent.

The steps are written for Claude Code and for Codex; where the two differ, each step says what to do in either. Connecting one of them is enough for the whole computer: sync keeps Claude Code's skills folder and the shared `~/.agents/skills` folder in line, and that shared folder is what Codex, Gemini CLI, Kimi Code, Cursor, Copilot CLI, opencode, and Amp read. If you are another agent, stop and tell the user to run this setup from Claude Code or Codex.

## 1. Check it is not already set up

Run `claude mcp get aistack` in Claude Code, or `codex mcp get aistack` in Codex. If it shows a server, stop: this computer is already connected, and the user can say "sync aistack". If it says there is no such server, go on.

## 2. Ask where the Library should live

Put these three choices to the user, each with its line, and recommend the second when they have more than one computer:

1. **Only this computer.** Free and nothing to set up. No other computer can reach it.
2. **A free PostgreSQL database, shared by all their computers.** Neon is recommended: free, and it wakes by itself after a quiet spell. Supabase works too, but pauses after about a week unused and needs a click to wake. Each computer keeps the database's address, so if a laptop is lost they reset the database password and paste the new address on the others.
3. **A computer that stays on, running the AIStack server.** Free on a computer they own, if it stays switched on. It is the only choice that works for a team. If they pick this, stop here: they need the server's address and an invite code, and then "Set up AIStack: fetch <server address>/setup and follow it."

## 3. Get the database's address (choice 2 only)

Walk the user through it; they create the account themselves.

- **Neon:** sign in at https://neon.tech, create a project, open **Connect**, turn **Connection pooling off**, and copy the connection string. It starts with `postgresql://`.
- **Supabase:** create a project at https://supabase.com, open **Connect**, choose **Session pooler**, and copy the connection string with the database password filled in. Its user looks like `postgres.<project ref>`, and it works over IPv4.

Every computer of theirs uses this same address. Never print it back in full: it holds the password.

## 4. Check AIStack starts

`uvx` runs AIStack without installing it. If `uv --version` fails, ask the user before installing uv, then follow https://docs.astral.sh/uv/getting-started/installation/ (on macOS and Linux, `curl -LsSf https://astral.sh/uv/install.sh | sh`).

Start AIStack once with its input closed, so it connects, prepares the Library, registers this computer, and exits. For choice 2, put the address in the environment of this one command:

```bash
AISTACK_DATABASE_URL='<address>' uvx aistack-mcp@latest < /dev/null
```

For choice 1, leave `AISTACK_DATABASE_URL=...` out. On Windows PowerShell, set `$env:AISTACK_DATABASE_URL` first and pipe `$null` into the command instead.

It prints nothing when it works. An error says what is wrong: an address it cannot reach, a wrong password, or a database that already holds a team's server, which local mode will not open.

## 5. Install the sync skill

Create the skills folder first if it is missing: Claude Code only watches a skills folder that existed when it started. In Claude Code:

```bash
mkdir -p ~/.claude/skills/sync-aistack
uvx aistack-mcp@latest sync-skill > ~/.claude/skills/sync-aistack/SKILL.md
```

In Codex, the same into `~/.agents/skills/sync-aistack`. Check the file starts with `---` and `name: sync-aistack`.

## 6. Connect your coding agent

In Claude Code, with `-e AISTACK_DATABASE_URL='<address>'` for choice 2 and without it for choice 1:

```bash
claude mcp add --scope user -e AISTACK_DATABASE_URL='<address>' aistack -- uvx aistack-mcp@latest
```

In Codex, add this to `~/.codex/config.toml`, creating the file if needed and keeping everything already in it, then check it with `codex mcp get aistack`. Leave out the `env` line for choice 1.

```toml
[mcp_servers.aistack]
command = "uvx"
args = ["aistack-mcp@latest"]
env = { AISTACK_DATABASE_URL = "<address>" }
startup_timeout_sec = 60
tools.sync.approval_mode = "approve"
tools.get_skill.approval_mode = "approve"
tools.push_skill.approval_mode = "approve"
```

`startup_timeout_sec` gives AIStack time to download a new release when it starts after an update; Codex otherwise stops waiting after a few seconds. The three `tools` lines approve only what sync does without asking: comparing, installing, and backing up to the user's private Library. Tell the user so in one line. `@latest` keeps every computer on the same release, so when one upgrades the shared Library, the others follow at their next start.

## 7. Offer to sync at the start of every session

Ask whether to sync AIStack at the start of every session, and recommend it. If they agree, add a `SessionStart` hook: in Claude Code to `~/.claude/settings.json`, in Codex to `~/.codex/hooks.json`. Read the file first, or start from `{}`, and keep everything already in it. Add this entry to the list under `hooks.SessionStart`, creating missing keys, unless an entry with this exact command is already there:

```json
{"matcher": "startup", "hooks": [{"type": "command", "command": "echo AIStack: before the first task, run the sync-aistack skill.", "timeout": 10}]}
```

Check the file is still valid JSON. Codex asks the user to trust a new hook once, in `/hooks`.

## 8. Finish

Tell the user:

- **Restart Claude Code once**, or Codex if that is the agent you are. It reads its server list at startup. Skills installed from now on load without a restart.
- After restarting, say **"sync aistack"**. It backs up this computer's skills to the Library and installs what their other computers put there.
- **"open my aistack dashboard"** opens the Library in the browser, on this computer, for as long as the session runs. `uvx aistack-mcp dashboard` in a terminal does the same without an agent.
- For another computer, paste the same setup there and choose the same database. For choice 1 there is nothing to share.
