# Where coding agents read their configuration

Research for #62 and ADR-0018 (proposed): where each coding agent reads skills, MCP server definitions, instruction files, and hooks, at user level and at project level, and in what format.

Every source was read on 2026-10-14. Primary sources only: each project's own documentation, its source repository at a named tag or commit, or its release notes. Where a document does not say something, this report says so; where source code decides it, the line is linked. "Not documented" means the cited page was read and is silent, not that the feature is absent.

Versions the sources describe:

| Agent | Version read | Source |
|---|---|---|
| Claude Code | docs current on 2026-10-14; latest npm release `2.1.299` | code.claude.com/docs (closed source) |
| OpenAI Codex CLI | docs current on 2026-10-14 (undated); source at tag `rust-v0.162.1` (2026-10-09) | learn.chatgpt.com/docs, github.com/openai/codex |
| Google Gemini CLI | docs and source at tag `v0.64.0` (2026-10-13) | github.com/google-gemini/gemini-cli |
| Moonshot Kimi Code CLI | docs and source at `main` commit `f28c51c`; latest release `2.1.1` (2026-09-24) | github.com/MoonshotAI/kimi-code |
| Z.ai GLM / ZCode | docs undated | docs.z.ai, zcode.z.ai |
| opencode | docs undated; latest release `v1.19.0` (2026-10-11) | opencode.ai/docs |
| Cursor (editor and CLI) | docs undated | cursor.com/docs |
| GitHub Copilot CLI | docs undated; latest release `v1.0.97` (2026-10-13) | docs.github.com |
| Amp | docs undated | ampcode.com/docs |

## Comparison matrix

User-level paths first, then project-level. `~` is the user's home directory.

| Agent | Skills folders | MCP config | Instruction files | Hooks, and a session-start event |
|---|---|---|---|---|
| Claude Code | `~/.claude/skills/`; project `.claude/skills/` (cwd up to repo root, nested on demand). Does not document `~/.agents/skills`. Live reload. | `~/.claude.json` (user and local scope), `.mcp.json` (project). JSON `mcpServers`. `${VAR}` and `${VAR:-default}`. | `~/.claude/CLAUDE.md`, `~/.claude/rules/`; `CLAUDE.md`, `.claude/CLAUDE.md`, `CLAUDE.local.md`, `.claude/rules/` (cwd and parents). `AGENTS.md` only when no `CLAUDE.md`. `@path` imports. | `hooks` in `~/.claude/settings.json`, `.claude/settings.json`, `.claude/settings.local.json`. `SessionStart` (stdout reaches the model; `reloadSkills`). |
| Codex CLI | `~/.agents/skills/` (plus deprecated `~/.codex/skills/`), `/etc/codex/skills`; project `.agents/skills/` (cwd up to repo root) and `.codex/skills/`. Live reload. | `~/.codex/config.toml`, project `.codex/config.toml` (trusted only). TOML `[mcp_servers.<name>]`. Env by name: `env_vars`, `bearer_token_env_var`, `env_http_headers`. | `~/.codex/AGENTS.override.md` or `AGENTS.md`; `AGENTS.override.md` / `AGENTS.md` per directory from repo root to cwd. 32 KiB cap. No imports documented. | `~/.codex/hooks.json` or `[hooks]` in `config.toml`, same in project `.codex/`. `SessionStart` (stdout reaches the model). Each hook must be trusted once. |
| Gemini CLI | `~/.gemini/skills/` and `~/.agents/skills/`; workspace `.gemini/skills/` and `.agents/skills/` (trusted folders only). `.agents` wins within a tier. No watcher: `/skills reload`. | `~/.gemini/settings.json`, project `.gemini/settings.json`. JSON `mcpServers`; `httpUrl` for streamable HTTP, `url` means SSE. `$VAR`, `${VAR}`, `${VAR:-default}`. | `~/.gemini/GEMINI.md`; `GEMINI.md` in workspace dirs and parents, plus just-in-time. `AGENTS.md` only if set in `context.fileName`. `@file` imports. | `hooks` in the same `settings.json` files. `SessionStart` (JSON `additionalContext`). |
| Kimi Code CLI | `~/.kimi-code/skills/` and `~/.agents/skills/`; project `.kimi-code/skills/` and `.agents/skills/` at the git root. Watcher reloads. | `~/.kimi-code/mcp.json`, project `.kimi-code/mcp.json`. JSON `mcpServers`. No interpolation; `bearerTokenEnvVar`. | `~/.kimi-code/AGENTS.md` and `~/.agents/AGENTS.md`; `.kimi-code/AGENTS.md` and `AGENTS.md` per directory from git root to cwd. | `[[hooks]]` in `~/.kimi-code/config.toml` only. `SessionStart` is observation-only. |
| GLM (Z.ai) | No CLI of its own. Used through Claude Code, Codex, opencode, and others with a Z.ai endpoint, or in Z.ai's ZCode desktop app (`~/.zcode/skills/`). | ZCode: `~/.zcode/cli/config.json` `mcp.servers`, or `~/.agents/mcp.json` `mcpServers`. | ZCode: `~/.zcode/AGENTS.md` plus the workspace `AGENTS.md`. | ZCode: `hooks` in `~/.zcode/cli/config.json`. Has `SessionStart`. Project hooks are not run. |
| opencode | `~/.config/opencode/skills/`, `~/.claude/skills/`, `~/.agents/skills/`; project `.opencode/skills/`, `.claude/skills/`, `.agents/skills/` (cwd up to git worktree). | `~/.config/opencode/opencode.json`, project `opencode.json`. Key `mcp`; `type: local` or `remote`. `{env:VAR}`. | `~/.config/opencode/AGENTS.md`, else `~/.claude/CLAUDE.md`; project `AGENTS.md`, else `CLAUDE.md`. `instructions` key. | No hook file. JS/TS plugins in `~/.config/opencode/plugins/` and `.opencode/plugins/`; event `session.created`. |
| Cursor | `~/.cursor/skills/`, `~/.agents/skills/`, `~/.claude/skills/`, `~/.codex/skills/`, and the same names in the project. | `~/.cursor/mcp.json`, `.cursor/mcp.json`; the CLI uses the same configuration. `${env:NAME}`. | `.cursor/rules/*.mdc`, `AGENTS.md` (root and nested); the CLI also reads `CLAUDE.md` at the root. User rules live in the app's settings. | `~/.cursor/hooks.json`, `.cursor/hooks.json`. `sessionStart` (fire-and-forget). The CLI is confirmed only for `workspaceOpen`. |
| Copilot CLI | `~/.copilot/skills/`, `~/.agents/skills/`; project `.github/skills/`, `.claude/skills/`, `.agents/skills/`. `/skills reload`. | `~/.copilot/mcp-config.json`; project `.mcp.json` and `.github/mcp.json`. JSON `mcpServers`. Interpolation not documented. | `~/.copilot/copilot-instructions.md`; `.github/copilot-instructions.md`, `.github/instructions/**`, `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`. | `~/.copilot/hooks/*.json`, `.github/hooks/*.json`. `sessionStart` (`additionalContext`). |
| Amp | `~/.config/agents/skills/`, `~/.agents/skills/`, `~/.config/amp/skills/`, project `.agents/skills/` and `.claude/skills/`, `~/.claude/skills/`. First match by name wins. | `~/.config/amp/settings.json`, project `.amp/settings.json`. Key `amp.mcpServers`. `${VAR}`. | `~/.config/amp/AGENTS.md`, `~/.config/AGENTS.md`; `AGENTS.md` (fallback `AGENT.md`, `CLAUDE.md`) in cwd and parents. `@path` and globs. | No hook file. TS/JS plugins in `~/.config/amp/plugins/` and `.amp/plugins/`; event `session.start`. |

