import contextlib
import os
import subprocess
import uuid

import httpx
import pytest

from aistack.api import dashboard as dashboard_routes
from aistack.bootstrap import start_agent
from aistack.bootstrap.context import application_context
from aistack.mcp.mcp import mcp
from aistack.services import library_log, repository_work, skill_service
from tests.local_dashboard import local_dashboard

pytestmark = pytest.mark.anyio

REQUEST_HEADER = {"X-AIStack-Request": "1"}


@pytest.fixture(name="anyio_backend")
def anyio_backend_fixture():
    return "asyncio"


@pytest.fixture(name="dashboard")
async def dashboard_fixture(tmp_path, portable_engine):
    async with local_dashboard(tmp_path, portable_engine.url.render_as_string(
            hide_password=False)) as served:
        yield served


@contextlib.asynccontextmanager
async def _signed_in(base: str, link: str):
    async with httpx.AsyncClient(base_url=base) as client:
        assert (await client.get(link)).status_code == 303
        yield client


async def test_the_link_signs_in_to_the_persons_own_library(dashboard):
    base, link = dashboard
    async with _signed_in(base, link) as client:
        state = (await client.get("/api/state")).json()

    assert state["server"] is False
    assert state["library"]["kind"] in ("this_computer", "postgresql")
    assert state["user"]["username"] == "maria"
    assert [skill["name"] for skill in state["skills"]] == ["wizard"]


async def test_nothing_is_reachable_without_signing_in(dashboard):
    base, _ = dashboard
    async with httpx.AsyncClient(base_url=base) as client:
        assert (await client.get("/api/state")).status_code == 401
        assert (await client.get("/app")).status_code == 401


async def test_team_routes_and_the_server_routes_are_not_served(dashboard):
    """A team needs a server everyone reaches, and nothing but the page belongs on localhost."""
    base, link = dashboard
    async with _signed_in(base, link) as client:
        assert (await client.post("/api/teams", json={"name": "backend"},
                                  headers=REQUEST_HEADER)).status_code == 404
        assert (await client.post("/api/teams/join", json={"code": "aistinv_x"},
                                  headers=REQUEST_HEADER)).status_code == 404
        for path in ("/mcp", "/setup", "/health", "/invite/aistinv_x"):
            assert (await client.get(path)).status_code == 404, path


async def test_a_page_on_another_host_name_is_turned_away(dashboard):
    """DNS rebinding: a site that points its own name at 127.0.0.1 sends its own Host."""
    base, link = dashboard
    async with httpx.AsyncClient(base_url=base, headers={"Host": "evil.example"}) as client:
        assert (await client.get(link)).status_code == 400


async def test_a_change_needs_the_pages_own_header(dashboard):
    base, link = dashboard
    async with _signed_in(base, link) as client:
        response = await client.post("/api/skills/wizard/remove", json={})
        assert response.status_code == 400
        assert [skill["name"] for skill in (await client.get("/api/state")).json()["skills"]] \
            == ["wizard"]


async def test_a_moved_library_refuses_the_page_and_its_changes(dashboard):
    """AUTO-05: a change made here after a move would reach none of the other computers."""
    base, link = dashboard
    caller = application_context.get_local_principal()
    moved = library_log.Event(uuid.uuid4(), "2026-10-15T09:00:00.000000Z", caller.machine_id,
                              library_log.LIBRARY_MOVED,
                              {"place": {"kind": "github", "repository": "maria/skills"}})
    with application_context.get_session_factory().begin() as session:
        # As replay stores it: this release records no move of its own.
        library_log._store_event(session, moved, published=True)

    async with _signed_in(base, link) as client:
        for response in (await client.get("/api/state"),
                         await client.post("/api/skills/wizard/remove", json={},
                                           headers=REQUEST_HEADER)):
            assert response.status_code == 409
            assert "moved to the GitHub repository maria/skills" in response.json()["error"]

    with application_context.get_session_factory().begin() as session:
        assert [skill.name for skill in skill_service.list_skills(session, caller.user_id)] \
            == ["wizard"]


