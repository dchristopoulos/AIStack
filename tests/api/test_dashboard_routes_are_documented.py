"""The page is not the only way to learn the routes behind it: `docs/DESIGN.md` lists them,
with the body keys each route takes, every field `/api/state` returns, and every tool."""

import inspect
import pathlib
import re

import pytest

import aistack.api.dashboard  # noqa: F401  (registers the routes)
from aistack.db.engine import build_session_factory
from aistack.mcp.local import local_mcp
from aistack.mcp.mcp import mcp
from aistack.services import (
    dashboard_service,
    onboarding_service,
    skill_service,
    team_service,
)
from tests.archives import skill_archive

_DESIGN = pathlib.Path(__file__).parents[2] / "docs" / "DESIGN.md"
# What the route adds to what `dashboard_service.state` returns.
_ADDED_BY_THE_ROUTE = {"server", "library", "this_computer"}
# Every key `library` can hold: on a server, a computer, a database, and a GitHub Library.
_LIBRARY_KEYS = {"kind", "provider", "host", "repository", "problem", "unpublished"}
# Objects keyed by data, not by field name: their keys are harness names.
_KEYED_BY_DATA = {"last_synced"}


def _section(start: str, end: str) -> str:
    text = _DESIGN.read_text()
    begin = text.index(start) + len(start)
    return text[begin:text.index(end, begin)]


def _routes():
    # FastMCP keeps custom routes in a private list and has no public way to read them back.
    # It is pinned to one release, so this breaks loudly on an upgrade and not silently.
    return [route for route in mcp._additional_http_routes
            if route.path.startswith(("/api", "/app"))]


def test_every_dashboard_route_is_in_the_design_document():
    documented = _DESIGN.read_text()
    routes = [f"{method} {route.path}" for route in _routes()
              for method in sorted(route.methods - {"HEAD"})]

    assert len(routes) >= 19
    assert [route for route in routes if f"`{route}`" not in documented] == []


def test_every_body_key_a_route_reads_is_in_its_row():
    rows = {line.split("`")[1]: line for line in _DESIGN.read_text().splitlines()
            if line.startswith("| `POST /api/")}
    missing = []
    for route in _routes():
        if "POST" not in route.methods or not route.path.startswith("/api/"):
            continue
        source = inspect.getsource(inspect.unwrap(route.endpoint))
        row = rows.get(f"POST {route.path}", "")
        missing += [f"POST {route.path}: {key}"
                    for key in re.findall(r'_(?:text|flag)\(body, "(\w+)"', source)
                    if f"`{key}`" not in row]

    assert missing == []


def _keys(value, found: set[str]) -> set[str]:
    if isinstance(value, dict):
        for key, inner in value.items():
            found.add(key)
            if key not in _KEYED_BY_DATA:
                _keys(inner, found)
    elif isinstance(value, list):
        for inner in value:
            _keys(inner, found)
    return found


@pytest.fixture(name="shown")
def shown_fixture(engine):
    """A state with every kind of object in it: a second computer, a skill taken from a
    team, a team member, a group, and an invite."""
    session_factory = build_session_factory(engine)
    with session_factory.begin() as session:
        me = onboarding_service.join(session, "dimitris", "macbook", "MACOS")
        onboarding_service.add_machine(session, me.user.user_id, "desktop", "LINUX",
                                       added_by=me.machine.machine_id)
        maria = onboarding_service.join(session, "maria", "laptop", "LINUX")
        skill_service.push(session, machine_id=maria.machine.machine_id,
                           user_id=maria.user.user_id, name="code-review", origin=None,
                           archive=skill_archive("code-review"))
        team_service.create_team(session, me.user.user_id, "acme")
        team_service.join_team(session, maria.user.user_id,
                               team_service.new_invite_code(session, me.user.user_id, "acme"))
        team_service.new_invite_code(session, me.user.user_id, "acme")
        team_service.create_group(session, me.user.user_id, "acme", "backend")
        team_service.set_group_member(session, me.user.user_id, "acme", "backend", "maria",
                                      True)
        skill_service.share(session, maria.user.user_id, "code-review", "acme", "backend")
        skill_service.get_skill(session, me.machine.machine_id, me.user.user_id,
                                "code-review", "acme")
        return dashboard_service.state(session, me.user.user_id)


def test_every_field_of_the_state_is_in_the_design_document(shown):
    documented = _section("**`GET /api/state`.**", "### Schema")
    keys = _keys(shown, set()) | _ADDED_BY_THE_ROUTE | _LIBRARY_KEYS

    # Each kind of object was there to be read, so a missing key is an undocumented one.
    assert {"invites", "can_invite", "source", "placements", "added_by"} <= keys
    # A key is named on its own, `key`, or under its object, `teams[].key` or `source.key`.
    assert sorted(key for key in keys
                  if not re.search(rf"`(?:[\w\[\]]+\.)?{key}`", documented)) == []


def _documented_tools(heading: str) -> set[str]:
    """The tool names at the start of each line of the first text block under `heading`."""
    block = _section(heading, "\n### ").split("```text\n", 1)[1].split("```", 1)[0]
    return {name for line in block.splitlines() if line and not line[0].isspace()
            for name in re.findall(r"(?:^|, )([a-z_]+)",
                                   re.sub(r"\([^)]*\)", "", line.split("→")[0]))}


@pytest.mark.anyio
@pytest.mark.parametrize(("server", "heading"), [
    (mcp, "### Tools (all thirteen, nothing else)"),
    (local_mcp, "### Local mode"),
], ids=["server", "local"])
async def test_the_design_document_lists_exactly_the_registered_tools(server, heading):
    registered = {tool.name for tool in await server.list_tools(run_middleware=False)}

    assert _documented_tools(heading) == registered
