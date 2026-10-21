"""`aistack sync` writes rules to a temporary home and repository, over real HTTP (ADR-0036)."""

import json
import subprocess

import httpx
import pytest
from sqlalchemy import select

from aistack.db.models.machine import Machine
from aistack.db.models.project import Project
from aistack.db.models.project_file import ProjectFile
from aistack.db.models.user import User
from aistack.services import project_service, rule_files, rule_service, server_sync
from aistack.services.server_connection import Connection
from tests.mcp.conftest import call, join, push

pytestmark = pytest.mark.anyio

OWN = "# Mine\n\nAlways answer in English.\n"


@pytest.fixture
def home(tmp_path, monkeypatch):
    from aistack.services import hardware
    monkeypatch.setattr(hardware, "hardware_id", lambda: "rule-test-computer")
    monkeypatch.delenv("CODEX_HOME", raising=False)
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".codex").mkdir()
    return home


@pytest.fixture
def repository(tmp_path):
    top = tmp_path / "project"
    top.mkdir()
    _git(top, "init", "-q")
    (top / "AGENTS.md").write_text("Run the tests before committing.\n")
    _git(top, "add", "AGENTS.md")
    _git(top, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", "init")
    return top


def _git(top, *arguments):
    return subprocess.run(["git", "-C", str(top), *arguments], check=True, capture_output=True,
                          text=True).stdout


def _user_id(session_factory):
    with session_factory() as session:
        return session.scalar(select(User.user_id).where(User.username == "dimitris"))


def _rules(session_factory, action, *arguments, **keywords):
    with session_factory.begin() as session:
        return action(session, _user_id(session_factory), *arguments, **keywords)


async def _sync(server_url, token, home, cwd, **choices):
    reports = await server_sync.sync_computer(Connection(server_url, token), home, cwd,
                                              choices or None)
    return reports, server_sync.output(reports)


async def _manage(server_url, token, home, top) -> str:
    reports, _ = await _sync(server_url, token, home, top)
    key = reports[0]["project"]["key"]
    await call(server_url, token, "sync", local={}, here={"path": str(top), "remote": None},
               project=key)
    return key


async def test_a_hand_written_file_is_backed_up_and_then_follows_the_person(server_url, home,
                                                                         session_factory):
    claude, codex = home / ".claude/CLAUDE.md", home / ".codex/AGENTS.md"
    claude.write_text(OWN)
    token = await join(server_url)

    _, output = await _sync(server_url, token, home, home)
    assert f"Backed up {claude} as rule claude-md revision 1." in output
    assert claude.read_text() == OWN and not codex.exists()

    # Used for Codex as well: written there, the same text.
    _rules(session_factory, rule_service.set_agents, "claude-md", ["claude_code", "codex"])
    _, output = await _sync(server_url, token, home, home)
    assert codex.read_text() == OWN
    assert f"Wrote rule claude-md revision 1, pushed by dimitris, to {codex}." in output

    # Edited on the page: every file updates.
    _rules(session_factory, rule_service.edit, "claude-md", OWN + "Be brief.\n")
    await _sync(server_url, token, home, home)
    assert claude.read_text() == codex.read_text() == OWN + "Be brief.\n"

    # Edited only here: kept in the Library without asking, and reaches the other file next.
    claude.write_text("Edited here.\n")
    _, output = await _sync(server_url, token, home, home)
    assert f"Backed up {claude} as rule claude-md revision 3." in output
    await _sync(server_url, token, home, home)
    assert codex.read_text() == "Edited here.\n"

    # Edited here and on the page: a question, and nothing is overwritten until answered.
    claude.write_text("Edited here again.\n")
    _rules(session_factory, rule_service.edit, "claude-md", "Edited on the page.\n")
    reports, output = await _sync(server_url, token, home, home)
    question = next(entry for entry in reports[-1]["rule_questions"]
                    if entry["file"] == str(claude))
    assert question["edited_from"] == 3 and question["revision"] == 4
    assert [option["choice"] for option in question["options"]] == ["restore", "push", "skip"]
    assert "--rule-choice" in output and "/transfer/" not in output
    assert claude.read_text() == "Edited here again.\n"

    await _sync(server_url, token, home, home, **{question["key"]: "push"})
    _, output = await _sync(server_url, token, home, home)
    assert claude.read_text() == codex.read_text() == "Edited here again.\n"
    assert server_sync.output((await _sync(server_url, token, home, home))[0], hook=True) == ""


async def test_codex_home_is_where_codex_reads_its_file(server_url, home, tmp_path, monkeypatch,
                                                       session_factory):
    elsewhere = tmp_path / "codex-home"
    elsewhere.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(elsewhere))
    token = await join(server_url)
    _rules(session_factory, rule_service.create, "house", OWN, agents=["codex"])
    await _sync(server_url, token, home, home)
    assert (elsewhere / "AGENTS.md").read_text() == OWN
    assert not (home / ".codex/AGENTS.md").exists()


