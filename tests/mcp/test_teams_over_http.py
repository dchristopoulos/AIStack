"""Teams over real HTTP (ADR-0015): what a second person can and cannot reach."""

import io
import logging
import tarfile
from datetime import timedelta

import httpx
import pytest
from fastmcp.exceptions import ToolError
from sqlalchemy import delete, select

from aistack.bootstrap.context import application_context
from aistack.db.models.invite import Invite
from aistack.db.models.machine import Machine
from aistack.db.models.skill_version import SkillVersion
from aistack.db.models.timestamps import utc_now
from aistack.db.models.user import User
from aistack.services import team_service
from aistack.services.transfer_ticket import DownloadTicket
from tests.archives import local_digests, skill_document
from tests.mcp.conftest import call, client_for, join, push
from tests.mcp.test_tool_authorization import BOOTSTRAP_ONLY_TOOLS

pytestmark = pytest.mark.anyio

# What each machine-scope tool shows a user about a team they are not in. Adding a tool here
# is deciding that, and the words are the only ones there are:
#   own     - acts on the caller's own skills, machines, or account; no team is involved
#   hidden  - answers, with the team and everything in it left out
#   refused - the same sentence as for a team that does not exist
#   taken   - says the name is in use by a team or a user, and nothing else
#   code    - lets them in with the team's invite code, and says nothing without it
OUTSIDER_VIEW = {
    "add_machine": "own",
    "push_skill": "own",
    "disable_skill": "own",
    "open_dashboard": "own",
    "list_skills": "hidden",
    "list_teams": "hidden",
    "sync": "hidden",
    "get_skill": "refused",
    "share_skill": "refused",
    "invite_to_team": "refused",
    "create_team": "taken",
    "join_team": "code",
}

# One call per refused tool, naming a team. The outsider has a 'wizard' of their own, so the
# only thing wrong with each is the team.
REFUSED_CALLS = {
    "get_skill": {"name": "wizard"},
    "share_skill": {"name": "wizard"},
    "invite_to_team": {},
}


async def _team(server_url, admin, *members, name="acme") -> str:
    """A team created by `admin`, with `members` joined through its invite code."""
    await call(server_url, admin, "create_team", name=name)
    code = (await call(server_url, admin, "invite_to_team", team=name))["code"]
    for member in members:
        await call(server_url, member, "join_team", code=code)
    return name


async def _refusal(server_url, token, tool, **arguments) -> str:
    async with client_for(server_url, token) as client:
        with pytest.raises(ToolError) as rejection:
            await client.call_tool(tool, arguments)
    return str(rejection.value)


async def _download(url: str) -> httpx.Response:
    async with httpx.AsyncClient() as http:
        return await http.get(url)


def _extracted(archive: bytes) -> dict[str, tuple[bytes, bool]]:
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
        return {member.name: (tar.extractfile(member).read(), bool(member.mode & 0o111))
                for member in tar}


def _server_log(caplog) -> list[str]:
    """AIStack's own loggers, plus the framework's; see test_push_over_http.py."""
    return [record.getMessage() for record in caplog.records
            if record.name.startswith(("aistack", "fastmcp", "mcp.server", "uvicorn.error"))]


async def test_every_machine_tool_has_a_stated_view_for_an_outsider(server_url):
    """A new tool is a new way to ask about a team. It gets a row before it ships."""
    async with client_for(server_url, await join(server_url)) as client:
        registered = {tool.name for tool in await client.list_tools()}

    assert registered == set(OUTSIDER_VIEW)
    assert not BOOTSTRAP_ONLY_TOOLS & set(OUTSIDER_VIEW)
    assert set(REFUSED_CALLS) == {tool for tool, view in OUTSIDER_VIEW.items()
                                  if view == "refused"}


