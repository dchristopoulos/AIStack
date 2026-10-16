"""What the documents promise, held against the files they describe."""

import pathlib
import re

_ROOT = pathlib.Path(__file__).parents[1]


def test_every_decision_is_listed_in_the_decisions_index():
    index = (_ROOT / "docs" / "adr" / "README.md").read_text()
    decisions = sorted(path.name for path in (_ROOT / "docs" / "adr").glob("[0-9]*.md"))

    assert decisions
    assert [name for name in decisions if f"]({name})" not in index] == []


def test_the_documented_containers_publish_plain_http_on_this_computer_only():
    """SEC-12, STD-12: Docker's published ports bypass host firewalls, so a bare
    `-p 8000:8000` puts plain HTTP on every interface beside the proxy's HTTPS."""
    commands = "\n".join(block for name in ("README.md", "docs/OPERATING.md")
                         for block in re.findall(r"```bash\n(.*?)```",
                                                 (_ROOT / name).read_text(), re.DOTALL))
    published = re.findall(r"-p (\S+)", commands)

    assert published
    assert [port for port in published if not port.startswith("127.0.0.1:")] == []
    assert '"${AISTACK_BIND:-127.0.0.1}:8000:8000"' in (_ROOT / "compose.yaml").read_text()


def test_the_quick_start_server_listens_on_this_computer_only():
    """It runs with an invite code anyone can read in the README."""
    readme = (_ROOT / "README.md").read_text()

    assert all("AISTACK_HOST=127.0.0.1" in line
               for line in readme.splitlines() if "aistack serve" in line)
