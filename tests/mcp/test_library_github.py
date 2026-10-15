"""ADR-0025 over real git: computers sharing a Library through a repository, a local bare one
standing in for GitHub."""

import contextlib
import os
import pathlib
import shutil
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from sqlalchemy import select

from aistack.bootstrap.configuration.settings.settings_config import LocalSettings
from aistack.bootstrap.context import application_context
from aistack.commons.exceptions import ValidationError
from aistack.db.models.machine import Machine
from aistack.db.models.skill_version import SkillVersion
from aistack.mcp import local_dashboard
from aistack.mcp.local import local_mcp
from aistack.services import library_log
from aistack.services.library_repo import LibraryRepo, RepoUnavailable, validate_repository

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
            assert (pushed["revision"], pushed["shared"]) == (1, False)
        # Back online: the next change carries the earlier one with it.
        _write(home, "review", "Review.")
        assert (await _call(laptop, "push_skill", name="review"))["shared"] is True

    async with computer("desktop") as (desktop, _):
        listed = await _call(desktop, "list_skills")
        assert sorted(skill["name"] for skill in listed["skills"]) == ["review", "wizard"]


async def test_a_new_computer_offline_explains_instead_of_starting_a_second_library(
        computer, repository):
    async with computer("laptop") as (laptop, home):
        _write(home, "wizard", "Cast.")
        await _call(laptop, "push_skill", name="wizard")

    with offline(repository):
        async with computer("desktop") as (desktop, home):
            with pytest.raises(ToolError, match="has not read your Library from GitHub yet"):
                await _call(desktop, "list_skills")
            # A clone that failed leaves nothing that could pass for one that worked.
            assert not (home / ".aistack" / "library").exists()


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
    # A new, empty repository is the usual first computer's: nothing to warn about.
    assert ready.stderr == ""

    unreachable = _check(tmp_path / "desktop",
                         {"AISTACK_LIBRARY_REPO": str(tmp_path / "missing.git")})
    assert unreachable.returncode == 1
    assert "AIStack is not ready" in unreachable.stderr
    assert "has not read your Library from GitHub yet" in unreachable.stderr

    alone = _check(tmp_path / "solo", {})
    assert alone.returncode == 0 and "on this computer only" in alone.stdout


def test_github_is_reached_through_the_gh_login_alone():
    from aistack.services.library_repo import LibraryRepo

    github = LibraryRepo(pathlib.Path("clone"), "maria/aistack-library")
    assert github.remote == "https://github.com/maria/aistack-library.git"
    assert github._credentials[:2] == ["-c", "credential.helper="]
    assert github._credentials[2:3] == ["-c"]
    assert github._credentials[3].startswith("credential.helper=!")
    assert github._credentials[3].endswith(" auth git-credential")
    assert LibraryRepo(pathlib.Path("clone"), "/srv/library.git")._credentials == []