async def test_a_pushed_skill_is_seen_by_nobody_else_until_it_is_shared(server_url):
    dimitris = await join(server_url, "dimitris", "macbook")
    maria = await join(server_url, "maria", "laptop")
    await _team(server_url, dimitris, maria, name="everyone")
    await push(server_url, dimitris)

    assert (await call(server_url, maria, "list_skills")) == {"skills": []}
    for team in ({}, {"team": "everyone"}):
        assert "wizard" in await _refusal(server_url, maria, "get_skill", name="wizard", **team)

    await call(server_url, dimitris, "share_skill", name="wizard", team="everyone")

    assert (await call(server_url, maria, "list_skills"))["skills"] == [{
        "name": "wizard",
        "team": "everyone",
        "group": None,
        "description": "Walks a human through steps.",
        "revision": 1,
        "pushed_by": "dimitris",
    }]
    assert "You have no skill" in await _refusal(server_url, maria, "get_skill", name="wizard")


async def test_a_team_is_created_by_its_admin_and_joined_with_its_invite_code(server_url):
    dimitris = await join(server_url, "dimitris", "macbook")
    maria = await join(server_url, "maria", "laptop")

    created = await call(server_url, dimitris, "create_team", name="acme")
    invite = await call(server_url, dimitris, "invite_to_team", team="acme")
    joined = await call(server_url, maria, "join_team", code=invite["code"])

    assert created == {"name": "acme", "role": "ADMIN"}
    assert invite == {"team": "acme", "code": invite["code"], "link": invite["link"]}
    assert joined == {"team": "acme"}
    assert (await call(server_url, maria, "list_teams"))["teams"] == [
        {"name": "acme", "kind": "SHARED", "role": "MEMBER", "members": 2},
    ]


async def test_a_team_invite_code_admits_a_new_person_to_that_team(server_url, session_factory):
    """ADR-0019: one paste creates the account, registers the computer, and joins the team."""
    dimitris = await join(server_url)
    await call(server_url, dimitris, "create_team", name="acme")
    code = (await call(server_url, dimitris, "invite_to_team", team="acme"))["code"]

    async with client_for(server_url, code) as client:
        assert {tool.name for tool in await client.list_tools()} == BOOTSTRAP_ONLY_TOOLS
        joined = (await client.call_tool("join", {"username": "maria", "machine_name": "laptop",
                                                  "os": "LINUX"})).structured_content

    assert joined["team"] == "acme"
    assert {team["name"]: team["role"] for team in
            (await call(server_url, joined["token"], "list_teams"))["teams"]}["acme"] == "MEMBER"
    with session_factory() as session:
        assert session.scalars(select(User.username).order_by(User.username)).all() == [
            "dimitris", "maria"]


async def test_a_used_cancelled_expired_or_unknown_invite_is_not_a_bearer(server_url,
                                                                         session_factory):
    """All four answer the same 401 before any tool runs, so none says it was ever real."""
    dimitris = await join(server_url, "dimitris", "macbook")
    maria = await join(server_url, "maria", "laptop")
    await call(server_url, dimitris, "create_team", name="acme")
    cancelled = (await call(server_url, dimitris, "invite_to_team", team="acme"))["code"]
    expired = (await call(server_url, dimitris, "invite_to_team", team="acme"))["code"]
    used = (await call(server_url, dimitris, "invite_to_team", team="acme"))["code"]
    await call(server_url, maria, "join_team", code=used)
    with session_factory.begin() as session:
        admin = session.scalar(select(User.user_id).where(User.username == "dimitris"))
        invites = session.scalars(select(Invite).order_by(Invite.created_on)).all()
        team_service.cancel_invite(session, admin, "acme", str(invites[0].invite_id))
        invites[1].expires_on = utc_now() - timedelta(seconds=1)
        # Past the moments after its use, when the client that used it may still ask.
        invites[2].used_on = utc_now() - timedelta(minutes=6)

    for code in (cancelled, expired, used, "aistinv_" + "x" * 32):
        with pytest.raises(Exception) as rejection:
            async with client_for(server_url, code) as client:
                await client.list_tools()
        assert "401" in str(rejection.value)
        assert code not in str(rejection.value)
    with session_factory() as session:
        assert sorted(session.scalars(select(User.username))) == ["dimitris", "maria"]


