"""A Library on real GitHub (ADR-0025): scratch computers sharing a private repository through
the person's own gh login, with nothing standing in for GitHub.

Runs only when AISTACK_E2E_GITHUB_REPO names a private repository the signed-in gh account can
write to, such as `owner/aistack-library-e2e`. Every run adds its computers and skills to that
repository's log, which only ever grows (ADR-0025), so use one kept for this alone. Each run's
skill names are its own, so runs never read each other's changes as their own.
"""

import contextlib
import os
import subprocess
import uuid

import pytest
from fastmcp import Client

from aistack.bootstrap.configuration.settings.settings_config import LocalSettings
from aistack.bootstrap.context import application_context
from aistack.mcp import local_dashboard
from aistack.mcp.local import local_mcp

REPOSITORY = os.environ.get("AISTACK_E2E_GITHUB_REPO")

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(not REPOSITORY, reason="Set AISTACK_E2E_GITHUB_REPO to a private "
                                              "repository to run the real-GitHub tests."),
]


@pytest.fixture(name="anyio_backend")
def anyio_backend_fixture():
    return "asyncio"


@pytest.fixture(name="computer")
def computer_fixture(tmp_path, monkeypatch):
    # Each computer gets a scratch home, where gh would not find its login: hand git the
    # token directly, through the same `gh auth git-credential` AIStack configures.
    token = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True,
                           check=True).stdout.strip()
    monkeypatch.setenv("GH_TOKEN", token)

    @contextlib.asynccontextmanager
    async def computer(name: str):
        home = tmp_path / name
        home.mkdir(exist_ok=True)
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setenv("USERPROFILE", str(home))
        application_context.build_local_context(LocalSettings(
            aistack_home=home / ".aistack", aistack_library_repo=REPOSITORY,
            aistack_username="e2e"))
        try:
            assert application_context.get_local_principal()
            async with Client(local_mcp) as client:
                yield client, home
        finally:
            local_dashboard.stop_dashboard()
            application_context.dispose_application_context()

    return computer


def _write(home, name, body):
    folder = home / ".claude" / "skills" / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {name}.\n---\n\n{body}\n")
    return folder


async def _call(client, tool, **arguments):
    return (await client.call_tool(tool, arguments)).structured_content


async def test_a_skill_travels_between_computers_and_back_through_github(computer, caplog):
    caplog.set_level("DEBUG")
    name = f"e2e-{uuid.uuid4().hex[:8]}"

    async with computer("laptop") as (laptop, home):
        original = _write(home, name, "First.")
        pushed = await _call(laptop, "push_skill", name=name)
        assert (pushed["revision"], pushed["shared"]) == (1, True)

    async with computer("desktop") as (desktop, home):
        installed = await _call(desktop, "get_skill", name=name)
        assert installed["revision"] == 1
        copy = home / ".claude" / "skills" / name / "SKILL.md"
        assert copy.read_bytes() == (original / "SKILL.md").read_bytes()
        _write(home, name, "Second.")
        assert (await _call(desktop, "push_skill", name=name))["revision"] == 2

    async with computer("laptop") as (laptop, _):
        synced = await _call(laptop, "sync")
        assert name in [skill["name"] for skill in synced["update"]]

    # git and gh ran with the person's token the whole time; no log line carries it.
    assert os.environ["GH_TOKEN"] not in caplog.text
