"""A project's folders on the dashboard (ADR-0026): what /api/state shows of them, and the
routes that place skills there and add or remove a project on a computer."""

import pytest

from tests.api.test_dashboard_over_http import _browser, _call, _join, _post, _push, _state
from tests.mcp.conftest import second_machine

pytestmark = pytest.mark.anyio

HERE = {"path": "/Users/dimitris/code/aistack",
        "remote": "git@github.com:dchristopoulos/AIStack.git"}
KEY = "github.com/dchristopoulos/aistack"
NOBODY = "00000000-0000-0000-0000-000000000000"


async def _manage(server_url, token, harness="claude_code"):
    """What "add this project to aistack" does: a project folder's first sync."""
    await _call(server_url, token, "sync", local={}, here=HERE, project=KEY, harness=harness)


def _machine(state, name) -> dict:
    return next(machine for machine in state["machines"] if machine["name"] == name)


async def test_the_state_lists_each_computers_projects_and_its_placements_there(server_url):
    laptop = await _join(server_url, "dimitris")
    await _push(server_url, laptop)
    await _manage(server_url, laptop)
    maria = await _join(server_url, "maria")
    await _manage(server_url, maria)
    async with _browser(server_url, laptop) as browser:
        machine = (await _state(browser))["machines"][0]
        placed = await _post(browser, f"/skills/wizard/machines/{machine['id']}",
                             enabled=True, project=KEY)
        state = await _state(browser)

    assert placed.status_code == 200
    projects = state["machines"][0]["projects"]
    assert [(project["key"], project["name"]) for project in projects] == [(KEY, "aistack")]
    assert [(folder["harness"], folder["path"]) for folder in projects[0]["folders"]] == [
        ("claude_code", HERE["path"])]
    assert {(placement["harness"], placement["project"])
            for placement in state["skills"][0]["placements"]} == {
        ("claude_code", None), ("claude_code", KEY)}


async def test_a_project_known_from_one_computer_is_added_to_another_until_it_syncs(
        server_url):
    laptop = await _join(server_url, "dimitris")
    await _manage(server_url, laptop)
    await second_machine(server_url, laptop)
    async with _browser(server_url, laptop) as browser:
        other = _machine(await _state(browser), "desktop")["id"]
        added = await _post(browser, f"/machines/{other}/projects", project=KEY,
                            harness="agents")
        state = await _state(browser)

    assert added.status_code == 200
    assert _machine(state, "desktop")["projects"][0]["folders"] == [
        {"harness": "agents", "path": None, "last_synced_on": None}]
    assert "agents" in _machine(state, "desktop")["harnesses"]


async def test_removing_a_project_from_a_computer_takes_only_its_placements_there(server_url):
    laptop = await _join(server_url, "dimitris")
    await _push(server_url, laptop)
    await _manage(server_url, laptop)
    async with _browser(server_url, laptop) as browser:
        machine = (await _state(browser))["machines"][0]["id"]
        await _post(browser, f"/skills/wizard/machines/{machine}", enabled=True, project=KEY)
        removed = await _post(browser, f"/machines/{machine}/projects/remove", project=KEY)
        state = await _state(browser)

    assert removed.json() == {"removed": 1}
    assert state["machines"][0]["projects"] == []
    assert [skill["name"] for skill in state["skills"]] == ["wizard"]
    assert [placement["project"] for placement in state["skills"][0]["placements"]] == [None]


async def test_someone_elses_project_or_computer_is_one_that_does_not_exist(server_url):
    dimitris = await _join(server_url, "dimitris")
    await _manage(server_url, dimitris)
    maria = await _join(server_url, "maria")
    await _push(server_url, maria)
    async with _browser(server_url, dimitris) as theirs, _browser(server_url, maria) as browser:
        dimitris_machine = (await _state(theirs))["machines"][0]["id"]
        own = (await _state(browser))["machines"][0]["id"]
        answers = [
            await _post(browser, f"/skills/wizard/machines/{own}", enabled=True, project=KEY),
            await _post(browser, f"/skills/wizard/machines/{own}", enabled=True,
                        project="github.com/nobody/nothing"),
            await _post(browser, f"/machines/{own}/projects", project=KEY),
            await _post(browser, f"/machines/{own}/projects",
                        project="github.com/nobody/nothing"),
            await _post(browser, f"/machines/{dimitris_machine}/projects/remove", project=KEY),
            await _post(browser, f"/machines/{NOBODY}/projects/remove", project=KEY),
        ]

    assert [answer.status_code for answer in answers] == [404] * 6
    texts = [answer.json()["error"] for answer in answers]
    assert texts[0].replace(KEY, "X") == texts[1].replace("github.com/nobody/nothing", "X")
    assert texts[2].replace(KEY, "X") == texts[3].replace("github.com/nobody/nothing", "X")
    assert texts[4].replace(dimitris_machine, "X") == texts[5].replace(NOBODY, "X")


async def test_a_project_change_needs_the_pages_own_header(server_url):
    laptop = await _join(server_url, "dimitris")
    await _manage(server_url, laptop)
    async with _browser(server_url, laptop) as browser:
        machine = (await _state(browser))["machines"][0]["id"]
        refused = await browser.post(f"/api/machines/{machine}/projects/remove",
                                     json={"project": KEY})
        state = await _state(browser)

    assert refused.status_code == 400
    assert state["machines"][0]["projects"] != []
