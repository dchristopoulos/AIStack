# Full local sync instead of runtime proxy skills

Status: accepted

Skills are fully materialized on disk (body plus bundled files) and run natively after install, with no runtime dependency on AIStack. The MCP server is only the install and sync channel.

The alternative we evaluated was a runtime proxy: generate a tiny local skill whose body tells the agent to fetch the canonical instructions from the AIStack MCP when the skill triggers. It loses on every axis. Token cost is higher, because skills already load their body from disk only on trigger, so the proxy pays for a stub, a tool call, and the body arriving in the tool result. It adds trigger-time latency and an offline failure mode. It depends on the model reliably following a two-hop indirection. And bundled scripts and reference files must reach the disk anyway for a skill to run, so keeping only the body remote means building and maintaining two mechanisms where one will do.

The proxy would have bought instant updates, instant revocation, and central usage analytics. Not enough to pay for the above. Revisit if a requirement appears that full sync genuinely cannot serve, such as private skill bodies that must never touch disk.
