# Set up AIStack on this computer

You are an AI coding agent. The user asked you to connect this computer to the AIStack server at {server_url}, which backs up their skills, keeps every computer of theirs current, and lets them share skills with teams. Do the steps below in order, with your shell. Setup ends with one restart of your coding agent.

The steps are written for Claude Code and for Codex; where the two differ, each step says what to do in either. Connecting one of them is enough for the whole computer: sync keeps Claude Code's skills folder and the shared `~/.agents/skills` folder in line, and that shared folder is what Codex, Gemini CLI, Kimi Code, Cursor, Copilot CLI, opencode, and Amp read. If you are another agent, stop and tell the user to run this setup from Claude Code or Codex; their skills will still reach you through that folder.

For Codex, use `CODEX_HOME` when set everywhere these steps show `~/.codex`; the shared skills folder remains `~/.agents/skills`.

## If they have a computer code

A code from **Computers → Add a computer**, or a recovery code from the server operator, connects this computer to an existing account. Run the copied command in a terminal on this computer:

```text
uvx aistack-mcp join "{mcp_url}" "<computer code>"
```

Use the dialog's POSIX or PowerShell command for the shell in use. Install uv first if it is missing. Keep Add a computer open and approve only the request just started. Its reported name and operating system are not proof of identity. Approval is required unless the code explicitly disables it; operator recovery codes have no approval. Cancellation, expiry or denial needs a fresh code.

The program checks server support and the computer binding, installs AIStack, preserves unrelated agent settings and hooks, and configures the chosen agents. It installs active Library skills when selected, keeps different local copies for a decision, and runs sync. Start empty leaves Library placements undecided and still backs up local skills privately. Never repeat credentials in chat or logs, and never pass the permanent token to a subprocess. Public plain HTTP is refused unless the person explicitly accepts `--allow-http`; private HTTP still warns that it is unencrypted.

If interrupted, run the same command again. A protected `.aistack/joining.json` keeps the request and, only while needed to finish configuration, its key; setup removes it on success. If a response was lost before its credential could be saved, cancel the code or remove the incomplete computer and make a fresh code. Never claim an already connected computer from a used-code refusal: the program authenticates its existing connection first. A copied connection needs its own computer code; do not reset its fingerprint.

Follow the command's remaining instructions, including the hook trust step and one agent restart, then stop here. A team invite still goes through `join_team` after connection. The steps below create a first account with a server or team invite; they do not redeem computer codes.

You need these from the user. Ask for whichever they did not give you, in one question:

- an **invite code**: the server's own, or a team's, which starts with `aistinv_`. Either one works here, and a team's code also makes them a member of that team.
- a **username**: a short lowercase handle their team will recognize, like `maria` or `j.smith` (letters, digits, and single `.`, `-`, `_`). It is shown next to every skill revision they push or share. If they gave only their name, propose a handle from it and ask whether it suits them.
- their **name**, as teammates should read it beside the handle, like `Maria Lopez`. Optional: if they gave one, pass it; never ask twice.
- a **name for this computer**. Use the short hostname, without the domain, unless they said otherwise. It can be at most 64 characters.

Work out the operating system yourself: `MACOS`, `WINDOWS`, or `LINUX`.

On Windows, use `curl.exe` wherever a step says `curl`.

## 1. Check it is not already set up

One connection serves the whole computer, so check both agents, whichever one you are:

```
claude mcp list
grep -c '^\[mcp_servers.aistack\]' ~/.codex/config.toml
```

A command that is not installed, or a file that does not exist, counts as not connected. If `aistack` is not in the list and the count is 0, this computer is not connected yet: go to step 2.

Otherwise find where it points. `claude mcp list` shows the address after `aistack:`, or a command for an AIStack that runs on the computer itself. For Codex, this prints only the address or command line of its table:

```
sed -n '/^\[mcp_servers.aistack\]/,/^\[/p' ~/.codex/config.toml | grep -E '^(url|command) '
```

- **It is {mcp_url}.** This computer has configuration for this server. Authenticate it with `aistack sync`, or `list_skills` if its tools are available, before saying it is already connected. If that fails, repair the connection or follow copied-computer recovery; do not silently register another computer. If the user gave a team invite code (it starts with `aistinv_`), they already have an account: if you have AIStack's tools, call `join_team` with the code and tell them which team they joined; if you do not, tell them to say "join a team with this code" to the agent that is connected. Either way, stop here, and tell them they can say "sync aistack": it keeps every skills folder on this computer current. Never register this computer a second time.
- **It is another address, or a command.** This computer uses another AIStack: another server, or one that runs on this computer and keeps a Library of its own. A computer belongs to one AIStack at a time. Tell the user which one it uses now, and ask whether to switch it to this server. If they say no, stop. If they say yes: the first sync here backs up every skills folder on this computer, so those skills come along. Skills kept only in the old Library, on none of this computer's folders, stay there. For one that runs on this computer, run the command it showed with `export ~/aistack-library` first, and copy the folders the user wants into `~/.claude/skills` or `~/.agents/skills`. Then remove the old connection, `claude mcp remove aistack --scope user` in Claude Code, or the whole `[mcp_servers.aistack]` table in `~/.codex/config.toml`, and go on to step 2.

Never run `claude mcp get aistack` or `codex mcp get aistack`: they print this computer's token in full.

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

The answer to this step holds this computer's token, and it is the only copy. It is saved to `~/.aistack-setup-response.json` (`$HOME\.aistack-setup-response.json` on Windows) and kept until step 4 has connected your agent, so a setup that stops in between can finish. If that file is already there, an earlier setup registered this computer and stopped: if it holds `result.structuredContent.token`, skip to step 4 with it. Otherwise delete it and go on.

