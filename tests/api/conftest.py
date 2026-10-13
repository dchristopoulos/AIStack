# The dashboard is served by the same in-process server the MCP tests start.
from tests.mcp.conftest import (  # noqa: F401
    anyio_backend_fixture,
    server_url_fixture,
    session_factory_fixture,
)