async def test_a_project_folder_is_not_placed_into_from_the_local_dashboard_yet(dashboard):
    """Its log event is replayed by this release and recorded by a later one (ADR-0026)."""
    base, link = dashboard
    async with _signed_in(base, link) as client:
        machine = (await client.get("/api/state")).json()["machines"][0]["id"]
        refused = await client.post(f"/api/skills/wizard/machines/{machine}",
                                    json={"enabled": True, "project": "github.com/a/b"},
                                    headers=REQUEST_HEADER)
        added = await client.post(f"/api/machines/{machine}/projects",
                                  json={"project": "github.com/a/b"}, headers=REQUEST_HEADER)

    assert refused.status_code == 400 and "on an AIStack server for now" in refused.json()["error"]
    assert added.status_code == 404


def _kinds() -> list[str]:
    with application_context.get_session_factory().begin() as session:
        return [event.kind for event in library_log.unpublished(session)]


async def test_rules_are_changed_here_and_each_change_is_logged(dashboard):
    """ADR-0039: local mode records rule changes in the release that adds them."""
    base, link = dashboard
    async with _signed_in(base, link) as client:
        writes = [await client.post(path, json=body, headers=REQUEST_HEADER) for path, body in (
            ("/api/rules", {"name": "style", "text": "# Style\n", "agents": ["claude_code"]}),
            ("/api/rules/style/edit", {"text": "# Style\n- Short.\n"}),
            ("/api/rules/style/edit", {"text": "# Style\n- Short.\n"}),
            ("/api/rules/style/rename", {"new_name": "house-style"}),
            ("/api/rules/house-style/agents", {"agents": ["codex"]}),
            ("/api/rules", {"name": "other", "text": "b", "agents": []}),
            ("/api/rules/other/remove", {}),
        )]
        state = (await client.get("/api/state")).json()
        text = await client.get("/api/rules/house-style/text")

    assert [write.status_code for write in writes] == [200] * 7, [w.text for w in writes]
    assert writes[2].json()["unchanged"] is True
    assert [(rule["name"], rule["agents"]) for rule in state["rules"]] == [
        ("house-style", ["codex"])]
    assert text.json()["text"] == "# Style\n- Short.\n"
    # An edit to the same text changes nothing, so it records nothing.
    assert [kind for kind in _kinds() if kind.startswith("rule_")] == [
        library_log.RULE_CREATED, library_log.RULE_EDITED, library_log.RULE_RENAMED,
        library_log.RULE_AGENTS_SET, library_log.RULE_CREATED, library_log.RULE_REMOVED]


def _git(top, *arguments):
    return subprocess.run(["git", "-C", str(top), "-c", "user.name=t",
                           "-c", "user.email=t@example.com", *arguments], check=True,
                          capture_output=True, text=True).stdout


@pytest.fixture(name="shop")
def shop_fixture(tmp_path, monkeypatch):
    """A clone of a repository with a bare remote, and no `gh` on this computer."""
    for name, value in (("GIT_AUTHOR_NAME", "t"), ("GIT_AUTHOR_EMAIL", "t@example.com"),
                        ("GIT_COMMITTER_NAME", "t"), ("GIT_COMMITTER_EMAIL", "t@example.com")):
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(repository_work.shutil, "which", lambda name: None)
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    top = tmp_path / "shop"
    (top / "docs").mkdir(parents=True)
    for path, text in {"AGENTS.md": "# Shop\n", "CLAUDE.md": "Read AGENTS.md.\n",
                       "README.md": "# Read me\n", "docs/guide.md": "A guide.\n"}.items():
        (top / path).write_bytes(text.encode())
    _git(top, "init", "-q", "-b", "main")
    _git(top, "add", ".")
    _git(top, "commit", "-qm", "init")
    _git(top, "remote", "add", "origin", str(remote))
    _git(top, "push", "-qu", "origin", "main")
    return top


async def _add(client, top, ticked=("AGENTS.md", "CLAUDE.md")) -> httpx.Response:
    return await client.post("/api/projects/add", headers=REQUEST_HEADER,
                             json={"folder": str(top), "ticked": list(ticked)})