async def test_project_rules_are_written_beside_the_repositorys_and_kept_out_of_git(
        server_url, home, repository, session_factory):
    token = await join(server_url)
    key = await _manage(server_url, token, home, repository)
    _rules(session_factory, rule_service.create, "house-style", "Use tabs.\n", project=key,
           agents=["claude_code", "codex"])

    _, output = await _sync(server_url, token, home, repository)

    claude = repository / ".claude/rules/aistack-house-style.md"
    assert claude.read_text() == "Use tabs.\n"
    override = (repository / "AGENTS.override.md").read_text()
    assert override.splitlines()[0] == rule_files.OVERRIDE_HEADER
    assert "Run the tests before committing.\n" in override
    assert override.endswith("<!-- aistack:rule house-style -->\nUse tabs.\n")
    exclude = (repository / ".git/info/exclude").read_text().splitlines()
    assert "/.claude/rules/aistack-house-style.md" in exclude and "/AGENTS.override.md" in exclude
    assert _git(repository, "status", "--porcelain") == ""
    assert (repository / "AGENTS.md").read_text() == "Run the tests before committing.\n"

    # The repository's AGENTS.md changes: the override follows it at the next sync.
    (repository / "AGENTS.md").write_text("Run the tests first.\n")
    await _sync(server_url, token, home, repository)
    assert "Run the tests first.\n" in (repository / "AGENTS.override.md").read_text()

    # Edited in the Codex section only: backed up, and Claude Code's file follows.
    edited = (repository / "AGENTS.override.md").read_text().replace("Use tabs.", "Use spaces.")
    (repository / "AGENTS.override.md").write_text(edited)
    _, output = await _sync(server_url, token, home, repository)
    assert "as rule house-style revision 2" in output
    await _sync(server_url, token, home, repository)
    assert claude.read_text() == "Use spaces.\n"


async def test_a_new_project_rule_file_is_backed_up_and_a_removed_rule_asks_before_deleting(
        server_url, home, repository, session_factory):
    token = await join(server_url)
    key = await _manage(server_url, token, home, repository)
    mine = repository / ".claude/rules/aistack-review.md"
    mine.parent.mkdir(parents=True)
    mine.write_text("Review with care.\n")
    _, output = await _sync(server_url, token, home, repository)
    assert f"Backed up {mine} as rule review revision 1." in output

    _rules(session_factory, rule_service.archive, "review", project=key)
    reports, _ = await _sync(server_url, token, home, repository)
    question = reports[-1]["rule_questions"][0]
    assert question["key"] == "project:claude_code:review"
    assert question["removed_from_library"] is True
    assert [option["choice"] for option in question["options"]] == ["remove", "skip"]
    assert mine.exists()
    await _sync(server_url, token, home, repository, **{question["key"]: "remove"})
    assert not mine.exists()


async def test_a_file_turned_off_is_excluded_for_claude_and_left_out_for_codex(
        server_url, home, repository, session_factory):
    token = await join(server_url)
    key = await _manage(server_url, token, home, repository)
    settings = repository / ".claude/settings.local.json"
    settings.parent.mkdir()
    settings.write_text(json.dumps({"permissions": {"allow": ["Bash(ls)"]}}))
    with session_factory.begin() as session:
        project = session.scalar(select(Project).where(Project.key == key))
        session.add(ProjectFile(project_id=project.project_id, path="AGENTS.md", agent="codex",
                                ticked=True, turned_off=True))

    await _sync(server_url, token, home, repository)

    written = json.loads(settings.read_text())
    assert written["permissions"] == {"allow": ["Bash(ls)"]}
    assert written["claudeMdExcludes"] == [str(repository / "AGENTS.md")]
    override = (repository / "AGENTS.override.md").read_text()
    assert override == rule_files.OVERRIDE_HEADER + "\n"
    assert "/.claude/settings.local.json" in (repository / ".git/info/exclude").read_text()
    assert _git(repository, "status", "--porcelain") == ""

    with session_factory.begin() as session:
        session.execute(ProjectFile.__table__.update().values(turned_off=False))
    await _sync(server_url, token, home, repository)
    assert json.loads(settings.read_text())["claudeMdExcludes"] == []
    assert "Run the tests before committing." in (repository / "AGENTS.override.md").read_text()


