import logging
import os
import time
from types import SimpleNamespace

import pytest

from aistack.bootstrap import self_update


@pytest.fixture(name="as_a_uv_tool")
def as_a_uv_tool_fixture(monkeypatch):
    monkeypatch.setattr(self_update, "installed_as_uv_tool", lambda: True)
    monkeypatch.setattr(self_update, "_uv", lambda: "/opt/uv")
    monkeypatch.setattr(self_update.metadata, "version", lambda _: "0.1.0")


def _recorder(returncode=0, stderr=""):
    calls = []

    def run(command, **_):
        calls.append(command)
        return SimpleNamespace(returncode=returncode, stderr=stderr)
    return calls, run


def test_a_newer_release_is_installed_for_the_next_start(tmp_path, as_a_uv_tool):
    calls, run = _recorder()

    installed = self_update.check_and_upgrade(tmp_path, lambda: "0.1.3", run)

    assert installed == "0.1.3"
    assert calls == [["/opt/uv", "tool", "upgrade", "aistack-mcp"]]


def test_a_failed_upgrade_is_logged_where_local_mode_shows_it(tmp_path, as_a_uv_tool, caplog):
    """Local mode logs at WARNING. uv's own output stays out: it can name a private index."""
    caplog.set_level(logging.DEBUG)
    _, run = _recorder(returncode=2, stderr="error: https://person:s3cret@index.example/simple")

    assert self_update.check_and_upgrade(tmp_path, lambda: "0.1.3", run) is None

    failures = [record for record in caplog.records if "uv tool upgrade" in record.getMessage()]
    assert [record.levelno for record in failures] == [logging.WARNING]
    assert "s3cret" not in caplog.text
    assert "index.example" not in caplog.text


def test_a_new_minor_version_waits_for_the_person(tmp_path, as_a_uv_tool):
    """Before 1.0 a new minor is one older releases may stop working beside (ADR-0024)."""
    calls, run = _recorder()
    assert self_update.check_and_upgrade(tmp_path, lambda: "0.2.0", run) is None
    assert calls == []


def test_a_library_that_needs_a_newer_release_updates_at_once(tmp_path, as_a_uv_tool):
    """Another computer moved the Library on: no daily wait, and a new minor is installed."""
    calls, run = _recorder()
    self_update.check_and_upgrade(tmp_path, lambda: "0.1.0", run)  # checked a moment ago

    installed = self_update.check_and_upgrade(tmp_path, lambda: "0.2.0", run, force=True)

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
        return "0.1.1"

    self_update.check_and_upgrade(tmp_path, latest, run)
    self_update.check_and_upgrade(tmp_path, latest, run)
    assert len(asked) == 1

    day_ago = time.time() - 25 * 60 * 60
    os.utime(tmp_path / "last-update-check", (day_ago, day_ago))
    self_update.check_and_upgrade(tmp_path, latest, run)
    assert len(asked) == 2


def test_only_a_uv_tool_install_upgrades_itself(tmp_path, monkeypatch):
    """A checkout, pipx, or the server's container is left alone."""
    monkeypatch.setattr(self_update, "installed_as_uv_tool", lambda: False)
    calls, run = _recorder()
    assert self_update.check_and_upgrade(tmp_path, lambda: "9.0.0", run) is None
    assert calls == []


@pytest.mark.parametrize(("setting", "needs_newer", "expected"), [
    (None, False, [False]),
    (None, True, [True]),
    ("off", True, []),
])
def test_local_mode_updates_unless_the_person_turned_it_off(tmp_path, monkeypatch, setting,
                                                            needs_newer, expected):
    from aistack.bootstrap import __main__ as entry
    from aistack.mcp import local

    started = []
    monkeypatch.setenv("AISTACK_HOME", str(tmp_path))
    if setting is None:
        monkeypatch.delenv("AISTACK_AUTO_UPDATE", raising=False)
    else:
        monkeypatch.setenv("AISTACK_AUTO_UPDATE", setting)
    monkeypatch.setattr(entry, "build_local_context", lambda settings: None)
    monkeypatch.setattr(entry, "needs_newer_release", lambda: needs_newer)
    monkeypatch.setattr(entry.os, "chdir", lambda folder: None)
    monkeypatch.setattr(self_update, "start_in_background",
                        lambda home, force=False: started.append(force))
    monkeypatch.setattr(local.local_mcp, "run", lambda **_: None)

    entry.serve_local()

    assert started == expected
