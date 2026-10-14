"""The page is not the only way to learn the routes behind it: `docs/DESIGN.md` lists them."""

import pathlib

import aistack.api.dashboard  # noqa: F401  (registers the routes)
from aistack.mcp.mcp import mcp

_DESIGN = pathlib.Path(__file__).parents[2] / "docs" / "DESIGN.md"


def test_every_dashboard_route_is_in_the_design_document():
    documented = _DESIGN.read_text()
    # FastMCP keeps custom routes in a private list and has no public way to read them back.
    # It is pinned to one release, so this breaks loudly on an upgrade and not silently.
    routes = [
        f"{method} {route.path}"
        for route in mcp._additional_http_routes
        if route.path.startswith(("/api", "/app"))
        for method in sorted(route.methods - {"HEAD"})
    ]

    assert len(routes) >= 19
    assert [route for route in routes if f"`{route}`" not in documented] == []