async def test_an_override_aistack_did_not_make_is_left_alone(server_url, home, repository,
                                                              session_factory):
    token = await join(server_url)
    key = await _manage(server_url, token, home, repository)
    (repository / "AGENTS.override.md").write_text("Someone's own override.\n")
    _rules(session_factory, rule_service.create, "house-style", "Use tabs.\n", project=key,
           agents=["codex"])
    reports, output = await _sync(server_url, token, home, repository)
    assert (repository / "AGENTS.override.md").read_text() == "Someone's own override.\n"
    assert "is not one AIStack made" in output


async def test_nothing_is_written_through_a_link_out_of_the_project(server_url, home, repository,
                                                                    tmp_path, session_factory):
    token = await join(server_url)
    key = await _manage(server_url, token, home, repository)
    outside = tmp_path / "outside"
    outside.mkdir()
    (repository / "AGENTS.override.md").symlink_to(outside / "override.md")
    _rules(session_factory, rule_service.create, "house-style", "Use tabs.\n", project=key,
           agents=["codex"])
    _, output = await _sync(server_url, token, home, repository)
    assert list(outside.iterdir()) == []
    assert "did not write" in output


async def test_a_credential_is_not_backed_up(server_url, home):
    (home / ".claude/CLAUDE.md").write_text("token: aist_" + "x" * 40 + "\n")
    token = await join(server_url)
    reports, output = await _sync(server_url, token, home, home)
    assert "looks like it holds a credential" in output
    assert "aist_xxxx" not in output


async def test_an_older_program_sees_nothing_new_and_no_text_crosses_mcp(server_url, home,
                                                                         session_factory):
    token = await join(server_url)
    _rules(session_factory, rule_service.create, "house", "A secret-free rule text.\n",
           agents=["claude_code"])
    older = await call(server_url, token, "sync", local={})
    assert "rules" not in older and "repository_files" not in older

    newer = await call(server_url, token, "sync", local={}, rules=[
        {"agent": "claude_code", "place": "every_project", "name": None, "digest": None}])
    assert [(entry["name"], entry["action"]) for entry in newer["rules"]] == [("house", "install")]
    assert "A secret-free rule text" not in json.dumps(newer)


async def test_an_upload_for_a_project_no_longer_managed_stores_nothing(server_url, home,
                                                                       repository,
                                                                       session_factory):
    token = await join(server_url)
    key = await _manage(server_url, token, home, repository)
    newer = await call(server_url, token, "sync", local={},
                       here={"path": str(repository), "remote": None}, rules=[
        {"agent": "claude_code", "place": "every_project", "name": None, "digest": None},
        {"agent": "claude_code", "place": "project", "name": "review", "digest": "0" * 64}])
    upload = next(entry["upload_url"] for entry in newer["rules"] if entry["name"] == "review")
    with session_factory.begin() as session:
        project_service.remove_folder(session, _user_id(session_factory),
                                      _machine_id(session_factory), key)
    async with httpx.AsyncClient() as http:
        response = await http.put(upload, content=b"Review with care.\n")
    assert response.status_code == 404
    assert _rules(session_factory, rule_service.rules, project=key) == []


def _machine_id(session_factory):
    with session_factory() as session:
        return session.scalar(select(Machine.machine_id))


async def test_rule_tickets_open_only_their_own_route(server_url, home, session_factory):
    token = await join(server_url)
    await push(server_url, token)
    _rules(session_factory, rule_service.create, "house", OWN, agents=["claude_code"])
    newer = await call(server_url, token, "sync", local={}, rules=[
        {"agent": "claude_code", "place": "every_project", "name": None, "digest": "0" * 64}])
    entry = newer["rules"][0]
    assert entry["action"] == "ask"
    download = entry["download_url"]
    upload = entry["upload_url"]
    skill = await call(server_url, token, "get_skill", name="wizard")
    async with httpx.AsyncClient() as http:
        assert (await http.get(download)).text == OWN
        for wrong in (download.replace("/rule-download/", "/download/"),
                      skill["download_url"].replace("/download/", "/rule-download/")):
            assert (await http.get(wrong)).status_code == 403
        assert (await http.put(upload.replace("/rule-upload/", "/upload/"),
                               content=b"x")).status_code == 403
        assert (await http.put(download.replace("/rule-download/", "/rule-upload/"),
                               content=b"x")).status_code == 403
