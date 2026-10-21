"""`aistack project add` and the edits made on the page, over real HTTP, in a temporary
repository with a bare remote and a fake `gh` (ADR-0036, ADR-0038)."""

import os
import stat
import subprocess

import pytest
from sqlalchemy import select

from aistack.db.models.machine import Machine
from aistack.db.models.machine_project import MachineProject
from aistack.db.models.project import Project
from aistack.db.models.project_file import ProjectFile, ProjectFileEdit
from aistack.db.models.user import User
from aistack.services import project_file_service, repository_work, server_sync
from aistack.services.content_hash import text_hash
from aistack.services.server_connection import Connection
from tests.mcp.conftest import call, join

pytestmark = pytest.mark.anyio

AGENTS = "# Shop\n\nRun the tests before committing.\n"
EDITED = AGENTS + "Money is an integer number of cents.\n"


def _git(top, *arguments):
    return subprocess.run(["git", "-C", str(top), "-c", "user.name=t",
                           "-c", "user.email=t@example.com", *arguments], check=True,
                          capture_output=True, text=True).stdout


@pytest.fixture
def home(tmp_path, monkeypatch):
    from aistack.services import hardware
    monkeypatch.setattr(hardware, "hardware_id", lambda: "project-file-test-computer")
    monkeypatch.delenv("CODEX_HOME", raising=False)
    home = tmp_path / "home"
    (home / ".claude" / "skills").mkdir(parents=True)
    return home


@pytest.fixture
def remote(tmp_path):
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    return bare


@pytest.fixture
def repository(tmp_path, remote, monkeypatch):
    # Commits made by the program use the person's own identity.
    for name, value in (("GIT_AUTHOR_NAME", "t"), ("GIT_AUTHOR_EMAIL", "t@example.com"),
                        ("GIT_COMMITTER_NAME", "t"), ("GIT_COMMITTER_EMAIL", "t@example.com")):
        monkeypatch.setenv(name, value)
    top = tmp_path / "shop"
    top.mkdir()
    _git(top, "init", "-q", "-b", "main")
    files = {"AGENTS.md": AGENTS, "CLAUDE.md": "Read AGENTS.md.\n", "README.md": "# Shop\n",
             "docs/guide.md": "A guide.\n", "src/app.py": "print()\n"}
    for path, text in files.items():
        (top / path).parent.mkdir(parents=True, exist_ok=True)
        (top / path).write_text(text)
    _git(top, "add", ".")
    _git(top, "commit", "-qm", "init")
    _git(top, "remote", "add", "origin", str(remote))
    _git(top, "push", "-qu", "origin", "main")
    return top


@pytest.fixture
def gh(tmp_path, monkeypatch):
    """A `gh` that is signed in, records what it was asked, and prints a pull request."""
    folder = tmp_path / "bin"
    folder.mkdir()
    log = tmp_path / "gh.log"
    script = folder / "gh"
    script.write_text("#!/bin/sh\n"
                      f"printf '%s\\n' \"$@\" >> '{log}'\n"
                      'if [ "$1" = pr ]; then echo https://github.com/shop/shop/pull/7; fi\n')
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{folder}{os.pathsep}{os.environ['PATH']}")
    return log


@pytest.fixture
def no_gh(monkeypatch):
    monkeypatch.setattr(repository_work.shutil, "which", lambda name: None)


async def _sync(server_url, token, home, top, add=False, **choices):
    reports = await server_sync.sync_computer(
        Connection(server_url, token), home, top, choices or None,
        add_files=repository_work.markdown_files(top) if add else None)
    return reports, server_sync.output(reports)


def _rows(session_factory):
    with session_factory() as session:
        return {row.path: row for row in session.scalars(select(ProjectFile))}


def _me(session_factory):
    with session_factory() as session:
        user_id = session.scalar(select(User.user_id).where(User.username == "dimitris"))
        machine_id = session.scalar(select(Machine.machine_id).where(Machine.user_id == user_id))
        key = session.scalar(select(Project.key).where(Project.user_id == user_id))
        return user_id, machine_id, key


def _save_edit(session_factory, text, path="AGENTS.md"):
    user_id, machine_id, key = _me(session_factory)
    base = _rows(session_factory)[path].content_hash
    with session_factory.begin() as session:
        saved = project_file_service.save_edit(session, user_id, key, path, text, base,
                                               str(machine_id))
    assert saved.saved


