"""A project's skills folder over the server's tools, with a bearer (ADR-0026)."""

import logging

import httpx
import pytest
from fastmcp.exceptions import ToolError
from sqlalchemy import func, select

from aistack.db.models.machine import Machine
from aistack.db.models.machine_project import MachineProject
from aistack.db.models.machine_project_skill import MachineProjectSkill
from aistack.db.models.machine_skill import MachineSkill
from aistack.db.models.project import Project
from aistack.db.models.skill_version import SkillVersion
from aistack.services import project_service
from tests.archives import skill_archive
from tests.mcp.conftest import call, client_for, join

pytestmark = pytest.mark.anyio

# A remote as git prints it when a token is in the URL: nothing of it may be kept or logged.
CANARY = "ghs_canaryTOKEN0123456789"
HERE = {"path": "/Users/dimitris/code/aistack",
        "remote": f"https://x-access-token:{CANARY}@github.com/dchristopoulos/AIStack.git"}
KEY = "github.com/dchristopoulos/aistack"


async def _project_sync(server_url, token, **arguments) -> dict:
    return await call(server_url, token, "sync", local={}, here=HERE, project=KEY, **arguments)


async def _refusal(server_url, token, tool, **arguments) -> str:
    async with client_for(server_url, token) as client:
        with pytest.raises(ToolError) as refused:
            await client.call_tool(tool, arguments)
    return str(refused.value)


async def test_naming_the_repository_reports_it_and_a_project_sync_starts_managing_it(
        server_url, session_factory):
    token = await join(server_url)

    seen = await call(server_url, token, "sync", local={}, here=HERE)
    synced = await _project_sync(server_url, token)
    again = await call(server_url, token, "sync", local={}, here=HERE)

    assert seen["project"] == {"key": KEY, "name": "aistack", "managed": False}
    assert synced["project"]["managed"] is True and synced["first_sync"] is True
    assert synced["sync_skill_url"] is None
    assert again["project"]["managed"] is True


async def test_a_push_from_a_project_lands_in_that_folder_only(server_url, session_factory):
    token = await join(server_url)
    await _project_sync(server_url, token)

    issued = await call(server_url, token, "push_skill", name="notes", project=KEY)
    async with httpx.AsyncClient() as http:
        stored = (await http.put(issued["upload_url"], content=skill_archive("notes"))).json()

    assert stored["revision"] == 1
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(MachineProjectSkill)) == 1
        assert session.scalar(select(func.count()).select_from(MachineSkill)) == 0
    installed = await call(server_url, token, "get_skill", name="notes", project=KEY)
    assert installed["folder"] == ".claude/skills"


async def test_an_upload_after_the_project_stopped_being_managed_stores_nothing(
        server_url, session_factory):
    token = await join(server_url)
    await _project_sync(server_url, token)
    issued = await call(server_url, token, "push_skill", name="notes", project=KEY)
    with session_factory.begin() as session:
        machine = session.scalar(select(Machine))
        project_service.remove_folder(session, machine.user_id, machine.machine_id, KEY)

    async with httpx.AsyncClient() as http:
        refused = await http.put(issued["upload_url"], content=skill_archive("notes"))

    assert refused.status_code == 404
    assert "no longer managed on this computer" in refused.json()["error"]
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(SkillVersion)) == 0


async def test_another_users_project_reads_like_one_that_does_not_exist(server_url):
    dimitris = await join(server_url)
    maria = await join(server_url, "maria", "laptop")
    await _project_sync(server_url, dimitris)

    theirs = [await _refusal(server_url, maria, tool, name="notes", project=KEY)
              for tool in ("get_skill", "push_skill", "disable_skill")]
    nobodys = [await _refusal(server_url, maria, tool, name="notes",
                              project="github.com/nobody/nothing")
               for tool in ("get_skill", "push_skill", "disable_skill")]

    assert [refusal.replace(KEY, "X") for refusal in theirs] == [
        refusal.replace("github.com/nobody/nothing", "X") for refusal in nobodys]
    assert all("does not manage a project" in refusal for refusal in theirs)


async def test_a_token_in_a_remote_is_never_kept_logged_or_returned(server_url, session_factory,
                                                                    caplog):
    token = await join(server_url)
    # AIStack's own lines; the protocol libraries' are floored at INFO in a real server.
    caplog.set_level(logging.DEBUG, logger="aistack")

    results = [await call(server_url, token, "sync", local={}, here=HERE),
               await _project_sync(server_url, token),
               await call(server_url, token, "push_skill", name="notes", project=KEY)]

    ours = [record.getMessage() for record in caplog.records
            if record.name.startswith("aistack")]
    assert ours and not any(CANARY in line for line in ours)
    assert CANARY not in str(results)
    with session_factory() as session:
        stored = [str(row) for model in (Project, MachineProject)
                  for row in session.execute(select(model.__table__)).all()]
    assert stored and all(CANARY not in row for row in stored)
