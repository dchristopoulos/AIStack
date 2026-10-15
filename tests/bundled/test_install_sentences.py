import re
from pathlib import Path

from aistack.bundled import INSTALL_COMMAND, RUN_COMMAND

ROOT = Path(__file__).parents[2]
BUNDLED = ROOT / "src" / "aistack" / "bundled"

# What a person or their agent is told to run: the README, the operator's guide, and every file
# the package ships. The ADRs record what was true when they were written, and are left alone.
HANDED_OUT = [ROOT / "README.md", ROOT / "docs" / "OPERATING.md",
              *(path for path in BUNDLED.rglob("*") if path.suffix in {".md", ".html"})]

# A run sentence ends at the program's name; an install sentence at the source it installs.
RUN = re.compile(r"uvx\b[^`'\n]*?aistack-mcp\b(?:@\S+)?")
INSTALL = re.compile(r"uv tool install [^`'\s]+")

# The README's one deliberate alternative: unreleased code, straight from this repository.
FROM_THE_REPOSITORY = "uv tool install git+https://github.com/dchristopoulos/AIStack"


def _sentences(pattern):
    # A placeholder such as `uvx --from <wheel>` describes how something was tested; nobody is
    # handed it to run.
    return [(path.relative_to(ROOT).as_posix(), found)
            for path in HANDED_OUT
            for found in pattern.findall(path.read_text(encoding="utf-8"))
            if "<" not in found]


def test_every_run_sentence_uses_the_one_command():
    """Release day changes RUN_COMMAND and this test names every sentence left to follow it."""
    sentences = _sentences(RUN)
    assert {path for path, _ in sentences} >= {"README.md", "src/aistack/bundled/dashboard.html"}
    assert [(path, found) for path, found in sentences if found != RUN_COMMAND] == []


def test_every_install_sentence_uses_the_one_command():
    sentences = _sentences(INSTALL)
    assert {path for path, _ in sentences} >= {"src/aistack/bundled/local/setup.md"}
    assert [(path, found) for path, found in sentences if found not in {INSTALL_COMMAND, FROM_THE_REPOSITORY}] == []
