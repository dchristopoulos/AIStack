"""ADR-0025 over real git: computers sharing a Library through a repository, a local bare one
standing in for GitHub."""

import contextlib
import shutil
import subprocess

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from sqlalchemy import select

from aistack.bootstrap.configuration.settings.settings_config import LocalSettings
from aistack.bootstrap.context import application_context
from aistack.db.models.machine import Machine
from aistack.db.models.skill_version import SkillVersion
from aistack.mcp import local_dashboard
from aistack.mcp.local import local_mcp

pytestmark = pytest.mark.anyio


@pytest.fixture(name="anyio_backend")
def anyio_backend_fixture():
    return "asyncio"


@pytest.fixture(name="repository")
def repository_fixture(tmp_path):
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--quiet", "--bare", str(remote)], check=True)
    return remote


@pytest.fixture(name="computer")
def computer_fixture(tmp_path, monkeypatch, repository):
    @contextlib.asynccontextmanager
    async def computer(name: str):
        home = tmp_path / name
        home.mkdir(exist_ok=True)
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setenv("USERPROFILE", str(home))
        application_context.build_local_context(LocalSettings(
            aistack_home=home / ".aistack", aistack_library_repo=str(repository),
            aistack_username="maria"))
        try:
            async with Client(local_mcp) as client:
                yield client, home
        finally:
            local_dashboard.stop_dashboard()
            application_context.dispose_application_context()

    return computer


@contextlib.contextmanager
def offline(repository):
    """The repository out of reach, as without network, then back."""
    away = repository.with_name("away.git")
    shutil.move(repository, away)
    try:
        yield
    finally:
        shutil.move(away, repository)


def _write(home, name, body):
    folder = home / ".claude" / "skills" / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {name}.\n---\n\n{body}\n")
    return folder


async def _call(client, tool, **arguments):
    return (await client.call_tool(tool, arguments)).structured_content


def _revisions() -> list[tuple[int, str]]:
    with application_context.get_session_factory().begin() as session:
        return sorted(session.execute(select(SkillVersion.revision,
                                             SkillVersion.content_hash)).all())


async def test_a_skill_backed_up_on_one_computer_installs_on_another(computer, repository):
    async with computer("laptop") as (laptop, home):
        original = _write(home, "wizard", "Cast.")
        await _call(laptop, "push_skill", name="wizard")

    async with computer("desktop") as (desktop, home):
        listed = await _call(desktop, "list_skills")
        assert [skill["name"] for skill in listed["skills"]] == ["wizard"]
        installed = await _call(desktop, "get_skill", name="wizard")
        assert (home / ".claude" / "skills" / "wizard" / "SKILL.md").read_bytes() == \
            (original / "SKILL.md").read_bytes()
        assert installed["revision"] == 1

    async with computer("laptop"):
        application_context.library_before_read(force=True)
        with application_context.get_session_factory().begin() as session:
            assert len(session.scalars(select(Machine)).all()) == 2

    log = subprocess.run(["git", "--git-dir", str(repository), "ls-tree", "-r", "--name-only",
                          "main"], capture_output=True, text=True, check=True).stdout.split()
    assert log and all(path.startswith("log/") and ":" not in path for path in log)


async def test_changes_made_offline_go_out_with_the_next_push(computer, repository):
    async with computer("laptop") as (laptop, home):
        _write(home, "wizard", "Cast.")
        with offline(repository):
            pushed = await _call(laptop, "push_skill", name="wizard")
            assert pushed["revision"] == 1
        # Back online: the next change carries the earlier one with it.
        _write(home, "review", "Review.")
        await _call(laptop, "push_skill", name="review")

    async with computer("desktop") as (desktop, _):
        listed = await _call(desktop, "list_skills")
        assert sorted(skill["name"] for skill in listed["skills"]) == ["review", "wizard"]


async def test_a_new_computer_offline_explains_instead_of_starting_a_second_library(
        computer, repository):
    async with computer("laptop") as (laptop, home):
        _write(home, "wizard", "Cast.")
        await _call(laptop, "push_skill", name="wizard")

    with offline(repository):
        async with computer("desktop") as (desktop, _):
            with pytest.raises(ToolError, match="has not read your Library from GitHub yet"):
                await _call(desktop, "list_skills")


async def test_computers_that_edited_one_skill_offline_agree_once_back(computer, repository):
    async with computer("laptop") as (laptop, home):
        _write(home, "wizard", "First.")
        await _call(laptop, "push_skill", name="wizard")
    async with computer("desktop") as (desktop, home):
        await _call(desktop, "sync")

    with offline(repository):
        async with computer("laptop") as (laptop, home):
            _write(home, "wizard", "Edited on the laptop.")
            await _call(laptop, "push_skill", name="wizard")
        async with computer("desktop") as (desktop, home):
            _write(home, "wizard", "Edited on the desktop.")
            await _call(desktop, "push_skill", name="wizard")

    seen = {}
    for name in ("laptop", "desktop", "laptop"):
        async with computer(name) as (client, _):
            await _call(client, "sync")
            seen[name] = _revisions()

    assert seen["laptop"] == seen["desktop"]
    assert [revision for revision, _ in seen["laptop"]] == [1, 2, 3]


def _check(home, environment_extra):
    import os
    import sys
    environment = {**os.environ, "HOME": str(home), "USERPROFILE": str(home),
                   "AISTACK_HOME": str(home / ".aistack"), **environment_extra}
    environment.pop("AISTACK_DATABASE_URL", None)
    return subprocess.run([sys.executable, "-m", "aistack.bootstrap", "check"],
                          env=environment, capture_output=True, text=True)


def test_check_says_where_the_library_lives_or_what_is_wrong(tmp_path, repository):
    ready = _check(tmp_path / "laptop", {"AISTACK_LIBRARY_REPO": str(repository)})
    assert ready.returncode == 0, ready.stderr
    assert f"in the GitHub repository {repository}" in ready.stdout

    unreachable = _check(tmp_path / "desktop",
                         {"AISTACK_LIBRARY_REPO": str(tmp_path / "missing.git")})
    assert unreachable.returncode == 1
    assert "AIStack is not ready" in unreachable.stderr
    assert "has not read your Library from GitHub yet" in unreachable.stderr

    alone = _check(tmp_path / "solo", {})
    assert alone.returncode == 0 and "on this computer only" in alone.stdout