---

## Claude Code

Sources: [skills](https://code.claude.com/docs/en/skills), [MCP](https://code.claude.com/docs/en/mcp), [memory](https://code.claude.com/docs/en/memory), [hooks](https://code.claude.com/docs/en/hooks), [settings](https://code.claude.com/docs/en/settings), [subagents](https://code.claude.com/docs/en/sub-agents), [.claude directory](https://code.claude.com/docs/en/claude-directory), [changelog](https://code.claude.com/docs/en/changelog). Version on npm: `2.1.299`.

### Skills

- Format: `SKILL.md` with YAML frontmatter, with `description` recommended. "All fields are optional." `name` "defaults to the directory name". The combined `description` and `when_to_use` text "is truncated at 1,536 characters in the skill listing". The skills page states no length or character set for `name`. ([skills](https://code.claude.com/docs/en/skills))
- Locations: enterprise (`.claude/skills/` in the managed settings directory), personal `~/.claude/skills/<name>/SKILL.md`, project `.claude/skills/<name>/SKILL.md` loaded "from the starting directory and every parent up to the repository root", nested `<subdir>/.claude/skills/` loaded the first time Claude touches a file there, `--add-dir` directories, and plugins (namespaced `/plugin:skill`). ([skills](https://code.claude.com/docs/en/skills))
- Precedence: "Enterprise over personal, and personal over project." A skill beats a `.claude/commands/` file with the same name. ([skills](https://code.claude.com/docs/en/skills))
- Reload: "When you add, edit, or remove a skill under `~/.claude/skills/`, the project `.claude/skills/`, or a `.claude/skills/` inside an `--add-dir` directory, Claude Code picks up the change within the current session, without a restart." A top-level skills directory created after the session started needs `/reload-skills`. ([skills](https://code.claude.com/docs/en/skills))
- `~/.agents/skills`: the skills page, the `.claude` directory page, and the changelog do not mention `.agents/skills`. The changelog mentions `AGENTS.md` only (see below). Claude Code is closed source, so there is no line to show. Treat it as not read.
- Claude.ai sync writes into `~/.claude/skills/synced/` and leaves other folders alone; a folder Claude Code moved aside goes to `~/.claude/skills/.trash/`. ([skills, troubleshooting](https://code.claude.com/docs/en/skills))

### MCP servers

- Scopes: local (the default, in `~/.claude.json` under that project's path), project (`.mcp.json` at the project root, committed), user (`~/.claude.json`, all projects). The docs do not name the JSON key for user scope inside `~/.claude.json`; the CLI writes it (`claude mcp add`, `claude mcp add-json`). ([MCP](https://code.claude.com/docs/en/mcp))
- Precedence: local, then project, then user, then plugin, then claude.ai connectors. "The entire server entry from that source is used; fields are not merged across scopes." ([MCP](https://code.claude.com/docs/en/mcp))
- stdio entry (`type` may be omitted: "Claude Code reads an entry with no `type` as a stdio server"):

  ```json
  { "mcpServers": { "db": { "type": "stdio", "command": "/path/to/server", "args": ["--flag"], "env": { "DB_URL": "${DB_URL}" } } } }
  ```

- HTTP entry. `type` is required; `streamable-http` is an alias of `http`.

  ```json
  { "mcpServers": { "api": { "type": "http", "url": "https://example.com/mcp", "headers": { "Authorization": "Bearer ${API_KEY}" } } } }
  ```

- Secrets: `${VAR}` and `${VAR:-default}` expand in `command`, `args`, `env`, `url`, `headers`. An unset variable with no default is left as literal text, and `claude mcp list` warns. ([MCP](https://code.claude.com/docs/en/mcp))
- Project servers from `.mcp.json` need approval in interactive sessions. ([MCP](https://code.claude.com/docs/en/mcp))

### Instruction files

- Managed: `/Library/Application Support/ClaudeCode/CLAUDE.md` (macOS), `/etc/claude-code/CLAUDE.md` (Linux), `C:\Program Files\ClaudeCode\CLAUDE.md`. User: `~/.claude/CLAUDE.md` and `~/.claude/rules/`. Project: `./CLAUDE.md` or `./.claude/CLAUDE.md`, `./CLAUDE.local.md`, and `.claude/rules/**/*.md`, optionally scoped by `paths`. ([memory](https://code.claude.com/docs/en/memory))
- Combination: files from the working directory and every directory above it are loaded at launch and "concatenated into context rather than overriding each other", ordered from the filesystem root down. Subdirectory files load on demand. ([memory](https://code.claude.com/docs/en/memory))
- `AGENTS.md`: by default it is read "only when you have no `CLAUDE.md` in your working directory or above it". `~/.claude/CLAUDE.md` and rules keep loading alongside it. Needs v2.1.277 or later. The **Project instructions** setting `claude-md-and-agents-md` reads both. ([memory, AGENTS.md](https://code.claude.com/docs/en/memory))
- Imports: `@path/to/file`, relative to the importing file, absolute and home paths allowed, "maximum depth of four hops". Imports outside the project need a one-time approval; imports in user-scope files do not. ([memory](https://code.claude.com/docs/en/memory))

### Hooks

- Files: `~/.claude/settings.json`, `.claude/settings.json`, `.claude/settings.local.json`, managed settings, plugin `hooks/hooks.json`, and skill or subagent frontmatter. Format: event, then matcher group, then handler. ([hooks](https://code.claude.com/docs/en/hooks))
- Events: 33, including `SessionStart`, `Setup`, `SessionEnd`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `Stop`, `PreCompact`, `InstructionsLoaded`, `ConfigChange`, `FileChanged`. ([hooks](https://code.claude.com/docs/en/hooks))
- `SessionStart` matchers: `startup`, `resume`, `clear`, `compact`, `fork`. "On exit 0, plain-text stdout is added to Claude's context." At startup, hooks run in the background, but "Claude's first response still waits for them". Default timeout is 600 s. ([hooks](https://code.claude.com/docs/en/hooks))
- `SessionStart` output `reloadSkills: true` "re-scans the skill and command directories after the SessionStart hooks complete". It exists because "files a hook writes into `~/.claude/skills/` ... can be missing when the first prompt runs" otherwise. ([hooks, reload skills](https://code.claude.com/docs/en/hooks))
- `SessionStart` accepts only `command` and `mcp_tool` hooks. An `mcp_tool` hook on `SessionStart` at launch is skipped, because MCP servers are not yet available: "For anything the session needs at launch, use a `type: "command"` hook". So a hook cannot call AIStack's `sync` tool directly at startup. ([hooks, MCP tool hook fields](https://code.claude.com/docs/en/hooks))

```json
{ "hooks": { "SessionStart": [ { "matcher": "startup", "hooks": [ { "type": "command", "command": "~/.claude/hooks/start.sh", "timeout": 30 } ] } ] } }
```

### Other syncable configuration

- Settings: managed, then `--settings`, then `.claude/settings.local.json`, then `.claude/settings.json`, then `~/.claude/settings.json` (highest first). `~/.claude.json` is "a fifth file ... that it writes for itself", holding sign-in, MCP servers, and per-project state. ([settings](https://code.claude.com/docs/en/settings))
- Subagents: Markdown with YAML frontmatter (`name`, `description` required), in `~/.claude/agents/` and `.claude/agents/`, scanned recursively. Project wins over user. ([subagents](https://code.claude.com/docs/en/sub-agents))
- Commands: `.claude/commands/*.md` still work, and are "merged into skills". Output styles live in `output-styles/`. ([skills](https://code.claude.com/docs/en/skills), [.claude directory](https://code.claude.com/docs/en/claude-directory))

---

## OpenAI Codex CLI

Sources: [skills](https://learn.chatgpt.com/docs/build-skills) (redirected from developers.openai.com/codex/skills), [MCP](https://learn.chatgpt.com/docs/extend/mcp?surface=cli), [AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md), [hooks](https://learn.chatgpt.com/docs/hooks), [config basics](https://learn.chatgpt.com/docs/config-file/config-basic.md), [config reference](https://learn.chatgpt.com/docs/config-file/config-reference.md), [subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents.md), [Codex manual](https://learn.chatgpt.com/docs/codex-manual.md); source [`openai/codex` at `rust-v0.162.1`](https://github.com/openai/codex/tree/rust-v0.162.1).

### Skills

- Documented locations: REPO `$CWD/.agents/skills`, `$CWD/../.agents/skills`, `$REPO_ROOT/.agents/skills` ("Codex scans `.agents/skills` in every directory from your current working directory up to the repository root"); USER `$HOME/.agents/skills`; ADMIN `/etc/codex/skills`; SYSTEM (bundled). ([skills](https://learn.chatgpt.com/docs/build-skills))
- The source also reads two folders the docs do not list: the user config folder's `skills/` (`$CODEX_HOME/skills`, by default `~/.codex/skills`, commented "Deprecated user skills location ... kept for backward compatibility"), and `skills/` inside each project `.codex/` config layer. ([host_roots.rs L84-L120](https://github.com/openai/codex/blob/rust-v0.162.1/codex-rs/ext/skills/src/host_roots.rs#L84-L120))
- Duplicates: "If two skills share the same `name`, Codex doesn't merge them; both can appear in skill selectors." There is no precedence by location. ([skills](https://learn.chatgpt.com/docs/build-skills))
- Frontmatter: `name` and `description` are required. Limits in source: `MAX_NAME_LEN = 64`, `MAX_DESCRIPTION_LEN = 1024`, `MAX_SCAN_DEPTH = 6`, `MAX_SKILLS_DIRS_PER_ROOT = 2000`. ([loader/mod.rs L19-L32](https://github.com/openai/codex/blob/rust-v0.162.1/codex-rs/ext/skills/src/loader/mod.rs#L19-L32))
- Reload: "Codex detects skill changes automatically. If an update doesn't appear, restart Codex." Symlinked skill folders are followed. To disable one skill: `[[skills.config]]` with `path` and `enabled = false` in `~/.codex/config.toml`, then restart. Optional per-skill `agents/openai.yaml` holds UI metadata and invocation policy. ([skills](https://learn.chatgpt.com/docs/build-skills))

### MCP servers

- Files: `~/.codex/config.toml`, and project `.codex/config.toml` for "trusted projects" only. Precedence, highest first: CLI flags, project files from root to cwd (closest wins), profile, user, system `/etc/codex/config.toml`. ([MCP](https://learn.chatgpt.com/docs/extend/mcp?surface=cli), [config basics](https://learn.chatgpt.com/docs/config-file/config-basic.md))
- stdio entry: `command` (required), `args`, `env` (static map), `env_vars` (names to forward from the environment), `cwd`.

  ```toml
  [mcp_servers.context7]
  command = "npx"
  args = ["-y", "@upstash/context7-mcp"]
  env_vars = ["LOCAL_TOKEN"]
  ```

- Streamable HTTP entry: `url` (required), `bearer_token_env_var`, `http_headers` (static), `env_http_headers` (header name to environment variable name), `auth` (`oauth` or `chatgpt`).

  ```toml
  [mcp_servers.figma]
  url = "https://mcp.figma.com/mcp"
  bearer_token_env_var = "FIGMA_OAUTH_TOKEN"
  http_headers = { "X-Figma-Region" = "us-east-1" }
  ```

- Common options: `enabled`, `required`, `startup_timeout_sec` (default 10), `tool_timeout_sec` (default 60), `enabled_tools`, `disabled_tools`. OAuth: `codex mcp login <name>`. ([MCP](https://learn.chatgpt.com/docs/extend/mcp?surface=cli))
- Secrets: by environment variable name, through the three fields above. The pages read document no `${VAR}` interpolation inside `config.toml`.

### Instruction files

- Global: in `~/.codex` (or `CODEX_HOME`), `AGENTS.override.md` if present, otherwise `AGENTS.md`. "Codex uses only the first non-empty file at this level." ([AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md))
- Project: from the project root (usually the git root) down to the cwd, at most one file per directory, checked in the order `AGENTS.override.md`, `AGENTS.md`, then `project_doc_fallback_filenames`. "Codex concatenates files from the root down, joining them with blank lines." The total is capped by `project_doc_max_bytes` (default 32 KiB). No import syntax is documented. ([AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md))

### Hooks

- Files: `~/.codex/hooks.json`, `[hooks]` in `~/.codex/config.toml`, and the same in `<repo>/.codex/` (trusted projects only), plus plugin `hooks/hooks.json`. The structure is the same as Claude Code's: event, then matcher group, then handlers. On by default; `[features] hooks = false` turns them off. ([hooks](https://learn.chatgpt.com/docs/hooks))
- Events: `SessionStart`, `SessionEnd`, `PreToolUse`, `PermissionRequest`, `PostToolUse`, `PreCompact`, `PostCompact`, `UserPromptSubmit`, `SubagentStart`, `SubagentStop`, `Stop`, `Interrupt`. ([hooks](https://learn.chatgpt.com/docs/hooks))
- `SessionStart` matchers: `startup`, `resume`, `clear`, `compact`, `fork`. "Plain text on `stdout` is added as extra developer context." ([hooks](https://learn.chatgpt.com/docs/hooks))
- Trust: "Before a non-managed hook can run, Codex requires you to review and trust the exact hook definition." Trust is recorded against the hook's hash, so a changed hook is skipped until it is trusted again (`/hooks`). ([hooks](https://learn.chatgpt.com/docs/hooks))

```json
{ "hooks": { "SessionStart": [ { "matcher": "startup|resume", "hooks": [ { "type": "command", "command": "python3 ~/.codex/hooks/session_start.py" } ] } ] } }
```

### Other syncable configuration

- Custom agents: TOML files in `~/.codex/agents/` and `.codex/agents/`, with `name`, `description`, `developer_instructions` required. ([subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents.md))
- Custom prompts in `~/.codex/prompts/*.md` are deprecated: "Custom prompts are deprecated. Use skills". ([Codex manual, Custom Prompts](https://learn.chatgpt.com/docs/codex-manual.md))
- Command rules (execpolicy): `~/.codex/rules/`. Profiles: `~/.codex/<profile>.config.toml`. ([Codex manual](https://learn.chatgpt.com/docs/codex-manual.md), [config basics](https://learn.chatgpt.com/docs/config-file/config-basic.md))

---

## Google Gemini CLI

Sources at tag `v0.64.0`: [docs/cli/skills.md](https://github.com/google-gemini/gemini-cli/blob/v0.64.0/docs/cli/skills.md), [docs/tools/mcp-server.md](https://github.com/google-gemini/gemini-cli/blob/v0.64.0/docs/tools/mcp-server.md), [docs/cli/gemini-md.md](https://github.com/google-gemini/gemini-cli/blob/v0.64.0/docs/cli/gemini-md.md), [docs/reference/memport.md](https://github.com/google-gemini/gemini-cli/blob/v0.64.0/docs/reference/memport.md), [docs/hooks/index.md](https://github.com/google-gemini/gemini-cli/blob/v0.64.0/docs/hooks/index.md), [docs/hooks/reference.md](https://github.com/google-gemini/gemini-cli/blob/v0.64.0/docs/hooks/reference.md), [docs/reference/configuration.md](https://github.com/google-gemini/gemini-cli/blob/v0.64.0/docs/reference/configuration.md), [docs/cli/custom-commands.md](https://github.com/google-gemini/gemini-cli/blob/v0.64.0/docs/cli/custom-commands.md), [docs/core/subagents.md](https://github.com/google-gemini/gemini-cli/blob/v0.64.0/docs/core/subagents.md).

### Skills

- "Based on the Agent Skills open standard." Tiers, lowest to highest precedence: built-in, extension, user (`~/.gemini/skills/` or `~/.agents/skills/`), workspace (`.gemini/skills/` or `.agents/skills/`). "Within the same tier (user or workspace), the `.agents/skills/` alias takes precedence over the `.gemini/skills/` directory." ([skills.md](https://github.com/google-gemini/gemini-cli/blob/v0.64.0/docs/cli/skills.md))
- Workspace skills are skipped in an untrusted folder. ([skillManager.ts L81-L99](https://github.com/google-gemini/gemini-cli/blob/v0.64.0/packages/core/src/skills/skillManager.ts#L81-L99))
- Discovery is one level deep (glob `['SKILL.md', '*/SKILL.md']`). `name` is not validated against the spec, only sanitized: `:\/<>*?"|` are replaced with `-`. ([skillLoader.ts L127](https://github.com/google-gemini/gemini-cli/blob/v0.64.0/packages/core/src/skills/skillLoader.ts#L127), [L180](https://github.com/google-gemini/gemini-cli/blob/v0.64.0/packages/core/src/skills/skillLoader.ts#L180))
- Reload: skills are discovered "at the start of a session". `/skills reload` re-scans. Its only callers are the `/skills`, `/memory`, and `/extensions` commands and extension loading; there is no file watcher. ([skills.md](https://github.com/google-gemini/gemini-cli/blob/v0.64.0/docs/cli/skills.md), [config.ts `reloadSkills`](https://github.com/google-gemini/gemini-cli/blob/v0.64.0/packages/core/src/config/config.ts#L3712))
- Activation asks the user for consent in the UI before the body is loaded. ([skills.md](https://github.com/google-gemini/gemini-cli/blob/v0.64.0/docs/cli/skills.md))

### MCP servers

- Files: `mcpServers` in `~/.gemini/settings.json` (user) or `.gemini/settings.json` (project). `gemini mcp add -s user|project` writes one of them (default `project`). System files: `/etc/gemini-cli/settings.json`, `/Library/Application Support/GeminiCli/settings.json`, `C:\ProgramData\gemini-cli\settings.json`. ([mcp-server.md L1145-L1164](https://github.com/google-gemini/gemini-cli/blob/v0.64.0/docs/tools/mcp-server.md), [configuration.md L36-L55](https://github.com/google-gemini/gemini-cli/blob/v0.64.0/docs/reference/configuration.md))
- Transport is chosen by the key: `command` for stdio, `url` for **SSE**, `httpUrl` for streamable HTTP. Optional: `args`, `env`, `cwd`, `headers`, `timeout` (ms), `trust`, `includeTools`, `excludeTools`. ([mcp-server.md L156-L181](https://github.com/google-gemini/gemini-cli/blob/v0.64.0/docs/tools/mcp-server.md))

  ```json
  { "mcpServers": {
      "local": { "command": "python", "args": ["server.py"], "env": { "API_KEY": "$MY_API_TOKEN" } },
      "remote": { "httpUrl": "https://example.com/mcp", "headers": { "Authorization": "Bearer $MY_TOKEN" } } } }
  ```

- Secrets: "String values within your `settings.json` ... can reference environment variables using `$VAR_NAME`, `${VAR_NAME}`, or `${VAR_NAME:-DEFAULT_VALUE}`". That covers `headers` as well as `env`. Sensitive host variables are removed from a stdio server's environment unless they are named in `env`. ([configuration.md L63-L68](https://github.com/google-gemini/gemini-cli/blob/v0.64.0/docs/reference/configuration.md), [mcp-server.md L216-L251](https://github.com/google-gemini/gemini-cli/blob/v0.64.0/docs/tools/mcp-server.md))

### Instruction files

- Default name `GEMINI.md`: global `~/.gemini/GEMINI.md`, then files "in your configured workspace directories and their parent directories", then just-in-time files found when a tool touches a directory. All are concatenated. ([gemini-md.md](https://github.com/google-gemini/gemini-cli/blob/v0.64.0/docs/cli/gemini-md.md))
- `AGENTS.md` is read only if listed in `context.fileName`, for example `["AGENTS.md", "CONTEXT.md", "GEMINI.md"]`. The default is `undefined`, meaning `GEMINI.md`. ([gemini-md.md](https://github.com/google-gemini/gemini-cli/blob/v0.64.0/docs/cli/gemini-md.md), [configuration.md L1690](https://github.com/google-gemini/gemini-cli/blob/v0.64.0/docs/reference/configuration.md))
- Imports: `@file.md`, relative or absolute, with a maximum import depth that defaults to 5. `/memory reload` re-scans. ([memport.md L99-L102](https://github.com/google-gemini/gemini-cli/blob/v0.64.0/docs/reference/memport.md))

### Hooks

- Files: `hooks` in `.gemini/settings.json` (highest), `~/.gemini/settings.json`, `/etc/gemini-cli/settings.json`, and extensions. Only `type: "command"` is supported. Timeout is in milliseconds (default 60000). Project hooks are fingerprinted, so a changed hook is treated as new and untrusted. ([hooks/index.md](https://github.com/google-gemini/gemini-cli/blob/v0.64.0/docs/hooks/index.md))
- Events: `SessionStart`, `SessionEnd`, `BeforeAgent`, `AfterAgent`, `BeforeModel`, `AfterModel`, `BeforeToolSelection`, `BeforeTool`, `AfterTool`, `PreCompress`, `Notification`. ([hooks/index.md](https://github.com/google-gemini/gemini-cli/blob/v0.64.0/docs/hooks/index.md))
- `SessionStart`: `source` is `startup`, `resume`, or `clear`. `hookSpecificOutput.additionalContext` is "Injected as the first turn in history". It is advisory: "Startup is never blocked." stdout must be exactly one JSON object; plain text breaks parsing. ([hooks/reference.md L245-L258](https://github.com/google-gemini/gemini-cli/blob/v0.64.0/docs/hooks/reference.md), [hooks/index.md](https://github.com/google-gemini/gemini-cli/blob/v0.64.0/docs/hooks/index.md))

### Other syncable configuration

- Custom commands: TOML (`description`, `prompt`) in `~/.gemini/commands/` and `<project>/.gemini/commands/`; subfolders give namespaced commands (`git/commit.toml` becomes `/git:commit`). ([custom-commands.md](https://github.com/google-gemini/gemini-cli/blob/v0.64.0/docs/cli/custom-commands.md))
- Subagents: Markdown with YAML frontmatter in `.gemini/agents/*.md` and `~/.gemini/agents/*.md`. ([subagents.md L320-L331](https://github.com/google-gemini/gemini-cli/blob/v0.64.0/docs/core/subagents.md))

---

## Moonshot Kimi Code CLI

The Python `MoonshotAI/kimi-cli` is archived ("Legacy Python Kimi CLI, no longer maintained"; last release `1.52.0`). Its replacement is the TypeScript [`MoonshotAI/kimi-code`](https://github.com/MoonshotAI/kimi-code), which runs as `kimi`. `kimi migrate` copies `~/.kimi/` config and MCP servers into `~/.kimi-code/`. ([migration.md](https://github.com/MoonshotAI/kimi-code/blob/f28c51c01f025bba9f0d0f58f6309e7517a8cd02/docs/en/guides/migration.md)) Everything below is for Kimi Code at commit `f28c51c`. `KIMI_CODE_HOME` (default `~/.kimi-code`) moves every Kimi-specific path; the `~/.agents/...` paths always stay under the real home directory.

### Skills

- User level: `$KIMI_CODE_HOME/skills/` and `~/.agents/skills/`. Project level (project root = "the nearest directory containing `.git`"): `.kimi-code/skills/` and `.agents/skills/`. There are also `extra_skill_dirs` in `config.toml` and built-in skills. Priority: "Project > User > Extra > Built-in". ([skills.md](https://github.com/MoonshotAI/kimi-code/blob/f28c51c01f025bba9f0d0f58f6309e7517a8cd02/docs/en/customization/skills.md), [skillRoots.ts L8-L39](https://github.com/MoonshotAI/kimi-code/blob/f28c51c01f025bba9f0d0f58f6309e7517a8cd02/packages/agent-core-v2/src/features/skill/catalog/skillRoots.ts#L8-L39))
- Within a tier, the Kimi folder is added before `.agents/skills`. The rule for two skills with one name in the same tier is not documented.
- Format: directory form `<name>/SKILL.md`, with `name` and `description` "**must** be explicitly provided", plus a flat form `<name>.md` that Kimi alone supports. Kimi-specific frontmatter: `type`, `whenToUse`, `disableModelInvocation`, `arguments`. `name` is case-insensitive. No length limits are documented. ([skills.md](https://github.com/MoonshotAI/kimi-code/blob/f28c51c01f025bba9f0d0f58f6309e7517a8cd02/docs/en/customization/skills.md))
- Reload: the `watch` setting (on by default) "controls filesystem watchers that reload local.toml, AGENTS.md, skills, MCP config, and `config.toml` itself". ([config-files.md, `watch`](https://github.com/MoonshotAI/kimi-code/blob/f28c51c01f025bba9f0d0f58f6309e7517a8cd02/docs/en/configuration/config-files.md))

### MCP servers

- Files: `~/.kimi-code/mcp.json` (user) and `.kimi-code/mcp.json` in the working directory (project). For the same name, "the project-level entry takes precedence". Project servers need workspace trust. ([mcp.md](https://github.com/MoonshotAI/kimi-code/blob/f28c51c01f025bba9f0d0f58f6309e7517a8cd02/docs/en/customization/mcp.md))
- "Entries with a `command` field are stdio servers; entries with a `url` field and no `transport` are HTTP servers." SSE needs `"transport": "sse"`. Optional: `env`, `cwd`, `headers`, `bearerTokenEnvVar`, `enabled`, `startupTimeoutMs`, `toolTimeoutMs`, `enabledTools`, `disabledTools`, `deferred`. ([mcp.md](https://github.com/MoonshotAI/kimi-code/blob/f28c51c01f025bba9f0d0f58f6309e7517a8cd02/docs/en/customization/mcp.md))

  ```json
  { "mcpServers": {
      "filesystem": { "command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"] },
      "linear": { "url": "https://mcp.linear.app/mcp", "bearerTokenEnvVar": "LINEAR_TOKEN" } } }
  ```

- Secrets: `bearerTokenEnvVar` is the only documented reference by name. The loader does no `${VAR}` substitution; it only resolves a stdio `cwd`. ([configLoader.ts](https://github.com/MoonshotAI/kimi-code/blob/f28c51c01f025bba9f0d0f58f6309e7517a8cd02/packages/agent-core-v2/src/app/mcpConfig/configLoader.ts#L160-L164))
- A server added mid-session by editing `mcp.json` "only joins sessions created later". ([mcp.md](https://github.com/MoonshotAI/kimi-code/blob/f28c51c01f025bba9f0d0f58f6309e7517a8cd02/docs/en/customization/mcp.md))

### Instruction files

- Loaded in this order and concatenated: `$KIMI_CODE_HOME/AGENTS.md`; the first of `~/.agents/AGENTS.md` and `~/.agents/agents.md`; then, for each directory from the git root to the cwd, `.kimi-code/AGENTS.md` and the first of `AGENTS.md` and `agents.md`. Above 32 KiB in total it warns but does not truncate. `CLAUDE.md` is not read. No import syntax is documented. ([context.ts L137-L193](https://github.com/MoonshotAI/kimi-code/blob/f28c51c01f025bba9f0d0f58f6309e7517a8cd02/packages/agent-core-v2/src/agent/profile/context.ts#L137-L193), [agents.md, Instruction Files](https://github.com/MoonshotAI/kimi-code/blob/f28c51c01f025bba9f0d0f58f6309e7517a8cd02/docs/en/customization/agents.md))

### Hooks

- "All hook rules are written in the `[[hooks]]` array in `~/.kimi-code/config.toml`." There are only four fields: `event`, `matcher` (a regex), `command`, `timeout` (s, 1 to 600, default 30). Plugins can also bring hooks. ([hooks.md](https://github.com/MoonshotAI/kimi-code/blob/f28c51c01f025bba9f0d0f58f6309e7517a8cd02/docs/en/customization/hooks.md))
- Events include `SessionStart` (matcher `startup` or `resume`), `SessionEnd`, `SessionHeartbeat`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `Stop`, `PreCompact`, and `Notification`. Only `PreToolUse`, `Stop`, and `UserPromptSubmit` can affect the flow. "All other events are observation-only events: they fire and forget". So a `SessionStart` hook can run a program but cannot put text in front of the model. ([hooks.md](https://github.com/MoonshotAI/kimi-code/blob/f28c51c01f025bba9f0d0f58f6309e7517a8cd02/docs/en/customization/hooks.md))

```toml
[[hooks]]
event = "SessionStart"
matcher = "startup"
command = "~/.kimi-code/hooks/start.sh"
```

### Other syncable configuration

- Agents: Markdown files in `~/.kimi-code/agents/`, `~/.agents/agents/`, `.kimi-code/agents/`, `.agents/agents/`. Priority: explicit, then project, then extra, then user, then plugin, then built-in. `$KIMI_CODE_HOME/SYSTEM.md` overrides the main system prompt. ([agents.md](https://github.com/MoonshotAI/kimi-code/blob/f28c51c01f025bba9f0d0f58f6309e7517a8cd02/docs/en/customization/agents.md))
- Permission rules: `[[permission.rules]]` in `config.toml`. ([mcp.md](https://github.com/MoonshotAI/kimi-code/blob/f28c51c01f025bba9f0d0f58f6309e7517a8cd02/docs/en/customization/mcp.md))

---

## Z.ai GLM

GLM has no terminal coding agent of its own in Z.ai's documentation. The GLM Coding Plan is a model subscription used inside other agents: "The plan can be applied to agent tools such as ZCode, Claude Code, Codex, OpenCode, AutoClaw, and OpenClaw". It exposes an Anthropic-protocol endpoint `https://api.z.ai/api/anthropic` and an OpenAI-protocol endpoint `https://api.z.ai/api/coding/paas/v4`. ([overview](https://docs.z.ai/devpack/overview.md), [quick start](https://docs.z.ai/devpack/quick-start.md), [other tools](https://docs.z.ai/devpack/tool/others.md))

- **Through Claude Code** (the primary documented path): Z.ai's script "will automatically modify `~/.claude/settings.json`" to set `env` entries `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_BASE_URL=https://api.z.ai/api/anthropic`, and `ANTHROPIC_DEFAULT_{OPUS,SONNET,HAIKU}_MODEL`. Everything else is Claude Code's layout above. ([Claude Code guide](https://docs.z.ai/devpack/tool/claude.md))
- **Coding Tool Helper** (`npx @z_ai/coding-helper`) is a configurator, not an agent. It sets up "Claude Code, Codex, OpenCode, Crush, Factory Droid". ([coding tool helper](https://docs.z.ai/devpack/extension/coding-tool-helper.md))
- **ZCode** is Z.ai's own "Agentic Development Environment", installed as a "desktop app". Its docs describe only the desktop app. Third-party reports of an embedded CLI were not confirmed by a primary source. ([ZCode on docs.z.ai](https://docs.z.ai/devpack/tool/zcode.md), [ZCode docs](https://zcode.z.ai/en/docs/configuration))
  - Skills: `~/.zcode/skills/<name>/SKILL.md`. `name` and `description` are required; a `description` over 1024 characters drops the skill; a body over 100 KB is truncated. Skills from Claude Code or Codex are brought in by an Import dialog (symlink or copy), not scanned. The project folder is not documented. ([skill](https://zcode.z.ai/en/docs/skill))
  - MCP: `~/.zcode/cli/config.json` and `<project>/.zcode/config.json` under `mcp.servers`. It also reads `~/.agents/mcp.json` and `<project>/.agents/mcp.json` under `mcpServers`, but "If a `.zcode` file in the same scope defines any servers, the `.agents` file is skipped entirely." Disabled servers carry `"enable": false`. ([MCP](https://zcode.z.ai/en/docs/mcp-services))
  - Instructions: `~/.zcode/AGENTS.md` plus the workspace `AGENTS.md`, not merged across directory levels. `CLAUDE.md` is used only as a one-time onboarding migration source. ([agents](https://zcode.z.ai/en/docs/agents))
  - Hooks: `hooks` in `~/.zcode/cli/config.json` with `hooks.enabled: true`, or plugin `hooks/hooks.json`. "Project-level hooks are not executed in the current version." Events: `SessionStart` (sources `startup`, `clear`, `compact`), `UserPromptSubmit`, `PreToolUse`, `PermissionRequest`, `PostToolUse`, `PostToolUseFailure`, `Stop`. ([hooks](https://zcode.z.ai/en/docs/hooks))

For AIStack, a GLM user is almost always a Claude Code, Codex, or opencode harness with a different model endpoint, and needs no harness entry of its own. ZCode is a separate desktop harness.

---

## opencode (bonus)

Sources: [skills](https://opencode.ai/docs/skills/), [MCP](https://opencode.ai/docs/mcp-servers/), [rules](https://opencode.ai/docs/rules/), [config](https://opencode.ai/docs/config/), [plugins](https://opencode.ai/docs/plugins/). Latest release `v1.19.0`.

- Skills: `.opencode/skills/`, `.claude/skills/`, `.agents/skills/` (walking up from the cwd to the git worktree), and `~/.config/opencode/skills/`, `~/.claude/skills/`, `~/.agents/skills/`. `name` follows `^[a-z0-9]+(-[a-z0-9]+)*$`, 1 to 64 characters, and "must match the containing directory name". `description` is 1 to 1024 characters. Precedence between locations and reload behaviour are not documented; the page only advises unique names. `OPENCODE_DISABLE_CLAUDE_CODE_SKILLS=1` skips `.claude/skills`. ([skills](https://opencode.ai/docs/skills/), [rules](https://opencode.ai/docs/rules/))
- MCP: key `mcp` in `~/.config/opencode/opencode.json` or the project `opencode.json`. Config files are merged, not replaced. Local: `{"type": "local", "command": ["npx", "-y", "pkg"], "environment": {...}}`. Remote: `{"type": "remote", "url": "...", "headers": {...}}`. Secrets: `{env:VAR}` (empty if unset) and `{file:path}`. ([MCP](https://opencode.ai/docs/mcp-servers/), [config](https://opencode.ai/docs/config/))
- Instructions: project `AGENTS.md`, else `CLAUDE.md`, searched upward; global `~/.config/opencode/AGENTS.md`, else `~/.claude/CLAUDE.md`. "The first matching file wins in each category." The `instructions` key adds files, globs, and URLs. ([rules](https://opencode.ai/docs/rules/))
- Hooks: no hook file. JS/TS plugins in `~/.config/opencode/plugins/` and `.opencode/plugins/`, with events including `session.created`. The page documents no payload or timing for it. ([plugins](https://opencode.ai/docs/plugins/))
- Other: `agents/`, `commands/`, `modes/`, `tools/` under `~/.config/opencode/` and `.opencode/`. ([config](https://opencode.ai/docs/config/))

## Cursor CLI (bonus)

Sources: [skills](https://cursor.com/docs/context/skills), [MCP](https://cursor.com/docs/context/mcp), [CLI MCP](https://cursor.com/docs/cli/mcp), [CLI usage](https://cursor.com/docs/cli/using), [rules](https://cursor.com/docs/context/rules), [hooks](https://cursor.com/docs/agent/hooks).

- Skills: project `.agents/skills/` and `.cursor/skills/`; user `~/.agents/skills/` and `~/.cursor/skills/`; compatibility `.claude/skills/`, `.codex/skills/`, `~/.claude/skills/`, `~/.codex/skills/`. Scanned recursively. `name` "must match the parent folder name". Precedence is not documented. The skills page does not say whether the CLI scans the same folders. ([skills](https://cursor.com/docs/context/skills))
- MCP: `~/.cursor/mcp.json` and `.cursor/mcp.json`. stdio `{"type": "stdio", "command", "args", "env", "envFile"}`; remote `{"url", "headers", "auth"}`. `${env:NAME}` in `command`, `args`, `env`, `url`, `headers`. "MCP in the CLI uses the same configuration as the editor." ([MCP](https://cursor.com/docs/context/mcp), [CLI MCP](https://cursor.com/docs/cli/mcp))
- Instructions: `.cursor/rules/*.mdc` (plain `.md` is ignored) and `AGENTS.md` (root and nested). "The CLI also reads `AGENTS.md` and `CLAUDE.md` at the project root". User rules live in the app's settings, and no file on disk is documented. ([rules](https://cursor.com/docs/context/rules), [CLI usage](https://cursor.com/docs/cli/using))
- Hooks: `~/.cursor/hooks.json` and `.cursor/hooks.json` (`{"version": 1, "hooks": {...}}`). `sessionStart` is "Called when a new composer conversation is created", and is fire-and-forget. CLI support is stated only for `workspaceOpen`. ([hooks](https://cursor.com/docs/agent/hooks))

## GitHub Copilot CLI (bonus)

Sources: [skills](https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-skills), [MCP](https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-mcp-servers), [instructions](https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-custom-instructions), [hooks how-to](https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/use-hooks), [hooks reference](https://docs.github.com/en/copilot/reference/hooks-configuration). Latest release `v1.0.97`.

- Skills: project `.github/skills`, `.claude/skills`, `.agents/skills`; personal `~/.copilot/skills`, `~/.agents/skills`. `name` is required and lowercase with hyphens; no length limit is documented. `/skills reload` loads skills added mid-session. ([skills](https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-skills))
- MCP: user `~/.copilot/mcp-config.json`; project `.mcp.json` (wins) and `.github/mcp.json`, walking up to the repo root. Both use `mcpServers`. stdio `{"type": "local", "command", "args", "env", "tools"}`; remote `{"type": "http", "url", "headers", "tools"}`. Variable interpolation is not documented. ([MCP](https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-mcp-servers))
- Instructions: `~/.copilot/copilot-instructions.md` and `~/.copilot/instructions/**/*.instructions.md`; repo `.github/copilot-instructions.md`, `.github/instructions/**/*.instructions.md`, and `AGENTS.md`, `CLAUDE.md`, `.claude/CLAUDE.md`, `GEMINI.md`. Everything applicable is combined, with no defined precedence. ([instructions](https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-custom-instructions))
- Hooks: `~/.copilot/hooks/*.json` and `.github/hooks/*.json` (`{"version": 1, "hooks": {...}}`, with `bash` and `powershell` command keys), loaded at CLI start. `sessionStart` input `source` is `startup`, `resume`, or `new`. "Only `additionalContext` is consumed for `sessionStart`." ([hooks how-to](https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/use-hooks), [hooks reference](https://docs.github.com/en/copilot/reference/hooks-configuration))

## Amp (bonus)

Sources: [skills](https://ampcode.com/docs/customize/skills), [MCP](https://ampcode.com/docs/customize/mcp), [AGENTS.md](https://ampcode.com/docs/customize/agents-md), [plugins](https://ampcode.com/docs/customize/plugins).

- Skills, in precedence order ("Amp uses the first skill with a given frontmatter `name`"): `~/.config/agents/skills/`, `~/.agents/skills/`, `~/.config/amp/skills/`, `.agents/skills/` and `.claude/skills/` in the project and its parents, `~/.claude/skills/`, `~/.claude/plugins/cache/`. Up to five levels deep. The `reload_skills` tool re-scans, and new threads pick up changes. A skill may bundle MCP servers (`mcp.json` or `mcpServers` frontmatter). ([skills](https://ampcode.com/docs/customize/skills))
- MCP: `amp.mcpServers` in `~/.config/amp/settings.json` or `.amp/settings.json` (workspace servers need `amp mcp approve`). stdio `command`, `args`, `env`; remote `url`, `headers`; `${VAR_NAME}`. ([MCP](https://ampcode.com/docs/customize/mcp))
- Instructions: `AGENTS.md` (fallback `AGENT.md`, `CLAUDE.md`) in the cwd and parents up to `$HOME`, plus subtrees on demand; `~/.config/amp/AGENTS.md` and `~/.config/AGENTS.md`; system paths. `@path` includes with globs. ([AGENTS.md](https://ampcode.com/docs/customize/agents-md))
- Hooks: none documented. TS/JS plugins in `~/.config/amp/plugins/` and `.amp/plugins/`, with event `session.start`. ([plugins](https://ampcode.com/docs/customize/plugins))

---

## Implications for AIStack

### Skills: two folders cover nearly every agent

- `~/.agents/skills` is read by Codex, Gemini CLI, Kimi Code, opencode, Cursor, Copilot CLI, and Amp. It is not read by Claude Code (undocumented, so treat it as absent) or ZCode (import only). agentskills.io calls it "a widely-adopted convention for cross-client skill sharing" and notes that the spec "does not mandate where skill directories live". ([agentskills.io client guide](https://agentskills.io/client-implementation/adding-skills-support.md))
- `~/.claude/skills` is read by Claude Code, and also by opencode, Cursor, and Amp. Copilot reads `.claude/skills` only at project level.
- ADR-0018's model ("a harness is a skills folder with a name") holds, but the folder is shared. A harness keyed `codex` that writes `~/.agents/skills` is in fact also Gemini, Kimi, opencode, Cursor, Copilot, and Amp. Naming that entry after the folder (for example "Shared agents folder: Codex, Gemini, ...") would describe what a placement does more honestly than naming it after Codex. The ADR already says "a tool that reads a folder already listed needs none".
- **Duplicates.** A skill placed in both folders is seen twice by opencode, Cursor, and Amp. Amp takes the first match, and `~/.agents/skills` ranks above `~/.claude/skills`. opencode and Cursor document no precedence, and opencode asks for unique names. The dashboard should probably say so when the same skill is placed in both.
- **Codex legacy folder.** Codex still reads `~/.codex/skills` ([host_roots.rs](https://github.com/openai/codex/blob/rust-v0.162.1/codex-rs/ext/skills/src/host_roots.rs#L96-L101)), and so does Cursor. AIStack should install only into `~/.agents/skills`, but a backup scan of a Codex machine may find skills in the old folder.
- **Name rule.** AIStack's push validation already enforces the spec's name rule, and an install writes the folder under that name. That is the strictest form any agent requires: opencode and Cursor require `name` to equal the folder name. Kimi's flat `<name>.md` form and Gemini's unvalidated names are looser and need nothing from AIStack.
- **Reload.** Claude Code, Codex, and Kimi pick up an installed skill in the running session. Gemini needs `/skills reload`, Copilot `/skills reload`, and Amp `reload_skills` or a new thread. A result that tells the agent to reload where needed covers the gap.

### Where sync could start automatically

| Agent | Session-start mechanism | Can it put text before the model? |
|---|---|---|
| Claude Code | `SessionStart` command hook in `~/.claude/settings.json`; `reloadSkills: true` makes newly installed skills visible | Yes, stdout |
| Codex | `SessionStart` in `~/.codex/hooks.json` | Yes, stdout as developer context. The user must trust the hook once, and again after any change. |
| Gemini CLI | `SessionStart` in `~/.gemini/settings.json` | Yes, JSON `additionalContext` |
| Copilot CLI | `sessionStart` in `~/.copilot/hooks/*.json` | Yes, `additionalContext` |
| Kimi Code | `SessionStart` in `~/.kimi-code/config.toml` | No, observation only |
| Cursor | `sessionStart` in `~/.cursor/hooks.json` | Not stated; fire-and-forget, and CLI support unconfirmed |
| opencode, Amp | `session.created` / `session.start` in a JS/TS plugin | Not a hook file; would need a plugin |
| ZCode | `SessionStart` in `~/.zcode/cli/config.json` | Documented as injecting constraints before the first request |

- An MCP call cannot be made from a hook at launch: Claude Code skips `mcp_tool` hooks on `SessionStart` at startup, and no other agent offers one. So the hook is a command.
- `sync` is read-only and the agent acts (ADR-0004, ADR-0006). The smallest hook therefore prints one line, such as "run the sync-aistack skill", into context. That works in Claude Code, Codex, Gemini, and Copilot without the hook holding a token or calling the server.
- A hook that synced on its own would need a local client holding the machine token. That is DESIGN.md §5 item 4 (background sync) and is a separate decision.
- Installing a hook means editing a settings file the user also edits: `~/.claude/settings.json`, `~/.codex/hooks.json`, or `~/.gemini/settings.json`. Codex adds a trust prompt by design. This makes it an opt-in step offered at setup, not something to do silently.

### A common model for MCP server definitions

Every agent describes the same thing. The fields that matter, with how each agent spells them:

| Concept | Claude Code | Codex | Gemini | Kimi | opencode | Cursor | Copilot | Amp |
|---|---|---|---|---|---|---|---|---|
| User file and key | `~/.claude.json` (written by `claude mcp add`) | `~/.codex/config.toml` `[mcp_servers.X]` | `~/.gemini/settings.json` `mcpServers` | `~/.kimi-code/mcp.json` `mcpServers` | `~/.config/opencode/opencode.json` `mcp` | `~/.cursor/mcp.json` `mcpServers` | `~/.copilot/mcp-config.json` `mcpServers` | `~/.config/amp/settings.json` `amp.mcpServers` |
| stdio | `command`, `args`, `env` | `command`, `args`, `env`, `cwd` | `command`, `args`, `env`, `cwd` | `command`, `args`, `env`, `cwd` | `type: local`, `command` as one array, `environment` | `type: stdio`, `command`, `args`, `env` | `type: local`, `command`, `args`, `env` | `command`, `args`, `env` |
| Streamable HTTP | `type: http`, `url` | `url` | `httpUrl` (`url` is SSE) | `url` | `type: remote`, `url` | `url` | `type: http`, `url` | `url` |
| Header from a secret | `"Bearer ${VAR}"` | `bearer_token_env_var` or `env_http_headers` | `"Bearer $VAR"` | `bearerTokenEnvVar` only | `"Bearer {env:VAR}"` | `"Bearer ${env:VAR}"` | not documented | `"Bearer ${VAR}"` |
| Tool filter | not covered here | `enabled_tools`, `disabled_tools` | `includeTools`, `excludeTools` | `enabledTools`, `disabledTools` | not covered here | not covered here | `tools` | `includeTools` (skills) |

What the common model needs:

1. **A neutral record**: `name`; `transport` (`stdio` or `http`; SSE is legacy everywhere); for stdio, `command`, `args`, `cwd`, `env`; for HTTP, `url`, `headers`; `enabled`; optionally a tool allow-list and deny-list. Every agent can express this except opencode's single `command` array, which is a mechanical join of `command` and `args`.
2. **Secrets as references, never values** (ADR-0018 already says "only the name of an environment variable is ever stored"). An env or header value is either a literal or `{env: NAME}`. Each renderer writes its own form: `${NAME}`, `$NAME`, `{env:NAME}`, `${env:NAME}`, or Codex's and Kimi's by-name fields. Two agents limit this. Kimi can only take a bearer token from a variable, and the Copilot pages read document no interpolation. For those, a header that needs a secret cannot be expressed without writing the value. The model should mark such a definition unsupported for that harness rather than write a plaintext secret.
3. **Per-harness renderers, not a generic format.** The files are owned by the agent and hold other state: `~/.claude.json` holds the sign-in session, and the Gemini, Amp, and opencode files hold all their other settings. A renderer should merge one named entry and leave everything else alone, or use the agent's own CLI where one exists (`claude mcp add-json --scope user`, `codex mcp add`, `gemini mcp add -s user`, `copilot mcp add`). AIStack's own entry in each file, holding the machine token as a literal `Authorization` header as ADR-0018 describes, is one such entry. Codex (`http_headers`), Claude Code (`headers`), Gemini, Cursor, opencode, Copilot, and Amp all take a static header; Kimi takes static `headers` too.
4. **No shared MCP file to lean on yet.** ZCode reads `~/.agents/mcp.json` but defers to its own file. No other agent researched documents that path. MCP will need one projection per harness. The skills story, where one folder serves seven agents, does not repeat here.

### Instruction files

- `AGENTS.md` is the common name: Codex, Kimi, opencode, Cursor, Copilot, Amp, and ZCode read it by default. Claude Code reads it only when there is no `CLAUDE.md`; Gemini only when configured.
- The global files all differ: `~/.claude/CLAUDE.md`, `~/.codex/AGENTS.md`, `~/.gemini/GEMINI.md`, `~/.kimi-code/AGENTS.md` and `~/.agents/AGENTS.md`, `~/.config/opencode/AGENTS.md`, `~/.copilot/copilot-instructions.md`, `~/.config/amp/AGENTS.md`, `~/.zcode/AGENTS.md`.
- Imports exist in Claude Code (`@path`, four hops), Gemini (`@file`, depth 5), and Amp (`@path` with globs). Codex and Kimi document none. One canonical global file could be imported by Claude Code, Gemini, and Amp, but would have to be written in full for Codex, Kimi, opencode, Copilot, and ZCode. That is the shape of the separate instruction-file ADR.
