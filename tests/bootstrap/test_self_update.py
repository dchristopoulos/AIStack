import os
import time
from types import SimpleNamespace

import pytest

from aistack.bootstrap import self_update


@pytest.fixture(name="as_a_uv_tool")
def as_a_uv_tool_fixture(monkeypatch):
    monkeypatch.setattr(self_update, "_installed_as_uv_tool", lambda: True)
    monkeypatch.setattr(self_update, "_uv", lambda: "/opt/uv")
    monkeypatch.setattr(self_update.metadata, "version", lambda _: "0.1.0")


def _recorder(returncode=0):
    calls = []

    def run(command, **_):
        calls.append(command)
        return SimpleNamespace(returncode=returncode, stderr="")
    return calls, run


def test_a_newer_release_is_installed_for_the_next_start(tmp_path, as_a_uv_tool):
    calls, run = _recorder()

    installed = self_update.check_and_upgrade(tmp_path, lambda: "0.2.0", run)

    assert installed == "0.2.0"
    assert calls == [["/opt/uv", "tool", "upgrade", "aistack-mcp"]]


def test_the_same_or_an_older_release_changes_nothing(tmp_path, as_a_uv_tool):
    calls, run = _recorder()
    assert self_update.check_and_upgrade(tmp_path, lambda: "0.1.0", run) is None
    assert calls == []


def test_pypi_is_asked_at_most_once_a_day(tmp_path, as_a_uv_tool):
    calls, run = _recorder()
    asked = []

    def latest():
        asked.append(1)
        return "0.2.0"

    self_update.check_and_upgrade(tmp_path, latest, run)
    self_update.check_and_upgrade(tmp_path, latest, run)
    assert len(asked) == 1

    day_ago = time.time() - 25 * 60 * 60
    os.utime(tmp_path / "last-update-check", (day_ago, day_ago))
    self_update.check_and_upgrade(tmp_path, latest, run)
    assert len(asked) == 2


def test_only_a_uv_tool_install_upgrades_itself(tmp_path, monkeypatch):
    """A checkout, pipx, or the server's container is left alone."""
    monkeypatch.setattr(self_update, "_installed_as_uv_tool", lambda: False)
    calls, run = _recorder()
    assert self_update.check_and_upgrade(tmp_path, lambda: "9.0.0", run) is None
    assert calls == []