async def test_a_github_library_exports_and_moves_by_copy_and_sync(computer, repository,
                                                                    tmp_path):
    """Leaving GitHub, or arriving there, is export, copy into a skills folder, and sync."""
    import os
    import sys

    async with computer("laptop") as (laptop, home):
        _write(home, "wizard", "Cast.")
        await _call(laptop, "push_skill", name="wizard")

    exported = tmp_path / "exported"
    environment = {**os.environ, "HOME": str(tmp_path / "laptop"),
                   "USERPROFILE": str(tmp_path / "laptop"),
                   "AISTACK_HOME": str(tmp_path / "laptop" / ".aistack"),
                   "AISTACK_LIBRARY_REPO": str(repository)}
    environment.pop("AISTACK_DATABASE_URL", None)
    done = subprocess.run([sys.executable, "-m", "aistack.bootstrap", "export", str(exported)],
                          env=environment, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert (exported / "wizard" / "SKILL.md").read_text().endswith("Cast.\n")

    # A Library of its own elsewhere takes the folders in with one sync.
    other = repository.with_name("other.git")
    subprocess.run(["git", "init", "--quiet", "--bare", str(other)], check=True)
    home = tmp_path / "newplace"
    shutil.copytree(exported / "wizard", home / ".claude" / "skills" / "wizard")
    application_context.build_local_context(LocalSettings(
        aistack_home=home / ".aistack", aistack_library_repo=str(other),
        aistack_username="maria"))
    try:
        async with Client(local_mcp) as client:
            report = await _call(client, "sync")
            assert report["backup"] == ["wizard"]
            await _call(client, "push_skill", name="wizard")
            assert [s["name"] for s in (await _call(client, "list_skills"))["skills"]] == \
                ["wizard"]
    finally:
        application_context.dispose_application_context()


async def test_a_log_from_a_newer_release_is_explained_through_the_agent(computer, repository,
                                                                         tmp_path):
    async with computer("laptop") as (laptop, home):
        _write(home, "wizard", "Cast.")
        await _call(laptop, "push_skill", name="wizard")

    # A newer release on another computer logged a change of a kind this one does not know.
    clone = tmp_path / "newer"
    subprocess.run(["git", "clone", "--quiet", str(repository), str(clone)], check=True)
    _commit_event(clone, library_log.Event(
        uuid.UUID(int=2), _soon(), uuid.UUID(int=1), "skill_renamed", {}))

    async with computer("desktop") as (desktop, _):
        with pytest.raises(ToolError, match="Update AIStack on this computer: run `uv tool upgrade aistack-mcp`"):
            await _call(desktop, "list_skills")


def _soon() -> str:
    """A time after anything a test has logged, as an event spells it."""
    return (datetime.now(UTC) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _commit_event(clone, event, path=None) -> None:
    """Add a file to the repository as somebody with write access to it would."""
    target = clone / "log" / (path or event.path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(event.to_json(), encoding="utf-8")
    _push(clone)


def _push(clone) -> None:
    for command in (["add", "log"], ["-c", "user.name=t", "-c", "user.email=t@t",
                                     "commit", "--quiet", "-m", "newer"], ["push", "--quiet"]):
        subprocess.run(["git", "-C", str(clone), *command], check=True)


async def test_a_computer_starts_offline_and_rebuilds_a_lost_copy_from_its_clone(computer,
                                                                                 repository):
    """A normal start needs no network, and the copy can be deleted at any time (ADR-0025)."""
    async with computer("laptop") as (laptop, home):
        _write(home, "wizard", "Cast.")
        await _call(laptop, "push_skill", name="wizard")
        first = application_context.get_local_principal()

    (home / ".aistack" / "github-copy.db").unlink()
    with offline(repository):
        async with computer("laptop") as (laptop, _):
            listed = await _call(laptop, "list_skills")
            assert [skill["name"] for skill in listed["skills"]] == ["wizard"]
            assert application_context.get_local_principal() == first


async def test_a_file_cannot_speak_for_another_computer(computer, repository, tmp_path):
    """Write access lets anyone add a file; a file outside its computer's folder is refused,
    so nobody's change can be filed somewhere and claim to be theirs."""
    async with computer("laptop") as (laptop, home):
        _write(home, "wizard", "Cast.")
        await _call(laptop, "push_skill", name="wizard")
        with application_context.get_session_factory().begin() as session:
            laptop_id = session.scalar(select(Machine.machine_id))

    clone = tmp_path / "forger"
    subprocess.run(["git", "clone", "--quiet", str(repository), str(clone)], check=True)
    forged = library_log.Event(uuid.uuid4(), _soon(), laptop_id, library_log.SKILL_REMOVED,
                               {"name": "wizard"})
    _commit_event(clone, forged, path=f"{uuid.uuid4()}/{forged.path.split('/')[1]}")

    async with computer("desktop") as (desktop, _):
        with pytest.raises(ToolError, match="is not where its computer writes"):
            await _call(desktop, "list_skills")


@pytest.mark.parametrize("content", [
    b"\xff\xfe not text",
    b"[" * 100_000 + b"]" * 100_000,
    b'{"event_id": "00000000-0000-0000-0000-000000000002"}',
    library_log.Event(uuid.UUID(int=2), "2999-12-31T00:00:00.000000Z", uuid.UUID(int=1),
                      library_log.FOLDER_SYNCED, {}).to_json().encode(),
# Named, because the nested one as an id is 200,000 characters, past what Windows lets pytest
# put in an environment variable.
], ids=["not-utf-8", "nested-too-deep", "missing-fields", "far-future"])
def test_a_bad_file_in_the_log_is_named_not_a_crash(tmp_path, content):
    folder = tmp_path / "clone" / "log" / str(uuid.UUID(int=1))
    folder.mkdir(parents=True)
    (folder / "20260101T000000.000000Z-x.json").write_bytes(content)

    with pytest.raises(ValidationError, match=f"log/{uuid.UUID(int=1)}/20260101T"):
        LibraryRepo(tmp_path / "clone", "maria/aistack-library").events()


def test_a_folder_or_a_link_in_the_log_is_not_read(tmp_path):
    folder = tmp_path / "clone" / "log" / str(uuid.UUID(int=1))
    (folder / "a.json").mkdir(parents=True)
    if sys.platform != "win32":
        (folder / "b.json").symlink_to("/dev/urandom")

    assert LibraryRepo(tmp_path / "clone", "maria/aistack-library").events() == []


@pytest.mark.skipif(sys.platform == "win32", reason="Creating a link needs privileges there.")
def test_a_change_is_never_written_through_a_link_out_of_the_clone(tmp_path, repository):
    repo = LibraryRepo(tmp_path / "clone", str(repository))
    repo.pull()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    event = library_log.Event(uuid.uuid4(), _soon(), uuid.UUID(int=1), library_log.FOLDER_SYNCED,
                              {"harness": "claude"})
    (repo.folder / "log").mkdir()
    (repo.folder / "log" / str(event.machine_id)).symlink_to(elsewhere)

    with pytest.raises(RepoUnavailable, match="outside the clone"):
        repo.publish([event])
    assert list(elsewhere.iterdir()) == []


def test_a_first_start_never_deletes_a_folder_that_holds_files(tmp_path, repository):
    """On a disk that ignores case, AISTACK_HOME=$HOME makes the clone's place ~/Library."""
    kept = tmp_path / "Library" / "Keychains" / "login.keychain-db"
    kept.parent.mkdir(parents=True)
    kept.write_text("keep me")

    with pytest.raises(ValidationError, match="already holds files"):
        LibraryRepo(tmp_path / "Library", str(repository)).pull()
    assert kept.read_text() == "keep me"


def test_git_run_from_a_hook_still_works_on_the_library(tmp_path, repository, monkeypatch):
    """A git hook passes GIT_DIR to the agent it starts; AIStack's git must ignore it."""
    project = tmp_path / "project"
    subprocess.run(["git", "init", "--quiet", str(project)], check=True)
    monkeypatch.setenv("GIT_DIR", str(project / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(project))

    repo = LibraryRepo(tmp_path / "clone", str(repository))
    repo.publish([library_log.Event(uuid.uuid4(), _soon(), uuid.UUID(int=1),
                                    library_log.FOLDER_SYNCED, {"harness": "claude"})])

    environment = {name: value for name, value in os.environ.items()
                   if not name.startswith("GIT_")}
    project_commits = subprocess.run(["git", "-C", str(project), "rev-parse", "--verify",
                                      "--quiet", "HEAD"], env=environment, capture_output=True)
    assert project_commits.returncode != 0
    assert subprocess.run(["git", "--git-dir", str(repository), "log", "--oneline", "main"],
                          env=environment, capture_output=True, text=True,
                          check=True).stdout.strip()
    assert "user.name" not in subprocess.run(
        ["git", "-C", str(project), "config", "--local", "--list"], env=environment,
        capture_output=True, text=True).stdout


@pytest.mark.parametrize("repository", [
    "https://ghp_secret123@github.com/maria/aistack-library.git",
    "https://maria:ghp_secret123@github.com/maria/aistack-library.git",
    "ssh://git:ghp_secret123@github.com/maria/aistack-library.git",
    "--upload-pack=touch /tmp/owned",
])
def test_a_repository_with_a_credential_or_an_option_is_refused_unrepeated(repository):
    with pytest.raises(ValidationError) as refused:
        validate_repository(repository)
    assert "ghp_secret123" not in refused.value.message
    assert "upload-pack" not in refused.value.message


@contextlib.contextmanager
def clock_ahead(monkeypatch, offset: timedelta):
    """This computer's clock runs `offset` ahead, as a VM's can after sleep."""
    class Ahead(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(tz) + offset

    with monkeypatch.context() as patched:
        patched.setattr(library_log, "datetime", Ahead)
        yield


def _latest() -> tuple[int, str]:
    return _revisions()[-1]


async def test_a_computer_whose_clock_runs_ahead_does_not_win_over_a_newer_edit(
        computer, repository, monkeypatch):
    """ENT-03: an edit made after another computer's change sorts after it, whatever the clocks
    say, so every copy, and one rebuilt from the log, keeps the newer edit."""
    with clock_ahead(monkeypatch, timedelta(hours=1)):
        async with computer("laptop") as (laptop, home):
            _write(home, "wizard", "Written on the laptop.")
            await _call(laptop, "push_skill", name="wizard")

    async with computer("desktop") as (desktop, home):
        await _call(desktop, "sync")
        _write(home, "wizard", "Edited later on the desktop.")
        edited = await _call(desktop, "push_skill", name="wizard")
        assert edited["revision"] == 2
        newest = _latest()

    with clock_ahead(monkeypatch, timedelta(hours=1)):
        async with computer("laptop") as (laptop, _):
            await _call(laptop, "sync")
            assert _latest() == newest
    async with computer("phone"):
        application_context.library_before_read(force=True)
        assert _latest() == newest

    (repository.parent / "desktop" / ".aistack" / "github-copy.db").unlink()
    async with computer("desktop") as (desktop, home):
        assert _latest() == newest
        report = await _call(desktop, "sync")
        assert (report["update"], report["ask"]) == ([], [])


def test_terminal_commands_find_the_library_the_agent_was_set_up_with(tmp_path, repository):
    """AUTO-03: without the agent's settings, check and export used to open a new, empty
    Library on this computer and report success."""
    import os
    import sys

    home = tmp_path / "laptop"
    assert _check(home, {"AISTACK_LIBRARY_REPO": str(repository)}).returncode == 0

    alone = _check(home, {"AISTACK_LIBRARY_REPO": ""})
    assert alone.returncode == 0, alone.stderr
    assert f"in the GitHub repository {repository}" in alone.stdout
    environment = {**os.environ, "HOME": str(home), "USERPROFILE": str(home),
                   "AISTACK_HOME": str(home / ".aistack")}
    for variable in ("AISTACK_DATABASE_URL", "AISTACK_LIBRARY_REPO"):
        environment.pop(variable, None)
    exported = subprocess.run([sys.executable, "-m", "aistack.bootstrap", "export",
                               str(tmp_path / "exported")], env=environment,
                              capture_output=True, text=True)
    assert exported.returncode == 0, exported.stderr
    assert not (home / ".aistack" / "aistack.db").exists()

    other = subprocess.run([sys.executable, "-m", "aistack.bootstrap", "export",
                            str(tmp_path / "other")],
                           env={**environment, "AISTACK_LIBRARY_REPO": "maria/other"},
                           capture_output=True, text=True)
    assert other.returncode == 1
    assert str(repository) in other.stderr and "maria/other" in other.stderr


def test_export_with_no_library_anywhere_creates_none(tmp_path):
    """PH-14: it used to make an empty Library here and report 'Exported 0 skills'."""
    import os
    import sys

    home = tmp_path / "fresh"
    environment = {**os.environ, "HOME": str(home), "USERPROFILE": str(home),
                   "AISTACK_HOME": str(home / ".aistack")}
    for variable in ("AISTACK_DATABASE_URL", "AISTACK_LIBRARY_REPO"):
        environment.pop(variable, None)
    refused = subprocess.run([sys.executable, "-m", "aistack.bootstrap", "export",
                              str(tmp_path / "exported")], env=environment,
                             capture_output=True, text=True)

    assert refused.returncode == 1
    assert "There is no Library on this computer to export" in refused.stderr
    assert not (home / ".aistack").exists() and not (tmp_path / "exported").exists()
