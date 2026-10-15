from importlib import metadata

from aistack.commons.release import release
from aistack.db.schema import NewerSchema


def test_an_image_built_from_a_commit_names_the_commit(monkeypatch):
    version = metadata.version("aistack-mcp")
    monkeypatch.delenv("AISTACK_BUILD_COMMIT", raising=False)
    assert release() == version

    monkeypatch.setenv("AISTACK_BUILD_COMMIT", "1a2b3c4d5e6f7a8b9c0d")
    assert release() == f"{version}+g1a2b3c4"


def test_a_refusal_tells_a_newer_build_of_the_same_version_from_this_one(monkeypatch):
    monkeypatch.setenv("AISTACK_BUILD_COMMIT", "1a2b3c4d")
    same = NewerSchema("0012", "0012", release(), "0011")
    assert same.upgraded_by == f"a newer build of AIStack {release()}"
    assert NewerSchema("0012", "0012", "0.2.0", "0011").upgraded_by == "AIStack 0.2.0"