Write this JSON to a temporary request file, with the values filled in. Leave out `full_name` if the user gave no name. A file avoids every shell's quoting rules.

```json
{"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "join", "arguments": {"username": "<username>", "full_name": "<their name>", "machine_name": "<computer name>", "os": "<MACOS, WINDOWS, or LINUX>"}}}
```

Send it with the invite code as the bearer token, saving the response to the file, so the token in it never reaches the terminal:

```
curl -sS {mcp_url} -H "Authorization: Bearer <invite code>" -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" --data @<request file> -o ~/.aistack-setup-response.json
```

The response file is one plain JSON object, not an event stream. Read it:

- `result.structuredContent.token` is this computer's permanent token. Go to step 4.
- `result.isError` is true: the text in `result.content` says what to fix. Fix it and send again. If it says the username is taken:
  - The user already has an account and a connected computer: stop. They should say "add my other computer" there, and paste the command it gives them here. If they came with a team invite code, they also say "join a team with this code" there.
  - This is their only computer, and an earlier setup joined with this name but the answer was lost: stop. Whoever runs the server makes a recovery code with `aistack admin register-machine <username> --computer-code`, using the current server container, and privately sends the join command. Follow the computer-code instructions above.
  - Otherwise the name belongs to someone else: ask for another.
- An HTTP 401 with no result: the invite code is wrong. Ask the user to check it.

## 4. Connect your coding agent

In Claude Code:

```
claude mcp add --transport http --scope user aistack {mcp_url} --header "Authorization: Bearer <token>"
```

`--scope user` matters. Without it the server is only connected in the current folder.

In Codex, add this to `~/.codex/config.toml`, creating the file if it does not exist and keeping everything already in it. `codex mcp add` cannot set a header, so the block is written by hand. Then check that `grep -c '^\[mcp_servers.aistack\]' ~/.codex/config.toml` prints 1: a second block makes the whole file invalid.

```toml
[mcp_servers.aistack]
url = "{mcp_url}"
http_headers = { "Authorization" = "Bearer <token>" }
tools.sync.approval_mode = "approve"
tools.list_skills.approval_mode = "approve"
tools.get_skill.approval_mode = "approve"
tools.push_skill.approval_mode = "approve"
```

Codex otherwise asks before every AIStack call. The four `tools` lines approve only what sync does without asking: comparing, listing the Library, installing, and backing up to the user's private Library. Tell the user so in one line: everything else, such as sharing a skill with a team, still asks, and Codex still asks before writing into `~/.agents/skills`.

Check the connection: `claude mcp list` shows `aistack`, or the `grep -c` above prints 1. Only then delete the request file and `~/.aistack-setup-response.json`, which holds the token.

## 5. Install the sync program and offer a session-start hook

Install the program with `uv tool install aistack-mcp`. Locate its binary directory with `uv tool dir --bin`; use the full path of `aistack` there (`aistack.exe` on Windows). Respect `CODEX_HOME` for Codex's configuration and hooks. Run that full path with `sync` to check the authenticated connection and do the file work. Never point a hook at `uvx`: it must start without fetching a package. If installation is unavailable, keep the sync skill's manual fallback; do not claim a program hook was installed.

Ask whether to sync at session start and recommend it. If they decline, keep manual sync and skip the hook. If they agree, read the existing settings and preserve other hooks: `~/.claude/settings.json` for Claude Code or `$CODEX_HOME/hooks.json` (default `~/.codex/hooks.json`) for Codex. Add a SessionStart entry with the actual full path, quoted for the shell, followed by `sync --hook`, and a 180-second timeout. Replace the old AIStack echo or status reminder if present; do not duplicate it. For example, with the path replaced:

```json
{"matcher": "startup", "hooks": [{"type": "command", "command": "\"/full/path/to/aistack\" sync --hook", "timeout": 180}]}
```

The hook holds no token: the program reads the existing remote MCP configuration. Quiet sync prints nothing; questions, failures and unencrypted-connection warnings reach the agent. Review JSON before saving. Codex asks the user to trust a new hook once in `/hooks`; tell them to accept it. Sync does not delete files or choose an answer about local edits or team offers.

## 6. Finish

Do not save the invite code anywhere, and do not repeat the token back to the user. It is now in your agent's own configuration, which is the only place it needs to be.

Tell the user:

- This computer is connected to AIStack as `<username>` / `<computer name>`.
- **Restart Claude Code once**, or Codex if that is the agent you are. It reads its server list at startup, so the new connection appears after a restart. This is the only restart: skills installed from now on load without one.
- After restarting, say **"sync aistack"**. It backs up the skills on this computer to the Library, a private space only they see, and installs what this computer should have. It asks about undecided skills and local edits. If they agreed to step 5, every new session starts with a sync; otherwise syncing at the start of a work session, like `git pull`, keeps everything current.
- **"open my aistack dashboard"** gives a link to the web dashboard, where they see every skill and which computer has it, and manage teams, groups, and members.
- To work with other people: **"what skills do my teams have?"** to browse, **"install <skill> from <team>"** to take one, **"share <skill> with <team>"** to give a team a copy of theirs, **"create a team called <name>"** to start one, and **"join a team with this code"** when someone sends them a team invite code. If an invite link brought them here, they are already in that team.
- A teammate's change to a shared skill never reaches this computer by itself. Sync reports it as an offer, and they decide each time.
