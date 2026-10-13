"""Files AIStack ships and serves as they are: the setup instructions and the sync skill.

They live inside the package so the container image carries them, and a new user's agent can
fetch them from the server it is joining. A fresh vault cannot install the skill that talks
to it, so that one skill comes from here.
"""

from importlib import resources

SYNC_SKILL_NAME = "sync-aistack"


def setup_instructions() -> str:
    """The instructions template, with `{server_url}` and `{mcp_url}` still to fill in."""
    return _read("setup-aistack.md")


def sync_skill_document() -> str:
    return _read(f"skills/{SYNC_SKILL_NAME}/SKILL.md")


def _read(relative_path: str) -> str:
    return resources.files(__name__).joinpath(relative_path).read_text(encoding="utf-8")