def _commit(session_factory, note, path="AGENTS.md"):
    user_id, _, key = _me(session_factory)
    with session_factory.begin() as session:
        project_file_service.commit(session, user_id, key, path, note)


def _edits(session_factory):
    with session_factory() as session:
        return list(session.scalars(select(ProjectFileEdit).order_by(ProjectFileEdit.created_on)))


async def test_adding_a_project_lists_its_markdown_with_the_agent_files_ticked(
        server_url, home, repository, session_factory, no_gh):
    token = await join(server_url)

    listed = repository_work.markdown_files(repository)
    _, output = await _sync(server_url, token, home, repository, add=True)

    assert listed == [{"path": "AGENTS.md", "size": len(AGENTS)},
                      {"path": "CLAUDE.md", "size": 16}, {"path": "README.md", "size": 7},
                      {"path": "docs/guide.md", "size": 9}]
    rows = _rows(session_factory)
    assert {path: (row.ticked, row.agent and row.agent.value) for path, row in rows.items()} == {
        "AGENTS.md": (True, "codex"), "CLAUDE.md": (True, "claude_code"),
        "README.md": (False, None), "docs/guide.md": (False, None)}
    with session_factory() as session:
        assert session.scalar(select(MachineProject.path)) == str(repository.resolve())

    # The same sync sends the ticked files' text, and only theirs, once.
    rows = _rows(session_factory)
    assert rows["AGENTS.md"].text == AGENTS and rows["AGENTS.md"].content_hash == text_hash(AGENTS)
    assert rows["README.md"].text is None
    assert "Sent the current text of AGENTS.md to the page." in output
    _, output = await _sync(server_url, token, home, repository)
    assert "Sent the current text" not in output


async def test_an_edit_is_written_only_over_the_text_it_started_from(
        server_url, home, repository, session_factory, no_gh):
    token = await join(server_url)
    await _sync(server_url, token, home, repository, add=True)
    await _sync(server_url, token, home, repository)

    _save_edit(session_factory, EDITED)
    _, output = await _sync(server_url, token, home, repository)
    assert (repository / "AGENTS.md").read_text() == EDITED
    assert "Wrote the edit of AGENTS.md from the page" in output
    assert _edits(session_factory)[-1].written_on is not None
    # Written into the working copy the person asked for, and nothing committed.
    assert _git(repository, "status", "--porcelain") == " M AGENTS.md\n"

    # Changed here after the page read it: the edit waits for an answer.
    await _sync(server_url, token, home, repository)
    _save_edit(session_factory, EDITED + "Second.\n")
    (repository / "AGENTS.md").write_text("Changed here.\n")
    reports, output = await _sync(server_url, token, home, repository)
    assert (repository / "AGENTS.md").read_text() == "Changed here.\n"
    question = next(report for report in reports if report.get("rules"))["edit_questions"][0]
    assert question["key"] == "repository:AGENTS.md"
    assert "--rule-choice" in output and "/transfer/" not in output
    assert _edits(session_factory)[-1].written_on is None

    await _sync(server_url, token, home, repository, **{"repository:AGENTS.md": "write"})
    assert (repository / "AGENTS.md").read_text() == EDITED + "Second.\n"


async def test_a_stale_edit_can_be_cancelled_from_the_computer(server_url, home, repository,
                                                               session_factory, no_gh):
    token = await join(server_url)
    await _sync(server_url, token, home, repository, add=True)
    await _sync(server_url, token, home, repository)
    _save_edit(session_factory, EDITED)
    (repository / "AGENTS.md").write_text("Changed here.\n")

    await _sync(server_url, token, home, repository, **{"repository:AGENTS.md": "cancel"})

    assert (repository / "AGENTS.md").read_text() == "Changed here.\n"
    assert _edits(session_factory)[-1].cancelled_on is not None


def _state(top):
    return (_git(top, "rev-parse", "HEAD"), _git(top, "symbolic-ref", "HEAD"),
            _git(top, "status", "--porcelain"), _git(top, "diff", "--cached"),
            _git(top, "for-each-ref", "refs/heads"))


