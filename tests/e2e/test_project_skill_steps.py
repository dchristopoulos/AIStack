"""The sync skill's git steps for a project folder, run as written against a real repository
with a linked worktree (ADR-0026). The skill holds the rule that AIStack touches only what
git ignores, so its own commands are what is tested, not a copy of them."""

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from aistack.bundled import sync_skill_document

pytestmark = pytest.mark.skipif(sys.platform == "win32" or shutil.which("git") is None,
                                reason="The skill's bash steps need git and a POSIX shell.")

FOLDER = ".claude/skills"


def _section(heading: str) -> str:
    document = sync_skill_document()
    start = document.index(heading)
    end = document.find("\n### ", start + len(heading))
    return document[start:] if end == -1 else document[start:end]


def _blocks(heading: str) -> list[str]:
    return re.findall(r"```bash\n(.*?)```", _section(heading), flags=re.S)


def _run(script: str, top: Path, name: str = "") -> str:
    filled = (script.replace("<top>", str(top)).replace("<folder>", FOLDER)
              .replace("<name>", name))
    # Each line as the agent runs it: one command, nothing chained across lines.
    return subprocess.run(["bash", "-c", filled], check=True, capture_output=True,
                          text=True).stdout


def _git(top: Path, *arguments: str) -> str:
    return subprocess.run(["git", "-C", str(top), *arguments], check=True,
                          capture_output=True, text=True).stdout


def _skill(folder: Path, name: str) -> None:
    (folder / name).mkdir(parents=True)
    (folder / name / "SKILL.md").write_text(f"---\nname: {name}\ndescription: x\n---\n")


@pytest.fixture(name="repository")
def repository_fixture(tmp_path):
    """A clone with a skill git tracks and one git would commit, and a linked worktree."""
    top = tmp_path / "aistack"
    top.mkdir()
    _git(top, "init", "-q")
    _git(top, "config", "user.email", "test@example.com")
    _git(top, "config", "user.name", "Test")
    _skill(top / FOLDER, "conventions")
    _git(top, "add", ".")
    _git(top, "commit", "-q", "-m", "A skill the repository shares")
    _skill(top / FOLDER, "drafted")
    _git(top, "worktree", "add", "-q", str(tmp_path / "worktree"))
    return top, tmp_path / "worktree"


def _state(top: Path) -> tuple[str, str]:
    return _git(top, "status", "--porcelain"), _git(top, "diff")


def test_the_three_listings_tell_the_repositorys_folders_from_the_users(repository):
    top, _ = repository
    _skill(top / FOLDER, "mine")
    _run("excl=$(git -C <top> rev-parse --path-format=absolute --git-path info/exclude)\n"
         "echo '/<folder>/mine/' >> \"$excl\"", top)

    tracked, would_commit, ignored = [
        _run(line, top) for line in _blocks("### Sync its folders")[0].strip().splitlines()]

    assert "conventions/SKILL.md" in tracked
    assert would_commit.strip() == f"{FOLDER}/drafted/"
    assert ignored.strip() == f"{FOLDER}/mine/"


def test_an_install_and_a_removal_leave_the_repository_as_it_was(repository):
    top, worktree = repository
    before, worktree_before = _state(top), _state(worktree)
    guard = _blocks("### Install into a project")[0]

    # Twice: the exclude lines are written once.
    for _ in range(2):
        checked = _run(guard, top, "wizard")
    staged = top / FOLDER / ".aistack-staging"
    _skill(staged, "wizard")
    (staged / "wizard").rename(top / FOLDER / "wizard")

    assert checked.strip() == "ignored"
    assert _state(top) == before
    exclude = Path(_run("git -C <top> rev-parse --path-format=absolute --git-path info/exclude",
                        top).strip()).read_text()
    assert exclude.count(f"/{FOLDER}/wizard/") == 1
    assert exclude.count(f"/{FOLDER}/.aistack-staging/") == 1
    # The worktree shares the clone's exclude file, so the folder is ignored there too.
    _skill(worktree / FOLDER, "wizard")
    assert _state(worktree) == worktree_before

    assert _git(top, "ls-files", "--", f"{FOLDER}/wizard") == ""
    _git(top, "check-ignore", "-q", f"{FOLDER}/wizard/")
    shutil.rmtree(top / FOLDER / "wizard")
    assert _state(top) == before


def test_the_guard_refuses_a_folder_the_repository_holds(repository):
    top, _ = repository

    checked = subprocess.run(
        ["bash", "-c", _blocks("### Install into a project")[0].replace("<top>", str(top))
         .replace("<folder>", FOLDER).replace("<name>", "conventions")],
        capture_output=True, text=True)

    # Tracked: ls-files lists it, and git does not ignore what it tracks.
    assert "conventions/SKILL.md" in checked.stdout
    assert "ignored" not in checked.stdout


def test_a_remote_loses_its_credentials_before_it_leaves_the_computer(repository):
    top, _ = repository
    _git(top, "remote", "add", "origin",
         "https://x-access-token:ghs_secret@github.com/dchristopoulos/AIStack.git")

    printed = _run(_blocks("### Find the repository")[1].replace("<remote>", "origin"), top)

    assert printed.strip() == "https://github.com/dchristopoulos/AIStack.git"
