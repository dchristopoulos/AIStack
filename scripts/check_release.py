"""What the tag pipeline checks before it publishes a release, and the notes it publishes.

    python scripts/check_release.py check <version>   # exit 1 with a sentence when it may not
    python scripts/check_release.py notes <version>   # print that release's CHANGELOG section

A release may be published when CHANGELOG.md has a section for it, and when a migration
added since the previous release that older releases cannot run beside (ADR-0024) comes with
a new minor version, so `0.1` never moves to a release that locks the computers on it out.
"""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
CHANGELOG = ROOT / "CHANGELOG.md"
MIGRATIONS = "src/aistack/db/migrations/versions"


def parse(version: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", version)
    if match is None:
        raise ValueError(f"'{version}' is not major.minor.patch")
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def bump_refusal(previous: str | None, current: str, breaking: list[str]) -> str | None:
    """Why `current` may not follow `previous`, or None when it may."""
    if previous is None:
        return None
    before, now = parse(previous), parse(current)
    if now <= before:
        return f"{current} is not newer than the previous release, {previous}."
    if breaking and now[:2] == before[:2]:
        return (f"{', '.join(breaking)} cannot run beside older releases, so the release "
                f"after {previous} that carries it is a new minor version, not {current}.")
    return None


def notes(version: str, changelog: str) -> str | None:
    """The CHANGELOG section for `version`, without its heading, or None."""
    match = re.search(rf"^## {re.escape(version)}\b.*?$\n(.*?)(?=^## |\Z)", changelog,
                      flags=re.MULTILINE | re.DOTALL)
    return match.group(1).strip() if match else None


def _previous_release() -> str | None:
    found = subprocess.run(["git", "describe", "--tags", "--abbrev=0", "--match", "v*",
                            "HEAD^"], cwd=ROOT, capture_output=True, text=True)
    return found.stdout.strip() if found.returncode == 0 else None


def _breaking_since(previous: str) -> list[str]:
    added = subprocess.run(["git", "diff", "--name-only", "--diff-filter=A", previous, "HEAD",
                            "--", f"{MIGRATIONS}/*.py"], cwd=ROOT, capture_output=True,
                           text=True, check=True).stdout.split()
    breaking = []
    for path in added:
        # Every migration declares this (tests/db/test_schema.py), so reading it as text is
        # enough, and needs none of the dependencies a migration imports.
        declared = re.search(r"^older_releases_compatible\s*=\s*(True|False)",
                             (ROOT / path).read_text(encoding="utf-8"), flags=re.MULTILINE)
        if declared is None or declared.group(1) == "False":
            breaking.append(Path(path).name)
    return breaking


def check(version: str) -> str | None:
    if notes(version, CHANGELOG.read_text(encoding="utf-8")) is None:
        return f"CHANGELOG.md has no section '## {version}'. Write the release notes first."
    previous = _previous_release()
    return bump_refusal(previous, version, _breaking_since(previous) if previous else [])


if __name__ == "__main__":
    action, version = sys.argv[1:3]
    if action == "notes":
        section = notes(version, CHANGELOG.read_text(encoding="utf-8"))
        if section is None:
            sys.exit(f"CHANGELOG.md has no section '## {version}'.")
        print(section)
    else:
        refusal = check(version)
        if refusal:
            sys.exit(refusal)
        print(f"{version} may be released.")
