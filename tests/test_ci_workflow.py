import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

WORKFLOW = Path(__file__).parents[1] / ".github" / "workflows" / "tests.yaml"
PUBLISHING = {"publish", "pypi"}
# Writes the GitHub Release once the package is out; it publishes nothing that runs.
RELEASE_NOTES = "release"
# External service contracts run weekly and do not gate a release.
CONTRACT_TESTS = {"github-contract"}


class _StrictLoader(yaml.SafeLoader):
    """GitHub rejects a key given twice in one mapping; PyYAML silently keeps the last."""

    def construct_mapping(self, node, deep=False):
        keys = [self.construct_object(key, deep=deep) for key, _ in node.value]
        duplicates = {key for key in keys if keys.count(key) > 1}
        if duplicates:
            raise yaml.constructor.ConstructorError(None, None, f"duplicate keys {duplicates}", node.start_mark)
        return super().construct_mapping(node, deep=deep)


def _workflow():
    return yaml.load(WORKFLOW.read_text(), Loader=_StrictLoader)


def test_publishing_waits_for_every_merge_gate_test_job():
    """Every merge-gate test must pass before a package or image can be published."""
    jobs = _workflow()["jobs"]
    tests = set(jobs) - PUBLISHING - {RELEASE_NOTES} - CONTRACT_TESTS
    for name in PUBLISHING:
        assert set(jobs[name]["needs"]) == tests, name
    assert jobs[RELEASE_NOTES]["needs"] == ["pypi"]


@pytest.mark.parametrize("job", sorted(PUBLISHING))
def test_a_tag_publishes_only_a_commit_on_main_that_may_be_released(job):
    """The image and the package each check the tag themselves: either reaches every user."""
    steps = _workflow()["jobs"][job]["steps"]
    checks = "\n".join(step.get("run", "") for step in steps
                       if step.get("if", "startsWith(github.ref, 'refs/tags/v')")
                       == "startsWith(github.ref, 'refs/tags/v')")
    assert steps[0]["with"]["fetch-depth"] == 0
    assert 'test "$GITHUB_REF_NAME" = "v$(poetry version -s)"' in checks
    assert 'git merge-base --is-ancestor "$GITHUB_SHA" origin/main' in checks
    assert 'python scripts/check_release.py check "$(poetry version -s)"' in checks


def test_every_action_is_pinned_by_commit():
    """A tag or a branch can be moved to other code by whoever controls it, and the jobs that
    publish hold the credentials to ship that code to every user."""
    steps = [step for job in _workflow()["jobs"].values()
             for step in job["steps"] if "uses" in step]
    assert steps
    unpinned = [step["uses"] for step in steps
                if not re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", step["uses"])]
    assert unpinned == []


def test_jobs_read_the_repository_and_nothing_else_by_default():
    assert _workflow()["permissions"] == {"contents": "read"}


@pytest.mark.parametrize("job", ["suite", "browser-tests"])
def test_the_shards_cover_every_test(job):
    """The shards are k/n for every k up to one n, or some tests run in no job at all."""
    shards = _workflow()["jobs"][job]["strategy"]["matrix"]["shard"]
    n = len(shards)
    assert sorted(shards) == [f"{k}/{n}" for k in range(1, n + 1)]


def test_the_real_github_contract_uses_credentials_only_on_its_weekly_schedule():
    job = _workflow()["jobs"]["github-contract"]
    assert job["if"] == "github.event_name == 'schedule'"
    assert job["steps"][-1]["env"]["GH_TOKEN"] == "${{ secrets.AISTACK_E2E_GITHUB_TOKEN }}"
    assert job["steps"][-1]["if"] == "steps.configuration.outputs.configured == 'true'"


@pytest.mark.skipif(sys.platform == "win32", reason="The scheduled job runs in a Linux shell.")
@pytest.mark.parametrize("repository,token", [("", ""), ("owner/sandbox", ""), ("", "sentinel-credential"),
                                             ("owner/sandbox", "sentinel-credential")])
def test_the_github_contract_skips_until_both_repository_and_token_are_set(
        tmp_path, repository, token):
    script = _workflow()["jobs"]["github-contract"]["steps"][0]["run"]
    output = tmp_path / "output"
    summary = tmp_path / "summary"
    completed = subprocess.run(
        ["bash", "-e", "-c", script],
        env={
            "PATH": os.environ.get("PATH", ""),
            "AISTACK_E2E_GITHUB_REPO": repository,
            "TEST_TOKEN": token,
            "GITHUB_OUTPUT": str(output),
            "GITHUB_STEP_SUMMARY": str(summary),
        },
        capture_output=True,
        text=True,
        check=True,
    )
    configured = bool(repository and token)
    assert output.read_text().strip() == f"configured={str(configured).lower()}"
    summary_text = summary.read_text() if summary.exists() else ""
    if not configured:
        assert "Skipping the real-GitHub contract test" in summary_text
    assert "sentinel-credential" not in completed.stdout + completed.stderr + summary_text
