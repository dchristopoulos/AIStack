from enum import StrEnum

from aistack.db.models.value_set import ValueSet


class CodingAgent(StrEnum):
    """The coding agents whose rule files AIStack knows (ADR-0036).

    Not a harness: a harness is a skills folder several agents read, and a rule is written to
    each agent's own file. The values are stored, so a new agent is a new member and a
    migration that widens the CHECK constraints holding these. `services/agent_files.py` says
    what each one reads.
    """

    CLAUDE_CODE = "claude_code"
    CODEX = "codex"
    GEMINI_CLI = "gemini_cli"
    CURSOR = "cursor"
    COPILOT_CLI = "copilot_cli"
    OPENCODE = "opencode"


def coding_agent_type(constraint_name: str) -> ValueSet:
    """An agent as VARCHAR + CHECK, stored by value, as a harness is."""
    return ValueSet(CodingAgent, native_enum=False, create_constraint=True, length=16,
                    validate_strings=True, name=constraint_name,
                    values_callable=lambda members: [member.value for member in members])
