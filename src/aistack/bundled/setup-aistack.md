# Set up AIStack on this computer

You are an AI coding agent. The user asked you to connect this computer to the AIStack server at {server_url}, which backs up their skills, keeps every computer of theirs current, and lets them share skills with teams. Do the steps below in order, with your shell. It takes about a minute and ends with one restart of your coding agent.

The steps are written for Claude Code and for Codex; where the two differ, each step says what to do in either. Connecting one of them is enough for the whole computer: sync keeps Claude Code's skills folder and the shared `~/.agents/skills` folder in line, and that shared folder is what Codex, Gemini CLI, Kimi Code, Cursor, Copilot CLI, opencode, and Amp read. If you are another agent, stop and tell the user to run this setup from Claude Code or Codex; their skills will still reach you through that folder.

You need three things from the user. Ask for whichever they did not give you:

- an **invite code**: the server's own, or a team's, which starts with `aistinv_`. Either one works here, and a team's code also makes them a member of that team.
- a **username**: a short lowercase handle their team will recognize, like `maria` or `j.smith` (letters, digits, and single `.`, `-`, `_`). It is shown next to every skill revision they push or share.
- a **name for this computer**, like `macbook` or `work-laptop`. Suggest the short hostname, without the domain. It can be at most 64 characters.

Work out the operating system yourself: `MACOS`, `WINDOWS`, or `LINUX`.

On Windows, use `curl.exe` wherever a step says `curl`.

## 1. Check it is not already set up

In Claude Code:

```
claude mcp get aistack
```

In Codex:

```
codex mcp get aistack
```

If it prints an error saying there is no MCP server by that name and exits non-zero, this computer is not connected yet: go to step 2.

If it shows a server, stop. This computer is already connected. Tell the user so, and that they can say "sync aistack".

## 2. Install the sync skill

Create the global skills directory first if it does not exist. Claude Code only watches a skills directory that existed when it started, and creating it now is what lets skills load without a restart later.

In Claude Code:

```
mkdir -p ~/.claude/skills/sync-aistack
curl -sS -o ~/.claude/skills/sync-aistack/SKILL.md {server_url}/setup/sync-aistack/SKILL.md
```

In Codex, the same into the shared folder:

```
mkdir -p ~/.agents/skills/sync-aistack
curl -sS -o ~/.agents/skills/sync-aistack/SKILL.md {server_url}/setup/sync-aistack/SKILL.md
```

Open the file and confirm it starts with `---` and `name: sync-aistack`. If it is a JSON error or an HTML page instead, stop and show the user what came back.

## 3. Register this computer

Write this JSON to a temporary request file, with the three values filled in. A file avoids every shell's quoting rules.

```json
{"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "join", "arguments": {"username": "<username>", "machine_name": "<computer name>", "os": "<MACOS, WINDOWS, or LINUX>"}}}
```

Send it with the invite code as the bearer token, saving the response to a second temporary file so the token in it never reaches the terminal:

```
curl -sS {mcp_url} -H "Authorization: Bearer <invite code>" -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" --data @<request file> -o <response file>
```

The response file is one plain JSON object, not an event stream. Read it:

- `result.structuredContent.token` is this computer's permanent token. Go to step 4.
- `result.isError` is true: the text in `result.content` says what to fix. Fix it and send again. If it says the username is taken and this is the same person on a second computer, stop: they should say "add my other computer" from a computer that is already connected, and paste the command it gives them here.
- An HTTP 401 with no result: the invite code is wrong. Ask the user to check it.

## 4. Connect your coding agent

In Claude Code:

```
claude mcp add --transport http --scope user aistack {mcp_url} --header "Authorization: Bearer <token>"
```

`--scope user` matters. Without it the server is only connected in the current folder.

In Codex, add this to `~/.codex/config.toml`, creating the file if it does not exist and keeping everything already in it. `codex mcp add` cannot set a header, so the block is written by hand. Then check it with `codex mcp get aistack`.

```toml
[mcp_servers.aistack]
url = "{mcp_url}"
http_headers = { "Authorization" = "Bearer <token>" }
```

Then delete both temporary files. The response file holds the token.

## 5. Offer to sync at the start of every session

Ask the user whether Claude Code should sync AIStack at the start of every session, and recommend it: their computers then stay current without anyone remembering to ask. If they decline, skip to step 6.

If they agree, add a `SessionStart` hook: in Claude Code to `~/.claude/settings.json`, in Codex to `~/.codex/hooks.json`. It runs no program and holds no token: it only puts one line in front of you when a session starts, telling you to sync. Read the file first, or start from `{}` if it does not exist, and keep everything already in it. Add this entry to the list under `hooks.SessionStart`, creating the keys that are missing. If an entry with this exact command is already there, change nothing.

```json
{"matcher": "startup", "hooks": [{"type": "command", "command": "echo AIStack: before the first task, run the sync-aistack skill.", "timeout": 10}]}
```

Check that the file is still valid JSON before saving it. Codex asks the user to trust a new hook once, in `/hooks`; tell them to accept it.

## 6. Finish

Do not save the invite code anywhere, and do not repeat the token back to the user. It is now in your agent's own configuration, which is the only place it needs to be.

Tell the user:

- This computer is connected to AIStack as `<username>` / `<computer name>`.
- **Restart Claude Code once**, or Codex if that is the agent you are. It reads its server list at startup, so the new connection appears after a restart. This is the only restart: skills installed from now on load without one.
- After restarting, say **"sync aistack"**. It backs up the skills on this computer to the Library, a private space only they see, and installs whatever their other computers already put there. If they agreed to step 5, every new session starts with a sync; otherwise syncing at the start of a work session, like `git pull`, keeps everything current.
- **"open my aistack dashboard"** gives a link to the web dashboard, where they see every skill and which computer has it, and manage teams, groups, and members.
- To work with other people: **"what skills do my teams have?"** to browse, **"install <skill> from <team>"** to take one, **"share <skill> with <team>"** to give a team a copy of theirs, **"create a team called <name>"** to start one, and **"join a team with this code"** when someone sends them a team invite code. If an invite link brought them here, they are already in that team.
- A teammate's change to a shared skill never reaches this computer by itself. Sync reports it as an offer, and they decide each time.
