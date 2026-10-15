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


def _version():
    return tomllib.loads(PYPROJECT.read_text())["project"]["version"]


def _check_release():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "check_release", PYPROJECT.parent / "scripts" / "check_release.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_release_that_older_ones_cannot_run_beside_is_a_new_minor():
    check = _check_release()
    assert check.bump_refusal(None, "0.1.0", []) is None
    assert check.bump_refusal("v0.1.0", "0.1.1", []) is None
    assert check.bump_refusal("v0.1.0", "0.2.0", ["0012_reshape.py"]) is None
    assert "new minor version" in check.bump_refusal("v0.1.0", "0.1.1", ["0012_reshape.py"])
    assert "not newer" in check.bump_refusal("v0.1.1", "0.1.1", [])


def test_the_version_being_released_has_its_notes():
    """Setting the version is cutting a release, and the tag pipeline publishes these notes."""
    check = _check_release()
    changelog = (PYPROJECT.parent / "CHANGELOG.md").read_text(encoding="utf-8")
    assert check.notes(_version(), changelog), f"CHANGELOG.md has no section for {_version()}"


def test_every_command_runs_the_current_minor_of_the_image():
    """`0.1` stays on releases that work beside each other; a breaking release starts a new
    minor, and the commands people copy move to it in the same change as the version."""
    major, minor, _ = _version().split(".")
    channel = f"{major}.{minor}"
    root = PYPROJECT.parent
    texts = [root / "README.md", root / "compose.yaml", root / "docs" / "OPERATING.md",
             *(root / "src" / "aistack" / "bundled").rglob("*.md")]
    tags = [(path.name, tag) for path in texts
            for tag in re.findall(r"ghcr\.io/dchristopoulos/aistack:([^\s`'\"\\]+)",
                                  path.read_text(encoding="utf-8"))
            if not tag.startswith("<")]
    assert tags, "no image commands found"
    assert [(name, tag) for name, tag in tags if tag not in (channel, "edge")] == []
