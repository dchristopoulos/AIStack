"""One-use codes authorize only one approved request, including competing transactions."""

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from fastmcp.exceptions import ToolError
from sqlalchemy import select

from aistack.commons.exceptions import Conflict, NotFound
from aistack.db.models.computer_code import ComputerCode
from aistack.db.models.machine import Machine
from aistack.db.models.timestamps import utc_now
from aistack.services import computer_codes as codes
from aistack.services import operator_service
from aistack.services.token_service import hash_token
from tests.api.test_dashboard_over_http import _browser, _post, _state
from tests.mcp.conftest import call, client_for, join

pytestmark = pytest.mark.anyio


async def issued(server_url, **options):
    token = await join(server_url)
    result = await call(server_url, token, "add_machine", computer_code=True, options=options)
    return token, result


async def test_approval_and_one_delivery_over_real_http(server_url, session_factory, caplog):
    token, code = await issued(server_url)
    assert len(code["code"]) == 14 and "token" not in code
    assert codes.normalized(code["code"].lower()) == code["code"].replace("-", "")
    async with client_for(server_url, code["code"]) as client:
        assert {tool.name for tool in await client.list_tools()} == {"join"}
    request = await call(
        server_url, code["code"], "join", pairing="reserve", machine_name="new", os="LINUX"
    )
    bearer = request["request_bearer"]
    assert (await call(server_url, bearer, "join", pairing="poll"))["status"] == "waiting"
    with session_factory.begin() as session:
        assert session.get(Machine, uuid.UUID(request["machine_id"])) is None
    with pytest.raises(ToolError):
        await call(server_url, code["code"], "join", pairing="poll")
    async with _browser(server_url, token) as browser:
        state = await _state(browser)
        assert state["computer_codes"][0]["status"] == "waiting"
        assert code["code"] not in str(state) and bearer not in str(state)
        assert (
            await browser.post("/api/computer-codes/" + code["id"] + "/approve", json={})
        ).status_code == 400
        assert (
            await _post(browser, "/computer-codes/" + code["id"] + "/approve")
        ).status_code == 200
    added = await call(server_url, bearer, "join", pairing="poll", fingerprint="a" * 64)
    assert added["token"].startswith("aist_")
    assert "token" not in await call(server_url, bearer, "join", pairing="poll")
    await call(
        server_url, bearer, "join", pairing="confirm", setup={"agents": ["codex"], "skills": 0}
    )
    async with _browser(server_url, token) as browser:
        assert (await _state(browser))["computer_codes"][0]["status"] == "complete"
    with session_factory.begin() as session:
        assert session.get(Machine, uuid.UUID(added["machine_id"])).fingerprint_hash == "a" * 64
    for secret in (code["code"], bearer, added["token"]):
        assert secret not in caplog.text


async def test_owner_scope_frozen_options_and_denial(server_url):
    token, code = await issued(server_url)
    other = await join(server_url, "other")
    async with _browser(server_url, other) as browser:
        assert (await _state(browser))["computer_codes"] == []
        for action in ("/cancel", "/approve", "/deny", ""):
            assert (
                await _post(browser, "/computer-codes/" + code["id"] + action)
            ).status_code == 404
    reserved = await call(
        server_url, code["code"], "join", pairing="reserve", machine_name="new", os="MACOS"
    )
    async with _browser(server_url, token) as browser:
        assert (
            await _post(browser, "/computer-codes/" + code["id"], approval=False)
        ).status_code == 409
        assert (await _post(browser, "/computer-codes/" + code["id"] + "/deny")).status_code == 200
    with pytest.raises(ToolError):
        await call(server_url, reserved["request_bearer"], "join", pairing="poll")


@pytest.mark.parametrize("invalidate", ["cancel", "expire", "rotate", "remove", "offboard"])
async def test_recheck_after_verification_refuses_invalidated_request(
    server_url, session_factory, invalidate
):
    token, code = await issued(server_url, approval=False)
    request = await call(
        server_url, code["code"], "join", pairing="reserve", machine_name="new", os="LINUX"
    )
    entered, resume = threading.Barrier(2), threading.Barrier(2)

    def complete():
        # The HTTP bearer has its bootstrap scope already. Stop at the exact
        # pre-transaction window, then revoke before redemption can read any row.
        entered.wait(10)
        resume.wait(10)
        with session_factory.begin() as session:
            return codes.poll(session, request["request_bearer"], None)

    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(complete)
        entered.wait(10)
        with session_factory.begin() as session:
            row = session.get(ComputerCode, uuid.UUID(code["id"]))
            if invalidate == "expire":
                row.expires_on = utc_now() - timedelta(seconds=1)
            elif invalidate == "cancel":
                codes.decide(session, row.user_id, row.code_id, "cancel")
            elif invalidate == "rotate":
                operator_service.rotate(session, "dimitris", "macbook")
            elif invalidate == "remove":
                operator_service.remove_machine(session, "dimitris", "macbook")
            else:
                operator_service.offboard(session, "dimitris")
        resume.wait(10)
        with pytest.raises(NotFound):
            pending.result(10)


