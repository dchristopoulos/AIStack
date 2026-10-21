"""What a rule may be called and hold (ADR-0036). Pure: values in, values out or
ValidationError, with no session."""

import re

from aistack.commons.exceptions import ValidationError
from aistack.commons.text import loggable
from aistack.db.models.coding_agent import CodingAgent
from aistack.db.models.rule import RULE_NAME_MAX_LENGTH, RULE_TEXT_MAX_BYTES
from aistack.services import agent_files

# The name becomes part of a file name, `.claude/rules/aistack-<name>.md`, on every system.
_RULE_NAME = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")

# Shapes of a credential, matched per line. A warning, never a refusal: rules are theirs.
_CREDENTIALS = re.compile("|".join((
    r"\baist(?:inv|req)?_[A-Za-z0-9_-]{20,}",            # an AIStack token or code
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----",            # a private key block
    r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b",                    # an AWS access key id
    r"\bgh[pousr]_[A-Za-z0-9]{36,}",                     # a GitHub token
    r"\bgithub_pat_[A-Za-z0-9_]{22,}",                   # a GitHub fine-grained token
    r"\bglpat-[A-Za-z0-9_-]{20,}",                       # a GitLab token
    r"\bxox[abposr]-[A-Za-z0-9-]{10,}",                  # a Slack token
    r"hooks\.slack\.com/services/[A-Za-z0-9/]{20,}",     # a Slack webhook
    r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{20,}",           # an Anthropic or OpenAI key
    r"\bAIza[0-9A-Za-z_-]{35}",                          # a Google API key
    r"\b[rs]k_live_[A-Za-z0-9]{20,}",                    # a Stripe live key
)))


def validated_rule_name(name: object) -> str:
    if not isinstance(name, str):
        raise ValidationError(f"A rule's name must be text, but a {type(name).__name__} "
                              "arrived.")
    if len(name) > RULE_NAME_MAX_LENGTH:
        raise ValidationError(f"The rule name is {len(name)} characters long, and the limit is "
                              f"{RULE_NAME_MAX_LENGTH}. Received: '{loggable(name)}'.")
    if not _RULE_NAME.fullmatch(name):
        raise ValidationError("A rule name is lowercase letters and digits in groups joined by "
                              f"single hyphens, like 'house-style'. Received: '{loggable(name)}'.")
    return name


def validated_rule_text(text: object) -> str:
    """The text as it will be stored: at most 64 KiB of UTF-8, with no NUL character."""
    if not isinstance(text, str):
        raise ValidationError(f"A rule's text must be text, but a {type(text).__name__} "
                              "arrived.")
    try:
        size = len(text.encode("utf-8"))
    except UnicodeEncodeError:
        raise ValidationError("The rule's text is not valid Unicode: it holds half of a "
                              "surrogate pair. Save it again from the editor.") from None
    if size > RULE_TEXT_MAX_BYTES:
        raise ValidationError(f"The rule is {size} bytes, and the limit is "
                              f"{RULE_TEXT_MAX_BYTES} bytes (64 KiB). Shorten it, or split it "
                              "into two rules.")
    if "\0" in text:
        # PostgreSQL text cannot hold one, and no Markdown file needs one.
        raise ValidationError("The rule's text holds a NUL character, which a Markdown file "
                              "never needs. Remove it and save again.")
    return text


def credential_lines(text: str) -> list[int]:
    """The 1-based numbers of the lines that look like they hold a credential, counted as an
    editor counts them: `splitlines` would also break at a form feed or U+2028."""
    return [number for number, line in enumerate(text.split("\n"), start=1)
            if _CREDENTIALS.search(line)]


def validated_agents(agents: object) -> list[CodingAgent]:
    """The agents a rule is used for, each once, in the table's order. Only an agent AIStack
    writes rules for may be named."""
    if not isinstance(agents, list) or not all(isinstance(agent, str) for agent in agents):
        raise ValidationError("'agents' must be a list of agent names, like "
                              "[\"claude_code\", \"codex\"].")
    writable = agent_files.agents_writing_rules()
    allowed = ", ".join(agent.value for agent in writable)
    chosen = set()
    for agent in agents:
        try:
            known = CodingAgent(agent)
        except ValueError:
            raise ValidationError(f"Rules are written for {allowed}. Received: "
                                  f"'{loggable(agent)}'.") from None
        if known not in writable:
            raise ValidationError(f"AIStack writes rules for {allowed} for now, and shows "
                                  f"{agent_files.AGENT_FILES[known].display_name}'s files "
                                  "without writing them. Received: "
                                  f"'{known.value}'.")
        chosen.add(known)
    return [agent for agent in writable if agent in chosen]