async def test_an_invite_from_someone_taken_off_the_server_is_not_a_bearer(server_url,
                                                                           session_factory):
    """OPERATING.md 'Someone left' deletes the person's machines; their invites die with it."""
    dimitris = await join(server_url, "dimitris", "macbook")
    maria = await join(server_url, "maria", "laptop")
    await _team(server_url, dimitris, maria)
    with session_factory.begin() as session:
        admin = session.scalar(select(User.user_id).where(User.username == "dimitris"))
        team_service.set_member(session, admin, "acme", "maria", can_invite=True)
    hers = (await call(server_url, maria, "invite_to_team", team="acme"))["code"]
    with session_factory.begin() as session:
        gone = session.scalar(select(User.user_id).where(User.username == "maria"))
        session.execute(delete(Machine).where(Machine.user_id == gone))

    with pytest.raises(Exception) as rejection:
        async with client_for(server_url, hers) as client:
            await client.list_tools()
    assert "401" in str(rejection.value)


async def test_a_used_invite_admits_nobody_else_and_a_newer_one_cancels_nothing(server_url):
    dimitris = await join(server_url, "dimitris", "macbook")
    maria = await join(server_url, "maria", "laptop")
    eve = await join(server_url, "eve", "phone")
    await call(server_url, dimitris, "create_team", name="acme")
    first = (await call(server_url, dimitris, "invite_to_team", team="acme"))["code"]
    second = (await call(server_url, dimitris, "invite_to_team", team="acme"))["code"]

    assert (await call(server_url, maria, "join_team", code=first)) == {"team": "acme"}
    refusal = await _refusal(server_url, eve, "join_team", code=first)
    assert "not a team invite code that works" in refusal and first not in refusal
    assert (await call(server_url, eve, "join_team", code=second)) == {"team": "acme"}

    # Moments after its use it still reaches `join` and nothing else, and `join` refuses it.
    async with client_for(server_url, first) as client:
        assert {tool.name for tool in await client.list_tools()} == BOOTSTRAP_ONLY_TOOLS
    assert "not a team invite code that works" in await _refusal(
        server_url, first, "join", username="late", machine_name="box", os="LINUX")



async def test_only_an_admin_can_make_an_invite_code(server_url):
    dimitris = await join(server_url, "dimitris", "macbook")
    maria = await join(server_url, "maria", "laptop")
    await _team(server_url, dimitris, maria)

    assert "Only an admin" in await _refusal(server_url, maria, "invite_to_team", team="acme")


async def test_a_shared_skill_taken_by_a_teammate_downloads_the_same_files(server_url):
    dimitris = await join(server_url, "dimitris", "macbook")
    maria = await join(server_url, "maria", "laptop")
    await _team(server_url, dimitris, maria)
    script = "#!/bin/sh\r\necho hi\r\n"
    pushed = await push(server_url, dimitris, files={"scripts/run.sh": script},
                        executable=frozenset({"scripts/run.sh"}))

    shared = await call(server_url, dimitris, "share_skill", name="wizard", team="acme")
    taken = await call(server_url, maria, "get_skill", name="wizard", team="acme")

    assert shared == {
        "name": "wizard",
        "team": "acme",
        "group": None,
        "revision": 1,
        "created": True,
        "unchanged": False,
        "previous_pushed_by": None,
        "possibly_unrelated": False,
    }
    assert taken["content_hash"] == pushed["content_hash"]
    assert taken["pushed_by"] == "dimitris"
    assert _extracted((await _download(taken["download_url"])).content) == {
        "SKILL.md": (skill_document().encode(), False),
        "scripts/run.sh": (script.encode(), True),
    }
    # Taken, it is one of her own: listed first, with no team.
    assert [(skill["name"], skill["team"])
            for skill in (await call(server_url, maria, "list_skills"))["skills"]] == [
        ("wizard", None), ("wizard", "acme")]


