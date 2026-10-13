# The dashboard is served by the server, and a link from chat signs you in

Status: accepted, 2026-10-14 (replaces "FastAPI joins the stack with the dashboard" in `docs/DESIGN.md` §5)

The web application is where a person sees and manages their skills and teams. MCP stays what connects a coding agent to their account. Both are the same server process, the same database session rules, and the same services.

- **No second framework.** The server is already a Starlette application, because FastMCP is one. The dashboard's JSON routes live in `api/dashboard.py`, are registered the way the transfer routes are, and call the services the tools call. FastAPI would add a dependency and a second way to declare a route for no behavior this needs.
- **No build step.** The page is one HTML file with its own CSS and JavaScript, shipped as package data like the setup page. There is no node toolchain to install, pin, or audit, and the container image does not change shape.
- **No passwords.** `open_dashboard` returns a link containing a ticket signed like a transfer ticket: five minutes, its own audience. Opening it sets a session cookie (HttpOnly, SameSite=Lax, Secure over https) that lasts eight hours and is itself a signed ticket with a different audience, so neither can stand in for the other. The signing key lives in memory (ADR-0010), so a restart signs everyone out, which costs one sentence to an agent.
- **A request that changes something must carry a header a cross-site page cannot send.** That is the protection against a forged request. The cookie is Lax and not Strict because the link is usually opened from a chat window on another site, and Strict would withhold the cookie on the redirect that follows sign-in.
- **A session ends with its user's last machine.** An operator takes someone off a server by deleting their machines, so every dashboard request checks that one still exists. Without that, a signed cookie would keep working until it expired.
- **Nothing answers without a credential.** `/app` and `/api/*` refuse without a valid session. `/setup` and `/health` remain the only public routes.
- **The API returns what the caller may see, decided by the same module.** A route never filters in JavaScript what the server should not have sent.

Rejected: a separate front-end project (a second deployable for a one-container product); login with username and password (storage, resets, and lockouts for something a signed link does); long-lived dashboard tokens in the URL (the link is a credential in a browser history, so it is short).
