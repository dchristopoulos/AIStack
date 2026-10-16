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


async def test_add_machine_says_its_command_is_a_permanent_key():
    """UX-20: the person carries it through whatever reaches the other computer."""
    description = " ".join((await mcp.get_tool("add_machine")).description.split())

    assert "holds a permanent key for that computer" in description
    assert "delete it from anywhere it was carried" in description
    # PH-15: that computer never ran setup, which creates the folder.
    assert "mkdir -p ~/.claude/skills" in description


async def test_the_sync_skill_download_creates_its_folder():
    """PH-15: a computer added with add_machine has no sync-aistack folder to write into."""
    description = (await mcp.get_tool("sync")).description

    assert "curl -sS --create-dirs -o <folder>/sync-aistack/SKILL.md" in description