async def test_options_expiry_and_limit(server_url, session_factory):
    token, code = await issued(server_url)
    async with _browser(server_url, token) as browser:
        changed = await _post(
            browser,
            "/computer-codes/" + code["id"],
            expires_hours=1,
            agents="codex",
            name="travel",
            skills="empty",
            hook=False,
            approval=False,
        )
        assert changed.status_code == 200 and changed.json()["options"]["name"] == "travel"
        assert "code" not in changed.json()
        for _ in range(4):
            assert (await _post(browser, "/computer-codes")).status_code == 200
        assert (await _post(browser, "/computer-codes")).status_code == 409
        await _post(browser, "/computer-codes/" + code["id"] + "/cancel")
        assert (await _post(browser, "/computer-codes")).status_code == 200
    with session_factory.begin() as session:
        row = session.get(ComputerCode, uuid.UUID(code["id"]))
        assert row.code_hash == hash_token(codes.normalized(code["code"]))


async def test_claim_completion_and_limit_serialize(server_url, session_factory, monkeypatch):
    token, code = await issued(server_url, approval=False)

    # Synchronize before the first database operation, before SQLite's write lock.
    def race(function, values):
        barrier = threading.Barrier(2)
        execute = session_factory.class_._execute_internal

        def at_first_lock(session, statement, *args, **kwargs):
            if not session.info.get("racing"):
                session.info["racing"] = True
                barrier.wait(10)
            return execute(session, statement, *args, **kwargs)

        def invoke(value):
            try:
                with session_factory.begin() as session:
                    return function(session, value)
            except (NotFound, Conflict):
                return None

        with monkeypatch.context() as patch:
            patch.setattr(session_factory.class_, "_execute_internal", at_first_lock)
            with ThreadPoolExecutor(max_workers=2) as pool:
                return list(pool.map(invoke, values))

    reservations = race(
        lambda session, name: codes.reserve(session, code["code"], name, "LINUX"), ["one", "two"]
    )
    assert sum(value is not None for value in reservations) == 1
    request = next(value for value in reservations if value is not None)
    completions = race(
        lambda session, _: codes.poll(session, request["request_bearer"], None), [1, 2]
    )
    assert all(value is not None and value["status"] == "connected" for value in completions)
    assert sum("token" in value for value in completions if value) == 1
    with session_factory.begin() as session:
        user = session.scalar(select(Machine).where(Machine.token_hash == hash_token(token)))
        identity, machine, prefix = user.user_id, user.machine_id, user.token_hash[:16]
        from aistack.services.transfer_ticket import token_prefix

        prefix = token_prefix(user.token_hash)
        for _ in range(4):
            codes.create(session, identity, machine, prefix)
    created = race(lambda session, _: codes.create(session, identity, machine, prefix), [1, 2])
    assert sum(value is not None for value in created) == 1


@pytest.mark.parametrize("operation", ["reserve", "poll"])
async def test_expiry_during_redemption_is_rechecked(
    server_url, session_factory, monkeypatch, operation
):
    _, code = await issued(server_url, approval=False)
    bearer = code["code"]
    if operation == "poll":
        bearer = (
            await call(
                server_url, bearer, "join", pairing="reserve", machine_name="new", os="LINUX"
            )
        )["request_bearer"]
    # Let the in-memory active check pass, but advance beyond expiry before the
    # conditional database write. No sleep while a writing transaction is open.
    real_active = codes._active

    def active_then_expired(row):
        active = real_active(row)
        monkeypatch.setattr(codes, "utc_now", lambda: utc_now() + timedelta(days=8))
        return active

    monkeypatch.setattr(codes, "_active", active_then_expired)
    with session_factory.begin() as session, pytest.raises(NotFound):
        if operation == "reserve":
            codes.reserve(session, bearer, "new", "LINUX")
        else:
            codes.poll(session, bearer, None)
