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
