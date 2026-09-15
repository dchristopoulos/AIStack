# The two principals of ADR-0003, spelled as OAuth scopes so FastMCP's own authorization
# primitives do the enforcing and AIStack writes no check of its own. `AIStackTokenVerifier`
# stamps one of these onto every bearer; `mcp/auth/policy.py` says which one a tool needs.

# The invite code. May call `join` and nothing else.
BOOTSTRAP_SCOPE = "bootstrap"

# A registered machine's permanent token. May call everything except `join`.
MACHINE_SCOPE = "machine"
