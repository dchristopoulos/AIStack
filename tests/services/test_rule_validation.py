"""A rule's name, its text, the agents it is for, and the credential warning (ADR-0036)."""

import pytest

from aistack.commons.exceptions import ValidationError
from aistack.db.models.coding_agent import CodingAgent
from aistack.services.content_hash import file_digest, text_hash
from aistack.services.rule_validation import (
    credential_lines,
    validated_agents,
    validated_rule_name,
    validated_rule_text,
)


@pytest.mark.parametrize("name", ["house-style", "a", "x1-2"])
def test_a_good_name_is_kept(name):
    assert validated_rule_name(name) == name


@pytest.mark.parametrize("name", ["", "House", "two  words", "a--b", "-a", "a/b", "../x", 7,
                                  "a" * 65])
def test_a_bad_name_is_refused(name):
    with pytest.raises(ValidationError):
        validated_rule_name(name)


def test_a_rule_up_to_64_kib_is_kept():
    text = "é" * (32 * 1024)

    assert validated_rule_text(text) == text


def test_a_rule_over_64_kib_says_how_big_it_was():
    with pytest.raises(ValidationError) as refused:
        validated_rule_text("x" * (64 * 1024 + 1))

    assert "65537 bytes" in refused.value.message and "65536" in refused.value.message


@pytest.mark.parametrize("text", ["a\0b", "\ud800", 3, None])
def test_text_a_file_cannot_hold_is_refused(text):
    with pytest.raises(ValidationError):
        validated_rule_text(text)


def test_the_hash_is_the_digest_of_the_files_bytes():
    assert text_hash("# Rules\n- é\n") == file_digest("# Rules\n- é\n".encode())


@pytest.mark.parametrize("line", [
    "token: aist_" + "A" * 43,
    "-----BEGIN OPENSSH PRIVATE KEY-----",
    "-----BEGIN RSA PRIVATE KEY-----",
    "AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE",
    "ghp_" + "a" * 36,
    "github_pat_" + "A" * 30,
    "glpat-" + "a" * 20,
    "SLACK=xoxb-1234567890-abcdef",
    "https://hooks.slack.com/services/T000/B000/XXXXXXXXXXXXXXXXXXXX",
    "ANTHROPIC_API_KEY=sk-ant-" + "a" * 40,
    "sk-proj-" + "a" * 40,
    "AIza" + "a" * 35,
    "sk_live_" + "a" * 24,
])
def test_a_credential_shape_is_found(line):
    assert credential_lines(f"# Rules\n\n{line}\nmore\n") == [3]


def test_ordinary_rules_raise_no_warning():
    text = ("# House style\n- Use sk-learn for models.\n- Read AKIA docs.\n"
            "- Never print aist_ tokens.\n- Keys live in the vault.\n")

    assert credential_lines(text) == []


def test_lines_are_counted_as_an_editor_counts_them():
    assert credential_lines("a\fb c\r\nghp_" + "a" * 36) == [2]


def test_agents_are_kept_once_in_the_tables_order():
    assert validated_agents(["codex", "claude_code", "codex"]) == [CodingAgent.CLAUDE_CODE,
                                                                   CodingAgent.CODEX]
    assert validated_agents([]) == []


@pytest.mark.parametrize("agents", [["cursor"], ["vim"], "codex", [1]])
def test_an_agent_aistack_does_not_write_for_is_refused(agents):
    with pytest.raises(ValidationError):
        validated_agents(agents)
