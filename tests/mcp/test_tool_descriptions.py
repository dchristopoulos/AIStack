import pytest

from aistack.mcp.local import local_mcp
from aistack.mcp.mcp import mcp

pytestmark = pytest.mark.anyio

# Claude Code truncates a tool description at 2,048 characters. Whatever sits past that point
# is an instruction the agent never reads, and the last lines of a description are where the
# return value is explained.
DESCRIPTION_LIMIT = 2048


@pytest.mark.parametrize("server", [mcp, local_mcp], ids=["server", "local"])
async def test_every_tool_description_fits_what_the_client_keeps(server):
    tools = await server._list_tools()
    assert tools

    for tool in tools:
        assert len(tool.description) <= DESCRIPTION_LIMIT, (
            f"{tool.name} is {len(tool.description)} characters; the client keeps "
            f"{DESCRIPTION_LIMIT}.")
