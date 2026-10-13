# The MCP endpoint is stateless

Status: accepted

AIStack serves streamable HTTP in stateless mode with plain JSON responses (`stateless_http=True`, `json_response=True`). Every request carries its own bearer and is answered on its own. The server keeps no MCP session.

Why: nothing AIStack does needs a session. No tool sends a notification, asks the client to sample, or elicits (ADR-0012), and one MCP call is already one transaction. A session would be state held only to be thrown away, and it has three costs.

- **A restart strands every client.** Sessions live in the server's memory. After an upgrade or a crash, each connected harness holds a session id the server no longer knows and fails until it reconnects. Stateless, the next request simply works. For a self-hosted server that people restart to rotate an invite code, that is the common case and not an edge.
- **Onboarding needs a handshake.** A new machine has no MCP client configured for this server yet. With sessions, calling `join` over plain HTTP is three requests: initialize, the initialized notification, then the call, threading a session header through. Stateless, it is one `curl`, which is what lets the setup instructions be something an agent can follow reliably on any operating system.
- **A second replica needs sticky routing.** Not a need today, and not a door worth closing for nothing.

Authentication is unaffected: the bearer is verified on every request either way, and the authorization middleware runs before every tool call. Standard MCP clients work unchanged; the suite runs the FastMCP client against the same configuration production uses.

**Consequence.** A feature that needs server-initiated messages (progress streaming, elicitation, resource subscriptions) would need sessions back. None is planned, and ADR-0012 already chose against the one that was considered.

Rejected: keeping sessions and scripting the three-request handshake into setup (fragile across shells, and the restart problem remains); a separate `POST /join` route outside MCP (a second implementation of the one tool whose authorization rule is the most delicate).
