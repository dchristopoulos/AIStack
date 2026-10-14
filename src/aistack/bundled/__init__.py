"""Files AIStack ships and serves as they are: the setup instructions, the sync skill, and
the dashboard page, plus local mode's own setup and sync skill.

They live inside the package so the container image carries them, and a new user's agent can
fetch them from the server it is joining. A fresh vault cannot install the skill that talks
to it, so that one skill comes from here.
"""

from importlib import resources

SYNC_SKILL_NAME = "sync-aistack"


def setup_instructions() -> str:
    """The instructions template, with `{server_url}` and `{mcp_url}` still to fill in."""
    return _read("setup-aistack.md")


def dashboard_page() -> str:
    """The whole web application: one file, with its own styles and script (ADR-0017)."""
    return _read("dashboard.html")


def sync_skill_document() -> str:
    return _read(f"skills/{SYNC_SKILL_NAME}/SKILL.md")


def local_setup_instructions() -> str:
    """`aistack setup`: local mode's setup, which has no server to fetch it from (ADR-0020)."""
    return _read("local/setup.md")


def local_sync_skill_document() -> str:
    """The sync skill for local mode, where the tools read and write the folders themselves."""
    return _read(f"local/{SYNC_SKILL_NAME}/SKILL.md")


def _read(relative_path: str) -> str:
    return resources.files(__name__).joinpath(relative_path).read_text(encoding="utf-8")
