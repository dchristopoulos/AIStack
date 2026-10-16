"""The sync skill's own listing commands, run on a skill folder that is a git clone."""

import hashlib
import os
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
    # A line without a digest still lists its path, so a failure shows what was printed.
    lines = (line.strip().rpartition("  ") for line in output.splitlines() if line.strip())
    return {path.replace("\\", "/").removeprefix("./"): digest.lower()
            for digest, _, path in lines}


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


@pytest.mark.skipif(sys.platform != "win32", reason="the PowerShell listing is for Windows paths")
def test_the_powershell_listing_leaves_out_only_what_push_leaves_out(folder, tmp_path):
    shell = shutil.which("pwsh") or shutil.which("powershell")
    # Windows PowerShell started from another PowerShell inherits a module path it cannot load
    # its own cmdlets from; a person's shell has its own.
    environment = {name: value for name, value in os.environ.items() if name != "PSModulePath"}
    # From a file, as a person's shell runs it: through -Command, Windows' quoting of the
    # command line mangles the script's double quotes before PowerShell sees them.
    script = tmp_path.parent / f"{tmp_path.name}-listing.ps1"
    script.write_text(_block("powershell", "Get-FileHash").replace("<folder>", str(folder)),
                      encoding="utf-8-sig")
    done = subprocess.run([shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                           str(script)], capture_output=True, text=True, env=environment)

    assert done.returncode == 0, done.stderr
    assert _listed(done.stdout) == _digests(folder), (done.stdout, done.stderr)