def _files(state, key) -> dict:
    return {file["path"]: file for file in state["project_files"] if file["project"] == key}


async def test_a_folder_here_is_added_with_the_files_the_page_ticked(dashboard, shop):
    base, link = dashboard
    async with _signed_in(base, link) as client:
        no_header = await client.post("/api/projects/add", json={"folder": str(shop)})
        added = await _add(client, shop)
        key = added.json()["project"]
        ticked = await client.post("/api/projects/files/tick", headers=REQUEST_HEADER,
                                   json={"project": key, "path": "README.md", "ticked": True})
        off = await client.post("/api/projects/files/turn-off", headers=REQUEST_HEADER,
                                json={"project": key, "path": "CLAUDE.md", "turned_off": True})
        state = (await client.get("/api/state")).json()

    assert no_header.status_code == 400
    assert added.status_code == 200 and ticked.status_code == 200 and off.status_code == 200
    assert added.json()["name"] == "shop"
    files = _files(state, key)
    assert {path: file["ticked"] for path, file in files.items()} == {
        "AGENTS.md": True, "CLAUDE.md": True, "README.md": True, "docs/guide.md": False}
    assert files["CLAUDE.md"]["turned_off"] and files["AGENTS.md"]["project_name"] == "shop"
    # The page reads a ticked file's text from this working copy, and nothing else.
    assert files["README.md"]["text"] == "# Read me\n" and files["README.md"]["edit"] is None
    assert files["docs/guide.md"]["text"] is None
    assert _kinds()[-3:] == [library_log.PROJECT_FILES_LISTED, library_log.PROJECT_FILE_TICKED,
                             library_log.PROJECT_FILE_TURNED_OFF]


async def test_an_edit_is_written_here_only_over_the_text_it_started_from(dashboard, shop):
    base, link = dashboard
    async with _signed_in(base, link) as client:
        key = (await _add(client, shop)).json()["project"]
        agents = _files((await client.get("/api/state")).json(), key)["AGENTS.md"]
        edit = {"project": key, "path": "AGENTS.md", "base_hash": agents["content_hash"]}
        no_header = await client.post("/api/projects/files/edit",
                                      json=edit | {"text": "# Shop\nTests first.\n"})
        held = await client.post("/api/projects/files/edit", headers=REQUEST_HEADER,
                                 json=edit | {"text": "key: ghp_" + "a" * 36 + "\n"})
        written = await client.post("/api/projects/files/edit", headers=REQUEST_HEADER,
                                    json=edit | {"text": "# Shop\nTests first.\n"})
        after = _files((await client.get("/api/state")).json(), key)["AGENTS.md"]
        (shop / "AGENTS.md").write_text("# Shop\nChanged in an editor.\n")
        stale = await client.post("/api/projects/files/edit", headers=REQUEST_HEADER,
                                  json=edit | {"text": "# Shop\nOver the editor.\n"})
        unlisted = await client.post("/api/projects/files/edit", headers=REQUEST_HEADER,
                                     json=edit | {"path": "../outside.md", "text": "x"})

    assert no_header.status_code == 400
    assert held.json()["saved"] is False and held.json()["credential_lines"] == [1]
    assert written.status_code == 200, written.text
    assert written.json()["saved"] is True and written.json()["unchanged"] is False
    # Written, and not committed: the page offers Commit… for it.
    assert after["text"] == "# Shop\nTests first.\n"
    assert after["edit"]["written_on"] and after["edit"]["note"] is None
    assert stale.status_code == 409 and "changed" in stale.json()["error"]
    assert (shop / "AGENTS.md").read_text() == "# Shop\nChanged in an editor.\n"
    assert unlisted.status_code == 400
    assert _git(shop, "status", "--porcelain") == " M AGENTS.md\n"


