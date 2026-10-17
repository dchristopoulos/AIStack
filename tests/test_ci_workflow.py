import re
from pathlib import Path

import yaml

WORKFLOW = Path(__file__).parents[1] / ".github" / "workflows" / "tests.yaml"
PUBLISHING = {"publish", "pypi"}
# Writes the GitHub Release once the package is out; it publishes nothing that runs.
RELEASE_NOTES = "release"


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


def test_publishing_waits_for_every_test_job():
    """An image or a package reaches people only from a commit every test job passed on, so a
    test job added later and left out of `needs` cannot publish a break it caught."""
    jobs = _workflow()["jobs"]
    tests = set(jobs) - PUBLISHING - {RELEASE_NOTES}
    for name in PUBLISHING:
        assert set(jobs[name]["needs"]) == tests, name
    assert jobs[RELEASE_NOTES]["needs"] == ["pypi"]


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


def test_the_suite_shards_cover_every_test():
    """The shards are k/n for every k up to one n, or some tests run in no job at all."""
    shards = _workflow()["jobs"]["suite"]["strategy"]["matrix"]["shard"]
    n = len(shards)
    assert sorted(shards) == [f"{k}/{n}" for k in range(1, n + 1)]
