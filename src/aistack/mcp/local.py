"""The MCP server of local mode: `aistack` over stdio, started by the coding agent (ADR-0020).

It has no authentication, by design: over stdio the caller is whoever could start the
process, and that person is the Library's one user. So it offers only what one person does
with their own Library. Teams need a server that decides who sees what, and onboarding needs
somebody to admit, so neither is registered here, and a test holds the tool list to that.
"""

from fastmcp import FastMCP

# Only deliberate ToolError messages reach the agent, as on the server.
local_mcp = FastMCP("aistack", mask_error_details=True)

from aistack.mcp.tools import local  # noqa: F401, E402