async def test_an_edit_is_not_written_into_a_folder_that_is_another_repository_now(dashboard,
                                                                                    shop):
    base, link = dashboard
    async with _signed_in(base, link) as client:
        key = (await _add(client, shop)).json()["project"]
        agents = _files((await client.get("/api/state")).json(), key)["AGENTS.md"]
        _git(shop, "remote", "set-url", "origin", "git@github.com:someone/else.git")
        refused = await client.post("/api/projects/files/edit", headers=REQUEST_HEADER, json={
            "project": key, "path": "AGENTS.md", "base_hash": agents["content_hash"],
            "text": "# Elsewhere\n"})
        state = (await client.get("/api/state")).json()

    assert refused.status_code == 400 and "no longer" in refused.json()["error"]
    assert (shop / "AGENTS.md").read_text() == "# Shop\n"
    assert _files(state, key)["AGENTS.md"]["text"] is None


async def test_commit_shares_the_file_on_a_branch_of_its_own(dashboard, shop, tmp_path):
    base, link = dashboard
    (shop / "README.md").write_text("Work in progress that is not shared.\n")
    async with _signed_in(base, link) as client:
        key = (await _add(client, shop)).json()["project"]
        agents = _files((await client.get("/api/state")).json(), key)["AGENTS.md"]
        await client.post("/api/projects/files/edit", headers=REQUEST_HEADER, json={
            "project": key, "path": "AGENTS.md", "base_hash": agents["content_hash"],
            "text": "# Shop\nTests first.\n"})
        no_note = await client.post("/api/projects/files/commit", headers=REQUEST_HEADER,
                                    json={"project": key, "path": "AGENTS.md", "note": " "})
        shared = await client.post("/api/projects/files/commit", headers=REQUEST_HEADER,
                                   json={"project": key, "path": "AGENTS.md",
                                         "note": "Say tests come first"})

    assert no_note.status_code == 400
    assert shared.status_code == 200, shared.text
    branch = shared.json()["branch"]
    assert branch.startswith("aistack/agents-md-") and shared.json()["opened"] is False
    remote = tmp_path / "remote.git"
    assert _git(remote, "show", f"{branch}:AGENTS.md") == "# Shop\nTests first.\n"
    assert _git(remote, "diff", "--name-only", "main", branch) == "AGENTS.md\n"
    assert _git(remote, "log", "-1", "--format=%s", branch) == "Say tests come first\n"
    # This computer's branch, index and other work are as they were.
    assert _git(shop, "rev-parse", "--abbrev-ref", "HEAD") == "main\n"
    assert _git(shop, "rev-parse", "HEAD") == _git(remote, "rev-parse", "main")
    assert _git(shop, "status", "--porcelain") == " M AGENTS.md\n M README.md\n"


@pytest.fixture(name="started")
def started_fixture(monkeypatch):
    """What `aistack start --new-terminal` was run with, instead of opening a window."""
    runs = []

    def run(command, **options):
        runs.append((command, options, os.listdir(options["cwd"])))
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(start_agent, "_run_from_page", run)
    return runs


def test_the_server_has_no_route_that_starts_a_program():
    """ADR-0038: only the localhost dashboard opens a terminal on the computer it runs on."""
    # FastMCP keeps custom routes in a private list; it is pinned, so an upgrade breaks this.
    server = {route.path for route in mcp._additional_http_routes}

    assert "/api/start-agent" in {route.path for route in dashboard_routes.LOCAL_ROUTES}
    assert [path for path in server if "start" in path] == []


async def test_the_page_opens_a_terminal_running_aistack_start(dashboard, started):
    base, link = dashboard
    async with _signed_in(base, link) as client:
        response = await client.post("/api/start-agent", headers=REQUEST_HEADER, json={
            "agent": "codex", "project": "github.com/a/b", "skills": ["wizard", "tdd"]})

    assert response.status_code == 200
    [(command, options, cwd_holds)] = started
    assert command[1:] == ["-m", "aistack.bootstrap", "start", "--new-terminal",
                           "--agent=codex", "--project=github.com/a/b", "--skills=wizard,tdd"]
    # No shell, nothing read from the dashboard's own input, and no folder a key could name.
    assert "shell" not in options and options["stdin"] == subprocess.DEVNULL
    assert cwd_holds == []


