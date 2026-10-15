# Set up AIStack on this computer

You are an AI coding agent. The user asked you to set up AIStack, which backs up their skills to a Library of their own and keeps every computer of theirs current. Here AIStack runs on this computer: your agent starts it, and only the Library's storage is shared between computers. Do the steps below in order, with your shell. It ends with one restart of your coding agent.

The steps are written for Claude Code and for Codex; where the two differ, each step says what to do in either. Connecting one of them is enough for the whole computer: sync keeps Claude Code's skills folder and the shared `~/.agents/skills` folder in line, and that shared folder is what Codex, Gemini CLI, Kimi Code, Cursor, Copilot CLI, opencode, and Amp read. If you are another agent, stop and tell the user to run this setup from Claude Code or Codex.

## 1. Check it is not already set up

Run `claude mcp get aistack` in Claude Code, or `codex mcp get aistack` in Codex. If it shows a server, stop: this computer is already connected, and the user can say "sync aistack". If it says there is no such server, go on.

## 2. Ask where the Library should live

Put these four choices to the user, each with its line. Recommend the second when they have more than one computer, and the first when they only want to try AIStack:

1. **Only this computer.** Free and nothing to set up. No other computer can reach it.
2. **A private GitHub repository, shared by all their computers.** Free, nothing to keep switched on, nothing that pauses. They sign in to GitHub once in the browser; AIStack creates the repository and keeps it up to date, and keeps no password.
3. **A free PostgreSQL database, shared by all their computers.** For someone who already has one: they create the account and paste its address on each computer. Neon is recommended: free, and it wakes by itself after a quiet spell. Supabase works too, but pauses after about a week unused. Each computer keeps the database's address, so if a laptop is lost they reset the database password and paste the new address on the others.
4. **A computer that stays on, running the AIStack server.** Free on a computer they own, if it stays switched on. It is the only choice that works for a team. If they pick this, stop here: they need the server's address and an invite code, and then "Set up AIStack: fetch <server address>/setup and follow it."

## 3. Install AIStack

AIStack is installed once with uv, so your agent starts it directly: it starts at once, works offline, and updates itself in the background once a day. If `uv --version` fails, ask the user before installing uv, then follow https://docs.astral.sh/uv/getting-started/installation/ (on macOS and Linux, `curl -LsSf https://astral.sh/uv/install.sh | sh`). Then:

```bash
uv tool install aistack-mcp
```

It puts the `aistack-mcp` command in the folder `uv tool dir --bin` prints. Use that full path from here on, below written `<aistack-mcp>`: on macOS and Linux it is `"$(uv tool dir --bin)/aistack-mcp"`, on Windows `"$(uv tool dir --bin)\aistack-mcp.exe"`. An agent started from a desktop app may not have that folder on its path, and would then fail to start AIStack without saying why.

## 4. Prepare the place they chose, and check AIStack reaches it

**Choice 2, GitHub.** AIStack creates and fills the repository itself; the user only signs in. If `gh --version` fails, ask before installing the GitHub CLI (macOS: `brew install gh`; Windows: `winget install --id GitHub.cli`; others: https://cli.github.com). Then run `<aistack-mcp> github`:

- If it says to sign in, tell the user the code it printed and that the browser opened GitHub's sign-in page: they enter the code and approve GitHub CLI, nothing else. Then run `<aistack-mcp> github` again. It waits a little for the approval; if it still asks, ask the user whether they approved, and run it again.
- Once signed in, it finds their private `aistack-library` repository, or creates it on their first computer, and prints `AISTACK_LIBRARY_REPO=<owner>/aistack-library`. That is the Library's place below.

Do not ask the user to do anything else on GitHub.

**Choice 3, PostgreSQL.** Walk the user through it; they create the account themselves.

- **Neon:** sign in at https://neon.tech, create a project, open **Connect**, turn **Connection pooling off**, and copy the connection string. It starts with `postgresql://`.
- **Supabase:** create a project at https://supabase.com, open **Connect**, choose **Session pooler**, and copy the connection string with the database password filled in. Its user looks like `postgres.<project ref>`, and it works over IPv4.

Every computer of theirs uses this same address. Never print it back in full: it holds the password.

Run the check once, with the place in its environment: `AISTACK_LIBRARY_REPO` for choice 2, `AISTACK_DATABASE_URL` for choice 3, neither for choice 1:

```bash
AISTACK_LIBRARY_REPO='<owner>/aistack-library' <aistack-mcp> check
```

On Windows PowerShell, set `$env:AISTACK_LIBRARY_REPO` (or `$env:AISTACK_DATABASE_URL`) first and run `& <aistack-mcp> check`. The check prepares the Library, registers this computer, and says where the Library lives. Otherwise it says what is wrong: a repository it cannot reach, a database address or password that is wrong, or a database that already holds a team's server, which local mode will not open. Fix that before going on.

## 5. Install the sync skill

In Claude Code:

```bash
<aistack-mcp> sync-skill ~/.claude/skills
```

In Codex, the same with `~/.agents/skills`. It writes `sync-aistack/SKILL.md` in that folder, creating what is missing, and prints where. Do it before connecting: Claude Code only watches a skills folder that existed when it started.

## 6. Connect your coding agent

In Claude Code, with the same variable the check used (`-e AISTACK_LIBRARY_REPO=...` for choice 2, `-e AISTACK_DATABASE_URL=...` for choice 3, none for choice 1), and the full path written out:

```bash
claude mcp add --scope user -e AISTACK_LIBRARY_REPO='<owner>/aistack-library' aistack -- <aistack-mcp>
```

In Codex, add this to `~/.codex/config.toml`, creating the file if needed and keeping everything already in it, then check it with `codex mcp get aistack`. The `env` line holds the same variable the check used; leave it out for choice 1.

```toml
[mcp_servers.aistack]
command = '<full path to aistack-mcp>'
env = { AISTACK_LIBRARY_REPO = '<owner>/aistack-library' }
startup_timeout_sec = 60
tools.sync.approval_mode = "approve"
tools.list_skills.approval_mode = "approve"
tools.get_skill.approval_mode = "approve"
tools.push_skill.approval_mode = "approve"
```

Keep the single quotes: they take a Windows path's backslashes and a password's symbols as they are. `startup_timeout_sec` gives AIStack time to read a large Library on its first start; Codex otherwise stops waiting after a few seconds. The four `tools` lines approve only what sync does without asking: comparing, listing the Library, installing, and backing up to the user's private Library. Tell the user so in one line.

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
- **"open my aistack dashboard"** opens the Library in the browser, on this computer, for as long as the session runs. `aistack-mcp dashboard` in a terminal does the same without an agent.
- For another computer, paste the same setup there and choose the same place: the same repository or the same database. For choice 1 there is nothing to share.
