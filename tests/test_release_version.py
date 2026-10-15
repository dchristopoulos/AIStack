import re
import tomllib
from pathlib import Path

PYPROJECT = Path(__file__).parents[1] / "pyproject.toml"


def test_the_version_stays_below_one_and_has_no_suffix():
    """AGENTS.md: the version never reaches 1.0.0, and a release is plain major.minor.patch."""
    version = tomllib.loads(PYPROJECT.read_text())["project"]["version"]
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", version)
    assert match, f"'{version}' is not plain major.minor.patch"
    assert int(match.group(1)) == 0, f"'{version}' reached 1.0.0"
