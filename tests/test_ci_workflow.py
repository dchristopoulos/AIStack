import re
from pathlib import Path

import yaml

WORKFLOW = Path(__file__).parents[1] / ".github" / "workflows" / "tests.yaml"
PUBLISHING = {"publish", "pypi"}


def test_publishing_waits_for_every_test_job():
    """An image or a package reaches people only from a commit every test job passed on, so a
    test job added later and left out of `needs` cannot publish a break it caught."""
    jobs = yaml.safe_load(WORKFLOW.read_text())["jobs"]
    tests = set(jobs) - PUBLISHING
    for name in PUBLISHING:
        assert set(jobs[name]["needs"]) == tests, name


def test_every_action_is_pinned_by_commit():
    """A tag or a branch can be moved to other code by whoever controls it, and the jobs that
    publish hold the credentials to ship that code to every user."""
    steps = [step for job in yaml.safe_load(WORKFLOW.read_text())["jobs"].values()
             for step in job["steps"] if "uses" in step]
    assert steps
    unpinned = [step["uses"] for step in steps
                if not re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", step["uses"])]
    assert unpinned == []


def test_jobs_read_the_repository_and_nothing_else_by_default():
    assert yaml.safe_load(WORKFLOW.read_text())["permissions"] == {"contents": "read"}