async def test_a_teammates_change_is_offered_and_becomes_an_update_only_once_taken(server_url):
    """A skill is instructions to an agent: someone else's edit waits for its owner's yes."""
    dimitris = await join(server_url, "dimitris", "macbook")
    maria = await join(server_url, "maria", "laptop")
    await _team(server_url, dimitris, maria)
    await push(server_url, dimitris, files={"notes.md": "one\n"})
    await call(server_url, dimitris, "share_skill", name="wizard", team="acme")
    await call(server_url, maria, "get_skill", name="wizard", team="acme")
    on_marias_laptop = {"wizard": local_digests(files={"notes.md": "one\n"})}

    await push(server_url, dimitris, files={"notes.md": "two\n"})
    pushed_only = await call(server_url, maria, "sync", local=on_marias_laptop)
    await call(server_url, dimitris, "share_skill", name="wizard", team="acme")
    offered = await call(server_url, maria, "sync", local=on_marias_laptop)

    assert pushed_only["team_updates"] == [] and pushed_only["up_to_date"] == 1
    assert offered["team_updates"] == [{"name": "wizard", "team": "acme", "from_revision": 1,
                                        "to_revision": 2, "pushed_by": "dimitris"}]
    assert offered["update"] == [] and offered["ask"] == []
    assert offered["up_to_date"] == 1

    await call(server_url, maria, "get_skill", name="wizard", team="acme")
    accepted = await call(server_url, maria, "sync", local=on_marias_laptop)

    assert accepted["team_updates"] == []
    assert accepted["update"] == [{"name": "wizard", "from_revision": 1, "to_revision": 2,
                                   "pushed_by": "dimitris"}]


async def test_a_skill_taken_from_a_team_stays_installed_after_leaving_it(server_url,
                                                                        session_factory):
    """A machine only ever ran its user's own copy, so leaving takes nothing off a computer."""
    dimitris = await join(server_url, "dimitris", "macbook")
    maria = await join(server_url, "maria", "laptop")
    await _team(server_url, dimitris, maria)
    await push(server_url, dimitris)
    await call(server_url, dimitris, "share_skill", name="wizard", team="acme")
    await call(server_url, maria, "get_skill", name="wizard", team="acme")

    # Leaving is a dashboard action; no MCP tool does it.
    with session_factory.begin() as session:
        maria_id = session.scalar(select(User.user_id).where(User.username == "maria"))
        team_service.leave_team(session, maria_id, "acme")
    await push(server_url, dimitris, files={"notes.md": "after she left\n"})
    await call(server_url, dimitris, "share_skill", name="wizard", team="acme")

    mine = await call(server_url, maria, "get_skill", name="wizard")
    report = await call(server_url, maria, "sync", local={"wizard": local_digests()})

    assert mine["revision"] == 1
    assert set(_extracted((await _download(mine["download_url"])).content)) == {"SKILL.md"}
    assert report["up_to_date"] == 1
    assert report["update"] == [] and report["team_updates"] == [] and report["ask"] == []
    assert "acme" not in str(await call(server_url, maria, "list_skills"))
    # The team is now, to her, like one that was never there.
    assert (await _refusal(server_url, maria, "get_skill", name="wizard", team="acme")
            ).replace("acme", "X") == (
        await _refusal(server_url, maria, "get_skill", name="wizard", team="ghost")
            ).replace("ghost", "X")


@pytest.mark.parametrize("tool", sorted(REFUSED_CALLS))
async def test_a_team_you_are_not_in_reads_exactly_like_one_that_does_not_exist(server_url,
                                                                              tool):
    dimitris = await join(server_url, "dimitris", "macbook")
    eve = await join(server_url, "eve", "laptop")
    await _team(server_url, dimitris)
    await push(server_url, dimitris)
    await call(server_url, dimitris, "share_skill", name="wizard", team="acme")
    await push(server_url, eve)

    real = await _refusal(server_url, eve, tool, team="acme", **REFUSED_CALLS[tool])
    imagined = await _refusal(server_url, eve, tool, team="ghost", **REFUSED_CALLS[tool])

    assert "acme" in real
    assert real.replace("acme", "X") == imagined.replace("ghost", "X")


async def test_a_team_you_are_not_in_is_left_out_of_every_listing(server_url):
    dimitris = await join(server_url, "dimitris", "macbook")
    eve = await join(server_url, "eve", "laptop")
    await _team(server_url, dimitris)
    await push(server_url, dimitris)
    await call(server_url, dimitris, "share_skill", name="wizard", team="acme")

    listed = await call(server_url, eve, "list_skills")
    teams = await call(server_url, eve, "list_teams")
    report = await call(server_url, eve, "sync", local={"wizard": local_digests()})

    assert listed == {"skills": []}
    assert teams["teams"] == []
    # A folder of the same name on her disk is hers to back up, and nothing else.
    assert report["backup"] == ["wizard"]
    assert report["team_updates"] == [] and report["ask"] == [] and report["install"] == []