async def test_sharing_pushes_a_branch_holding_only_that_file(server_url, home, repository,
                                                              remote, session_factory, gh):
    token = await join(server_url)
    await _sync(server_url, token, home, repository, add=True)
    await _sync(server_url, token, home, repository)
    _save_edit(session_factory, EDITED)
    await _sync(server_url, token, home, repository)
    upstream = _git(repository, "rev-parse", "origin/main").strip()

    # Other work in progress, staged and not, and a local commit not yet pushed.
    (repository / "src/app.py").write_text("print('wip')\n")
    (repository / "README.md").write_text("# Shop, staged\n")
    _git(repository, "add", "README.md")
    (repository / "docs/guide.md").write_text("A guide, committed locally.\n")
    _git(repository, "commit", "-qm", "local work", "--", "docs/guide.md")
    before = _state(repository)

    _commit(session_factory, "Say how money is stored\n\nThe API had floats once.")
    _, output = await _sync(server_url, token, home, repository)

    assert _state(repository) == before
    branches = _git(remote, "for-each-ref", "--format=%(refname:short)", "refs/heads")
    branch = next(line for line in branches.split() if line.startswith("aistack/"))
    assert branch.startswith("aistack/agents-md-")
    assert _git(remote, "rev-parse", f"{branch}^").strip() == upstream
    assert _git(remote, "diff", "--name-only", upstream, branch) == "AGENTS.md\n"
    assert _git(remote, "show", f"{branch}:AGENTS.md") == EDITED
    assert _git(remote, "log", "-1", "--format=%s%n%n%b", branch).strip() == (
        "Say how money is stored\n\nThe API had floats once.")
    assert _git(remote, "rev-parse", "main").strip() == upstream
    asked = gh.read_text().split("\n")
    assert asked[asked.index("create") - 1:asked.index("create") + 1] == ["pr", "create"]
    assert asked[asked.index("--head") + 1] == branch
    assert asked[asked.index("--base") + 1] == "main"
    assert asked[asked.index("--title") + 1] == "Say how money is stored"
    assert "https://github.com/shop/shop/pull/7" in output
    edit = _edits(session_factory)[-1]
    assert edit.shared_on is not None
    assert edit.pull_request_url == "https://github.com/shop/shop/pull/7"

    # Shared once: the next sync has nothing to share.
    _, output = await _sync(server_url, token, home, repository)
    assert "Shared" not in output


async def test_without_gh_the_branch_is_pushed_and_the_person_told(server_url, home,
                                                                   repository, remote,
                                                                   session_factory, no_gh):
    token = await join(server_url)
    await _sync(server_url, token, home, repository, add=True)
    await _sync(server_url, token, home, repository)
    _save_edit(session_factory, EDITED)
    await _sync(server_url, token, home, repository)
    _commit(session_factory, "Say how money is stored")

    _, output = await _sync(server_url, token, home, repository)

    assert "Pushed the edit of AGENTS.md to branch aistack/agents-md-" in output
    assert "aistack/agents-md-" in _git(remote, "for-each-ref", "refs/heads")
    assert _edits(session_factory)[-1].shared_on is not None


async def test_an_edit_for_a_file_git_does_not_track_is_never_written(server_url, home,
                                                                      repository,
                                                                      session_factory, no_gh):
    token = await join(server_url)
    await _sync(server_url, token, home, repository, add=True)
    await _sync(server_url, token, home, repository)
    _save_edit(session_factory, EDITED)
    _git(repository, "rm", "-q", "--cached", "AGENTS.md")
    (repository / "AGENTS.md").write_text(AGENTS)

    _, output = await _sync(server_url, token, home, repository)

    assert (repository / "AGENTS.md").read_text() == AGENTS
    assert "git does not track AGENTS.md" in output


def test_the_program_refuses_a_path_outside_the_project(repository, tmp_path):
    outside = tmp_path / "outside.md"
    outside.write_text("x")
    (repository / "linked.md").symlink_to(outside)
    _git(repository, "add", "linked.md")
    tracked = repository_work._tracked(repository)

    for path in ("../outside.md", "/etc/hosts", "docs/../../outside.md", "linked.md",
                 "src/app.py\nAGENTS.md"):
        with pytest.raises(Exception, match="outside the project|path inside|not track"):
            repository_work._tracked_file(repository, path, tracked)
    assert "linked.md" not in [file["path"] for file in repository_work.markdown_files(
        repository)]


async def test_an_older_program_sends_no_listing_and_sees_no_work(server_url, home,
                                                                   repository):
    token = await join(server_url)
    here = {"path": str(repository), "remote": None}
    first = await call(server_url, token, "sync", local={}, here=here)
    key = first["project"]["key"]
    older = await call(server_url, token, "sync", local={}, here=here, project=key)
    assert "ticked_files" not in older and "edits" not in older
