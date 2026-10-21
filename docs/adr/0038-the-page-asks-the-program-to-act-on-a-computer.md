# The page asks the program to act on a computer

Status: accepted, 2026-10-21. Builds on ADR-0035 (the program does the mechanical work), ADR-0027 (a session belongs to the computer that opened it) and ADR-0020 (local mode). ADR-0013 (no server-initiated messages) is unchanged.

Some things a person starts on the page can only happen on a computer: starting a coding agent with chosen skills, looking inside a folder to add it as a project, writing an edit into a working copy, sharing that edit as a pull request. A server is somebody's machine and can be reached by anyone with a session; it must never be able to start a program on another computer. The research behind this is summarised in the pull request that adds this record.

## Decisions

**The program on the computer does the work, after the person confirms on that computer.** Every such action is an `aistack` command: `aistack start`, `aistack project add`, `aistack sync` (which writes pending edits and carries out a requested share). Before it starts an agent or sends a folder's file list, the command says what it is about to do and waits for Enter. A link or a page can therefore never run anything on its own.

**The page reaches the program three ways.**

| | Local mode | Server mode |
|---|---|---|
| One click | the localhost dashboard runs the command itself, in a new terminal | an `aistack://` link opens a terminal running the command |
| Copy | the command, to paste | the command, to paste |

Local mode's routes for this are registered only on the localhost dashboard (`LOCAL_ROUTES`) and carry the session cookie and the request header like every other action. The server has no route that starts a process.

**The program registers the `aistack://` link when it sets up a computer**: an app bundle on macOS, a per-user registry key on Windows, a `.desktop` handler on Linux, each pointing at the installed program's full path, and removed by `aistack` when it uninstalls. The handler opens a terminal and runs `aistack open <link>`, which accepts only known actions and treats every parameter as hostile: a project must be one this computer manages, an agent one of the known names, a skill name must match the skill-name rule, and nothing becomes a shell word unquoted. On Windows the registered command passes the link after `--`.

**Start an agent loads only the skills the person ticks, for that one session.** The dialog lists the project's and every project's skills, the repository's own skills included, ticked as last time for that project (remembered in the browser). v1 starts Claude Code and Codex, the two agents it can test:
- Claude Code: `claude --settings '<json>'`, where the settings turn off every other skill by name (`skillOverrides`), turn off the bundled skills, and turn off synced ones.
- Codex: `codex --no-daemon -c skills.bundled.enabled=false -c 'skills.config=[…]'`, after `codex debug prompt-input` with the same flags has confirmed that only the ticked skills remain. A Codex override that does not parse is ignored silently, so the check is not optional.

The program builds the list of skills to turn off from what is on disk at that moment, writes nothing to the person's settings, and keeps their login, rules and MCP servers. Each agent's recipe is one entry in a table in `bootstrap/start_agent.py`; adding an agent is adding an entry with its own test.

**Turning a skill off for one session is different from removing it.** Removing a skill from a computer, or a project, still takes it out of the agent's folder for every session and every app (ADR-0006); starting an agent with chosen skills changes nothing on disk, so other sessions and the desktop apps keep everything.

**Which computer the page is on.** Local mode knows. In server mode it is the computer whose agent opened the dashboard link (ADR-0027), shown as "This one"; a click on another computer's action shows the command to run there instead of a link.

## Not doing

- A daemon, or the program polling the server for actions: a stolen session could then start agents on every computer a person owns.
- A localhost helper the server's page calls.
- A prompt or permission flags passed to the started agent.
- Skills that are not on the computer yet. Add them first; the dialog says so.
- Saved named sets of skills.

## Consequences

- `aistack start`, `aistack project add` and `aistack open` are new commands, documented in the README.
- Setup and `aistack join` register the link, and `aistack check` reports whether it is registered.
- Claude Code needs 2.1.169 or later and Codex 0.163 or later for the recipes; the program says which version it found when one is too old.
- Plugin skills in Claude Code stay on unless the plugin is turned off, and resuming a session later from a plain terminal brings every skill back. The dialog says both in one line.
