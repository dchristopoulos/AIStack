"""Installed sync through authenticated HTTP and signed archive transfers."""

import json

import httpx
import pytest

from aistack.services import server_sync
from aistack.services.server_connection import Connection
from tests.archives import skill_document
from tests.mcp.conftest import call, join, push

pytestmark = pytest.mark.anyio


@pytest.fixture
def home(tmp_path, monkeypatch):
    from aistack.bootstrap import hardware
    monkeypatch.setattr(hardware, "hardware_id", lambda: "program-test-computer")
    monkeypatch.delenv("CODEX_HOME", raising=False)
    (tmp_path / ".claude").mkdir()
    return tmp_path


async def test_sync_installs_updates_backs_up_and_keeps_questions(server_url, home):
    token = await join(server_url)
    await push(server_url, token)
    connection = Connection(server_url, token)
    reports = await server_sync.sync_computer(connection, home, home)
    wizard = home / ".claude/skills/wizard/SKILL.md"
    assert wizard.is_file()
    assert "Installed wizard revision 1" in server_sync.output(reports)
    await push(server_url, token, files={"extra.md": "second\n"})
    reports = await server_sync.sync_computer(connection, home, home)
    assert "Updated wizard revision 2" in server_sync.output(reports)
    assert (wizard.parent / "extra.md").read_text() == "second\n"
    reports = await server_sync.sync_computer(connection, home, home)
    assert server_sync.output(reports, hook=True) == ""
    backup = wizard.parent.parent / "new-skill/SKILL.md"
    backup.parent.mkdir()
    backup.write_text(skill_document("new-skill"))
    wizard.write_text(wizard.read_text() + "\nlocal edits\n")
    reports = await server_sync.sync_computer(connection, home, home)
    assert "Backed up new-skill revision 1" in server_sync.output(reports)
    output = server_sync.output(reports, hook=True)
    assert '"loses_local_edits": true' in output
    assert "get_skill" in output and "push_skill" in output
    assert "local edits" in wizard.read_text()
    assert token not in json.dumps(reports)


async def test_edit_during_download_becomes_question_and_retry_preserves_it(server_url, home, monkeypatch):
    token = await join(server_url)
    await push(server_url, token)
    connection = Connection(server_url, token)
    await server_sync.sync_computer(connection, home, home)
    await push(server_url, token, files={"extra.md": "new revision"})
    wizard = home / ".claude/skills/wizard/SKILL.md"
    get = httpx.AsyncClient.get

    async def editing_get(client, url, **kwargs):
        response = await get(client, url, **kwargs)
        if "/download/" in str(url):
            wizard.write_text("local concurrent edit")
        return response

    monkeypatch.setattr(httpx.AsyncClient, "get", editing_get)
    report = (await server_sync.sync_computer(connection, home, home))[0]
    assert report["failures"] and "changed during download" in report["failures"][0]
    assert wizard.read_text() == "local concurrent edit"
    monkeypatch.setattr(httpx.AsyncClient, "get", get)
    report = (await server_sync.sync_computer(connection, home, home))[0]
    assert report["ask"][0]["local"] == "unknown"
    assert wizard.read_text() == "local concurrent edit"


async def test_failed_download_leaves_retryable_install(server_url, home, monkeypatch):
    token = await join(server_url)
    await push(server_url, token)
    connection = Connection(server_url, token)
    get = httpx.AsyncClient.get

    async def unavailable(*args, **kwargs):
        raise httpx.ConnectError("private URL must not be printed")

    monkeypatch.setattr(httpx.AsyncClient, "get", unavailable)
    reports = await server_sync.sync_computer(connection, home, home)
    assert reports[0]["failures"]
    assert "private URL" not in server_sync.output(reports)
    monkeypatch.setattr(httpx.AsyncClient, "get", get)
    await server_sync.sync_computer(connection, home, home)
    assert (home / ".claude/skills/wizard/SKILL.md").is_file()


async def test_project_discovery_does_not_manage_or_read_repository_skills(server_url, home, tmp_path):
    import subprocess
    project = tmp_path / "project"
    project.mkdir()
    subprocess.run(["git", "init", str(project)], check=True, capture_output=True)
    folder = project / ".claude/skills/repo-skill"
    folder.mkdir(parents=True)
    document = folder / "SKILL.md"
    document.write_text("repository content")
    token = await join(server_url)
    reports = await server_sync.sync_computer(Connection(server_url, token), home, project)
    assert len(reports) == 1 and reports[0]["project"]["managed"] is False
    assert document.read_text() == "repository content"
    assert not (project / ".git/info/exclude").read_text().endswith("/repo-skill/\n")
    key = reports[0]["project"]["key"]
    await call(server_url, token, "sync", local={}, here={"path": str(project), "remote": None}, project=key)
    await push(server_url, token)
    await call(server_url, token, "get_skill", name="wizard", project=key)
    reports = await server_sync.sync_computer(Connection(server_url, token), home, project)
    assert len(reports) == 2
    assert reports[1]["left_to_repository"] == []
    assert (project / ".claude/skills/wizard/SKILL.md").is_file()
    assert document.read_text() == "repository content"
    assert not (project / ".claude/skills/sync-aistack").exists()


async def test_refused_skill_fails_alone(server_url, home, monkeypatch):
    from aistack.commons.exceptions import Busy
    from aistack.services import skill_service

    token = await join(server_url)
    await push(server_url, token, name="alpha")
    await push(server_url, token)
    get_skill = skill_service.get_skill

    def busy_for_alpha(session, machine_id, user_id, name, *args, **kwargs):
        if name == "alpha":
            raise Busy("The server is busy. Try again.")
        return get_skill(session, machine_id, user_id, name, *args, **kwargs)

    monkeypatch.setattr(skill_service, "get_skill", busy_for_alpha)
    reports = await server_sync.sync_computer(Connection(server_url, token), home, home)
    assert reports[0]["failures"] == ["The server is busy. Try again."]
    assert (home / ".claude/skills/wizard/SKILL.md").is_file()
    assert not (home / ".claude/skills/alpha").exists()
    assert "Installed wizard revision 1" in server_sync.output(reports)


def test_a_team_offer_in_two_folders_is_one_question():
    offer = {"name": "wizard", "team": "aistack", "from_revision": 1, "to_revision": 2, "pushed_by": "maria",
             "own_changes": False, "different_skill": False}

    def report(folder, harness, project=None):
        return {"folder": folder, "harness": harness, "project_folder": project, "completed": [], "failures": [],
                "diagnostics": [], "team_updates": [offer]}

    text = server_sync.output([report("/h/.claude/skills", "claude_code"), report("/h/.agents/skills", "agents"),
                               report("/p/.claude/skills", "claude_code", "project-key")], hook=True)
    offers = json.loads(text.splitlines()[0].removeprefix("AIStack team updates: "))
    assert [entry["name"] for entry in offers] == ["wizard"]
    assert offers[0]["folders"] == [
        {"folder": "/h/.claude/skills", "harness": "claude_code"},
        {"folder": "/h/.agents/skills", "harness": "agents"},
        {"folder": "/p/.claude/skills", "harness": "claude_code", "project": "project-key"},
    ]
    assert "Ask once per skill" in text and text.count("wizard") == 1
