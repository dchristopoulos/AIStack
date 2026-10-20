"""Optional bindings refuse accidental copies before program filesystem work."""

import hashlib
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastmcp.exceptions import ToolError
from sqlalchemy import select
from sqlalchemy.sql.dml import Update

from aistack.bootstrap import hardware
from aistack.bootstrap.context.application_context import get_session_factory
from aistack.commons.exceptions import AIStackError, Conflict
from aistack.db.models.machine import Machine
from aistack.services import computer_fingerprint, server_sync
from aistack.services.server_connection import Connection
from tests.mcp.conftest import call, join

pytestmark = pytest.mark.anyio


async def test_first_binding_is_optional_and_later_mismatch_is_refused(server_url, session_factory):
    token = await join(server_url)
    identity = await call(server_url, token, "sync", local={}, identify=True)
    machine = uuid.UUID(identity["machine_id"])
    first = hardware.fingerprint(machine, "one-computer")
    second = hardware.fingerprint(machine, "a-copied-home")
    await call(server_url, token, "sync", local={}, identify=True, fingerprint=first)
    with pytest.raises(ToolError, match="different computer"):
        await call(server_url, token, "sync", local={}, fingerprint=second)
    # Older callers omit it, and omission neither clears nor claims the binding.
    await call(server_url, token, "sync", local={})
    with session_factory.begin() as session:
        assert session.get(Machine, machine).fingerprint_hash == first
    await call(server_url, token, "sync", local={}, fingerprint=first)


@pytest.mark.parametrize("value", ["raw-hardware-secret", "A" * 64, "a" * 65])
async def test_malformed_fingerprint_is_not_reflected(server_url, value):
    token = await join(server_url)
    with pytest.raises(ToolError) as rejected:
        await call(server_url, token, "sync", local={}, fingerprint=value)
    assert value not in str(rejected.value)


async def test_two_first_bindings_have_one_winner(server_url, session_factory, monkeypatch):
    token = await join(server_url)
    identity = await call(server_url, token, "sync", local={}, identify=True)
    machine = uuid.UUID(identity["machine_id"])
    with session_factory.begin() as session:
        user = session.get(Machine, machine).user_id
    barrier = threading.Barrier(2)
    execute = session_factory.class_.execute

    def at_claim(session, statement, *args, **kwargs):
        if isinstance(statement, Update) and statement.table.name == "machine":
            # Before connection acquisition: SQLite begins IMMEDIATE here, whereas PG
            # contenders reach the conditional UPDATE together. Neither sleeps in a tx.
            barrier.wait(10)
        return execute(session, statement, *args, **kwargs)

    monkeypatch.setattr(session_factory.class_, "execute", at_claim)

    def claim(value):
        try:
            with session_factory.begin() as session:
                computer_fingerprint.bind(session, machine, user, value)
            return True
        except Conflict:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(claim, ["a" * 64, "b" * 64])) == [False, True]


async def test_program_checks_binding_before_observation_or_transfer(server_url, tmp_path, monkeypatch):
    token = await join(server_url)
    (tmp_path / ".claude").mkdir()
    monkeypatch.setattr(hardware, "hardware_id", lambda: "first")
    await server_sync.sync_computer(Connection(server_url, token), tmp_path, tmp_path)
    monkeypatch.setattr(hardware, "hardware_id", lambda: "copied")

    def no_disk(*args, **kwargs):
        pytest.fail("The program touched disk before validating this computer")

    monkeypatch.setattr(server_sync.local_skills, "observed", no_disk)
    with pytest.raises(AIStackError, match="different computer"):
        await server_sync.sync_computer(Connection(server_url, token), tmp_path, tmp_path)


def test_fingerprint_encoding_is_fixed_across_platforms():
    machine = uuid.UUID("00112233-4455-6677-8899-aabbccddeeff")
    expected = hashlib.sha256("00112233-4455-6677-8899-aabbccddeeff:computer-é".encode("utf-8")).hexdigest()
    assert hardware.fingerprint(machine, "computer-é") == expected


async def test_identity_discovery_keeps_first_sync_and_no_hardware_is_diagnostic(server_url, tmp_path, monkeypatch):
    token = await join(server_url)
    (tmp_path / ".claude").mkdir()
    await call(server_url, token, "sync", local={}, identify=True)
    monkeypatch.setattr(hardware, "hardware_id", lambda: None)
    reports = await server_sync.sync_computer(Connection(server_url, token), tmp_path, tmp_path)
    assert reports[0]["first_sync"]
    assert reports[0]["failures"] == []
    assert "cannot be detected" in server_sync.output(reports)
    assert "cannot be detected" not in server_sync.output(reports, hook=True)
    with get_session_factory().begin() as session:
        assert session.scalar(select(Machine.fingerprint_hash)) is None
