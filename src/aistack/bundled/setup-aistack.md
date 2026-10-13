# Set up AIStack on this computer

You are an AI coding agent. The user asked you to connect this computer to the AIStack server at {server_url}, which keeps their team's skills in sync. Do the steps below in order, with your shell. It takes about a minute and ends with one restart of Claude Code.

You need three things from the user. Ask for whichever they did not give you:

- the **invite code** for this server
- a **username**: a short handle their team will recognize, like `maria`. It is shown next to every skill they push.
- a **name for this computer**, like `macbook` or `work-laptop`. Suggest the hostname.

Work out the operating system yourself: `MACOS`, `WINDOWS`, or `LINUX`.

On Windows, use `curl.exe` wherever a step says `curl`.

## 1. Check it is not already set up

```
claude mcp get aistack
```

If that shows a server, stop. This computer is already connected. Tell the user so, and that they can say "sync aistack".

## 2. Install the sync skill

Create the global skills directory first if it does not exist. Claude Code only watches a skills directory that existed when it started, and creating it now is what lets skills load without a restart later.

```
mkdir -p ~/.claude/skills/sync-aistack
curl -sS -o ~/.claude/skills/sync-aistack/SKILL.md {server_url}/setup/sync-aistack/SKILL.md
```

Open the file and confirm it starts with `---` and `name: sync-aistack`. If it is a JSON error or an HTML page instead, stop and show the user what came back.

## 3. Register this computer

Write this JSON to a temporary file, with the three values filled in. A file avoids every shell's quoting rules.

```json
{"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "join", "arguments": {"username": "<username>", "machine_name": "<computer name>", "os": "<MACOS, WINDOWS, or LINUX>"}}}
```

Send it with the invite code as the bearer token:

```
curl -sS {mcp_url} -H "Authorization: Bearer <invite code>" -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" --data @<that file>
```

Then delete the temporary file.

Read the response:

- `result.structuredContent.token` is this computer's permanent token. Go to step 4.
- `result.isError` is true: the text in `result.content` says what to fix. Fix it and send again. If it says the username is taken and this is the same person on a second computer, stop: they should say "add my other computer" from a computer that is already connected, and paste the command it gives them here.
- An HTTP 401 with no result: the invite code is wrong. Ask the user to check it.

## 4. Connect Claude Code

```
claude mcp add --transport http --scope user aistack {mcp_url} --header "Authorization: Bearer <token>"
```

`--scope user` matters. Without it the server is only connected in the current folder.

## 5. Finish

Do not save the invite code anywhere, and do not repeat the token back to the user. It is now in Claude Code's own configuration, which is the only place it needs to be.

Tell the user:

- This computer is connected to AIStack as `<username>` / `<computer name>`.
- **Restart Claude Code once.** It reads its server list at startup, so the new connection appears after a restart. This is the only restart: skills installed from now on load without one.
- After restarting, say **"sync aistack"** to install what this computer should have, **"what skills does the team have?"** to browse, or **"push my <skill> skill to aistack"** to share one. Syncing at the start of a work session, like `git pull`, keeps everything current.
