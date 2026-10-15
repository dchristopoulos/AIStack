"""Files AIStack ships and serves as they are: the setup instructions, the sync skill, and
the dashboard page, plus local mode's own setup and sync skill.

They live inside the package so the container image carries them, and a new user's agent can
fetch them from the server it is joining. A fresh vault cannot install the skill that talks
to it, so that one skill comes from here.
"""

from importlib import resources

SYNC_SKILL_NAME = "sync-aistack"

# The logo, for the browser tab of every page the server answers with. Inline, because those
# pages load nothing from anywhere; without it a browser asks for /favicon.ico on each load.
ICON_LINK = (
    '<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns=\'http://www.w3.org/2000/svg\' '
    "viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='8' fill='%232259d6'/%3E"
    "%3Cpath d='M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5' "
    "transform='translate(5 5) scale(.92)' fill='none' stroke='white' stroke-width='2.2' "
    "stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E\">")

# Every sentence that runs or installs AIStack, in the README, the operator's guide, setup,
# the sync skill and the page, starts with one of these, and a test holds them to it, so a
# change to where AIStack is installed from is made once and cannot miss a sentence.
RUN_COMMAND = "uvx aistack-mcp"
INSTALL_COMMAND = "uv tool install aistack-mcp"


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