async def test_creating_a_team_says_a_name_is_taken_and_nothing_else(server_url):
    dimitris = await join(server_url, "dimitris", "macbook")
    eve = await join(server_url, "eve", "laptop")
    await _team(server_url, dimitris)

    as_a_team = await _refusal(server_url, eve, "create_team", name="acme")
    as_a_user = await _refusal(server_url, eve, "create_team", name="dimitris")

    assert "already taken by a team or a user" in as_a_team
    assert as_a_team.replace("acme", "X") == as_a_user.replace("dimitris", "X")


async def test_a_download_url_serves_only_the_machines_users_own_skills(server_url,
                                                                      session_factory):
    """No tool mints a ticket for someone else's revision, so this one is signed here, with
    the server's own key, to prove the route checks ownership and not just the signature."""
    dimitris = await join(server_url, "dimitris", "macbook")
    maria = await join(server_url, "maria", "laptop")
    await _team(server_url, dimitris, maria, name="everyone")
    await push(server_url, dimitris)
    await call(server_url, dimitris, "share_skill", name="wizard", team="everyone")
    own_url = (await call(server_url, dimitris, "get_skill", name="wizard"))["download_url"]
    with session_factory() as session:
        marias_laptop = session.scalar(select(Machine.machine_id).where(Machine.name == "laptop"))
        versions = session.scalars(select(SkillVersion.skill_version_id)).all()
    signer = application_context.get_ticket_signer()

    refusals = [
        await _download(own_url.rsplit("/", 1)[0] + "/" + signer.sign_download(DownloadTicket(
            machine_id=marias_laptop,
            skill_version_id=version,
        )))
        for version in versions
    ]

    # His own copy and the one in `everyone`, which she can see and has not taken.
    assert len(versions) == 2
    assert [response.status_code for response in refusals] == [404, 404]
    assert len({response.json()["error"] for response in refusals}) == 1
    assert (await _download(own_url)).status_code == 200


async def test_open_dashboard_returns_a_sign_in_link_on_this_server(server_url):
    token = await join(server_url)

    link = await call(server_url, token, "open_dashboard")

    assert link["url"].startswith(server_url.removesuffix("/mcp") + "/app/login/")
    assert link["url"].rsplit("/", 1)[1].count(".") == 2
    assert link["expires_in_seconds"] == 300
    assert token not in link["url"]


async def test_a_team_invite_code_appears_in_no_log_line(server_url, caplog):
    """Issued, used, refused once used, and used as a bearer: every path it travels."""
    dimitris = await join(server_url, "dimitris", "macbook")
    maria = await join(server_url, "maria", "laptop")
    await call(server_url, dimitris, "create_team", name="acme")

    with caplog.at_level(logging.DEBUG):
        old = (await call(server_url, dimitris, "invite_to_team", team="acme"))["code"]
        new = (await call(server_url, dimitris, "invite_to_team", team="acme"))["code"]
        await call(server_url, maria, "join_team", code=old)
        await _refusal(server_url, maria, "join_team", code="aistinv_wrong")
        async with client_for(server_url, new) as client:
            await client.call_tool("join", {"username": "alex", "machine_name": "thinkpad",
                                            "os": "WINDOWS"})
        with pytest.raises(Exception):
            async with client_for(server_url, "aistinv_wrong") as client:
                await client.list_tools()

    messages = _server_log(caplog)
    assert any("Team invite issued" in message for message in messages)
    assert any("Team joined" in message for message in messages)
    assert any("join_team" in message and "failed" in message for message in messages)
    for message in messages:
        for code in (old, new):
            assert code not in message
            assert code.removeprefix("aistinv_") not in message


async def test_a_dashboard_link_appears_in_no_log_line(server_url, caplog):
    token = await join(server_url)

    with caplog.at_level(logging.DEBUG):
        link = await call(server_url, token, "open_dashboard")

    ticket = link["url"].rsplit("/", 1)[1]
    messages = _server_log(caplog)
    assert any("Dashboard link issued" in message for message in messages)
    for message in messages:
        assert ticket not in message
        # The signature alone is enough to recognize a leak of any part of it.
        assert ticket.split(".")[2] not in message
