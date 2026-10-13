# Sync returns its questions as data; the agent asks them in chat

Status: accepted (closes open question 1 in `docs/DESIGN.md` §9)

When sync finds a state it must not act on silently (ADR-0006), it returns that state as a structured entry: the skill, what was found, the options the user may choose, and whether each option replaces local files or discards local edits. The agent asks the user in chat and carries out the answer with `get_skill`, `push_skill`, or `disable_skill`. `sync` itself never blocks on a question.

Why: the alternative was MCP elicitation, where the server opens a form inside the call. Claude Code supports it, in both form and URL mode, with no client configuration, so this is a choice and not a workaround. Three things decide it.

- **Portability.** The second harness is on the roadmap and elicitation support varies by client. Returned data works in every harness that can call a tool.
- **The conversation is the better form.** Ten skills in ten different states are ten dialogs in sequence under elicitation. As data, the agent can group them, answer follow-up questions about what changed, and take "restore all of them except wizard" as one instruction.
- **One transaction per call.** A tool blocked on a human holds its call open for as long as the user takes to answer. Sync as a read that returns immediately keeps "one MCP call is one transaction" true without a carve-out.

The entries are facts, not prose, in line with the rule that tool results carry no preformatted `message`. The consequence flags are part of the contract rather than left to the agent's judgment: a prompt that leads to overwriting local content must say so (§4 The sync contract), and a flag the agent must surface is harder to drop than a sentence it might paraphrase away.

Rejected: elicitation (above); a `resolve_conflict` tool taking the user's answer (a hidden verb, where every answer already maps to an existing tool).