@pytest.mark.parametrize("body", [
    {"agent": "vim", "project": "github.com/a/b", "skills": ["wizard"]},
    {"agent": "codex", "project": "github.com/a/b", "skills": []},
    {"agent": "codex", "project": "github.com/a/b", "skills": ["a,b"]},
    {"agent": "codex", "project": "github.com/a/b", "skills": ["--yes"]},
    {"agent": "codex", "project": "github.com/a/b", "skills": "wizard"},
    {"agent": "codex", "project": "/home/maria/code", "skills": ["wizard"]},
    {"agent": "codex", "project": "~/code/b", "skills": ["wizard"]},
    {"agent": "codex", "project": "c:/code/b", "skills": ["wizard"]},
    {"agent": "codex", "project": "a b/c", "skills": ["wizard"]},
    {"agent": "codex", "skills": ["wizard"]},
], ids=["agent", "no-skill", "comma", "flag", "text", "absolute", "home", "drive", "space",
        "missing"])
async def test_a_start_with_anything_unchecked_runs_nothing(dashboard, started, body):
    base, link = dashboard
    async with _signed_in(base, link) as client:
        response = await client.post("/api/start-agent", headers=REQUEST_HEADER, json=body)

    assert response.status_code == 400
    assert started == []


async def test_a_start_needs_the_session_and_the_pages_header(dashboard, started):
    base, link = dashboard
    body = {"agent": "codex", "project": "github.com/a/b", "skills": ["wizard"]}
    async with httpx.AsyncClient(base_url=base) as stranger:
        assert (await stranger.post("/api/start-agent", headers=REQUEST_HEADER,
                                    json=body)).status_code == 401
    async with _signed_in(base, link) as client:
        assert (await client.post("/api/start-agent", json=body)).status_code == 400

    assert started == []


async def test_a_refusal_says_the_commands_own_sentence(dashboard, monkeypatch):
    monkeypatch.setattr(start_agent, "_run_from_page", lambda command, **_: (
        subprocess.CompletedProcess(command, 1, "", "Codex was not started. No folder.\n")))
    base, link = dashboard
    async with _signed_in(base, link) as client:
        response = await client.post("/api/start-agent", headers=REQUEST_HEADER, json={
            "agent": "codex", "project": "github.com/a/b", "skills": ["wizard"]})

    assert response.status_code == 400
    assert response.json()["error"] == "Codex was not started. No folder."


async def test_look_inside_lists_a_folder_here_and_the_server_has_no_such_route(dashboard,
                                                                                 tmp_path):
    """ADR-0038: local mode looks inside a folder at once; a server never reads a disk."""
    top = tmp_path / "shop"
    (top / ".claude" / "skills" / "shop-release").mkdir(parents=True)
    (top / ".claude" / "skills" / "shop-release" / "SKILL.md").write_text("x\n")
    for path, text in {"AGENTS.md": "rules\n", "README.md": "readme\n", "app.py": "x\n"}.items():
        (top / path).write_bytes(text.encode())  # no CRLF on Windows: sizes are exact
    subprocess.run(["git", "-C", str(top), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(top), "add", "."], check=True)
    base, link = dashboard
    async with _signed_in(base, link) as client:
        found = await client.post("/api/projects/look-inside", headers=REQUEST_HEADER,
                                  json={"folder": str(top)})
        refused = await client.post("/api/projects/look-inside", headers=REQUEST_HEADER,
                                    json={"folder": "relative/path"})
        no_header = await client.post("/api/projects/look-inside", json={"folder": str(top)})

    assert found.status_code == 200, found.text
    shown = found.json()
    assert [(f["path"], f["size"]) for f in shown["files"]] == [("AGENTS.md", 6),
                                                                ("README.md", 7)]
    assert shown["files"][1]["agents"] == [] and "codex" in shown["files"][0]["agents"]
    assert shown["skills"] == ["shop-release"]
    assert refused.status_code == 400 and no_header.status_code == 400
    assert "/api/projects/look-inside" not in {
        route.path for route in mcp._additional_http_routes}
