"""The sync skill's own listing commands, run on a skill folder that is a git clone."""

import hashlib
import pathlib
import re
import shutil
import subprocess
import sys

import pytest

from aistack.bundled import sync_skill_document

_LAYOUT = {
    "wizard/SKILL.md": "---\nname: wizard\ndescription: x\n---\n",
    "wizard/.github/workflows/ci.yml": "on: push\n",
    "wizard/.git/HEAD": "ref: refs/heads/main\n",
    ".hidden/SKILL.md": "not a skill\n",
    "synced/other/SKILL.md": "Claude Code's own\n",
}
# What push uploads: everything in the skill except its .git.
_EXPECTED = {"wizard/SKILL.md", "wizard/.github/workflows/ci.yml"}


def _block(language: str, marker: str) -> str:
    return next(block for block in re.findall(rf"```{language}\n(.*?)```", sync_skill_document(),
                                              re.S) if marker in block)


def _listed(output: str) -> dict[str, str]:
    lines = (line.split(None, 1) for line in output.splitlines() if line.strip())
    return {path.replace("\\", "/").removeprefix("./"): digest.lower() for digest, path in lines}


@pytest.fixture(name="folder")
def folder_fixture(tmp_path):
    for path, content in _LAYOUT.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(content)
    return tmp_path


def _digests(folder: pathlib.Path) -> dict[str, str]:
    return {path: hashlib.sha256((folder / path).read_bytes()).hexdigest() for path in _EXPECTED}


@pytest.mark.skipif(sys.platform == "win32" or shutil.which("shasum") is None,
                    reason="the bash listing runs where shasum is")
def test_the_bash_listing_leaves_out_only_what_push_leaves_out(folder):
    command = _block("bash", "find -L").replace("<folder>", str(folder))
    output = subprocess.run(["bash", "-c", command], capture_output=True, text=True,
                            check=True).stdout

    assert _listed(output) == _digests(folder)


@pytest.mark.skipif(shutil.which("powershell") is None and shutil.which("pwsh") is None,
                    reason="the PowerShell listing runs on Windows, and where pwsh is")
def test_the_powershell_listing_leaves_out_only_what_push_leaves_out(folder):
    shell = shutil.which("powershell") or shutil.which("pwsh")
    command = _block("powershell", "Get-FileHash").replace("<folder>", str(folder))
    output = subprocess.run([shell, "-NoProfile", "-Command", command], capture_output=True,
                            text=True, check=True).stdout

    assert _listed(output) == _digests(folder)
