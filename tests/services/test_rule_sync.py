import subprocess

import pytest

from aistack.commons.exceptions import ValidationError
from aistack.services import rule_files
from aistack.services.rule_sync import validated_observation


def _file(**changes):
    return {"agent": "claude_code", "place": "project", "name": "house-style",
            "digest": "a" * 64} | changes


@pytest.mark.parametrize("entry", [
    _file(name="../../.ssh/authorized_keys"),
    _file(name="a/b"),
    _file(name="House"),
    _file(name=None),
    _file(place="every_project", name="house-style"),
    _file(place="anywhere"),
    _file(agent="cursor"),
    _file(agent="nobody"),
    _file(digest=7),
])
def test_a_rule_file_is_named_never_pathed(entry):
    """The server takes a rule's name, which becomes part of a file name, and never a path."""
    with pytest.raises(ValidationError):
        validated_observation([entry])


def test_an_observation_lists_each_file_once():
    with pytest.raises(ValidationError, match="twice"):
        validated_observation([_file(), _file(digest=None)])
    assert validated_observation([_file(digest=" ABC ")])[0].digest == "abc"


@pytest.mark.parametrize("path", ["../outside.md", "/etc/passwd", "a\\b.md", "", "a/../../b"])
def test_a_repository_path_from_the_server_stays_in_the_project(path):
    with pytest.raises(ValidationError):
        rule_files.validated_repository_path(path)


def test_the_override_round_trips_its_sections():
    text = rule_files.override_text("Repository.\n", [("a", "One"), ("b", "Two\n\n")])
    assert rule_files.parsed_override(text.encode()) == {"a": "One", "b": "Two\n\n"}
    assert rule_files.parsed_override(b"Not ours.\n") is None


def test_a_rules_folder_leading_outside_the_project_is_not_read(tmp_path):
    top, outside = tmp_path / "project", tmp_path / "outside"
    subprocess.run(["git", "init", "-q", str(top)], check=True)
    (outside / "rules").mkdir(parents=True)
    (outside / "rules/aistack-x.md").write_text("elsewhere")
    (top / ".claude").symlink_to(outside)
    assert rule_files.claude_rules(top, set()) == {}
    assert not rule_files.inside(top, rule_files.claude_rule_path(top, "x").parent)


def test_a_file_edited_since_it_was_observed_is_not_replaced(tmp_path):
    path = tmp_path / "CLAUDE.md"
    path.write_text("edited meanwhile")
    assert rule_files.replace(path, b"library", b"as observed") is False
    assert path.read_text() == "edited meanwhile"
    assert rule_files.remove(path, b"as observed") is False and path.exists()
    assert rule_files.replace(path, b"library", b"edited meanwhile") is True
    assert path.read_text() == "library"


def test_a_tracked_rules_file_is_the_repositorys(tmp_path):
    top = tmp_path / "project"
    (top / ".claude/rules").mkdir(parents=True)
    (top / ".claude/rules/aistack-x.md").write_text("theirs")
    assert rule_files.claude_rules(top, {".claude/rules/aistack-x.md"}) == {}
    assert rule_files.claude_rules(top, set()) == {"x": b"theirs"}
