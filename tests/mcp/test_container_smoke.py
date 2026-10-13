import importlib.util
import pathlib

import pytest

from tests.conftest import INVITE_CODE

pytestmark = pytest.mark.anyio

SCRIPT = pathlib.Path(__file__).parents[2] / "scripts" / "container_smoke.py"


async def test_the_container_smoke_script_passes_against_this_server(server_url, tmp_path):
    """CI is the only place the script meets a container, and a tool that changed shape would
    fail there after the image is built. Both phases run here first, with no restart between."""
    spec = importlib.util.spec_from_file_location("container_smoke", SCRIPT)
    smoke = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(smoke)
    base_url = server_url.removesuffix("/mcp")
    state_file = tmp_path / "state.json"

    await smoke.fresh(base_url, INVITE_CODE, state_file)
    await smoke.restarted(base_url, INVITE_CODE, state_file)
