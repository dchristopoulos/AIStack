# The two principals of ADR-0003, spelled as OAuth scopes so FastMCP's own `require_scopes`
# is the authorization mechanism and AIStack ships no middleware of its own.

# The invite code. May call `join` and nothing else.
BOOTSTRAP_SCOPE = "bootstrap"

# A registered machine's permanent token. May call everything except `join`.
MACHINE_SCOPE = "machine"
