"""Drive a running AIStack container the way two machines would, from outside it.

CI runs this against the built image: once on a fresh volume, then again after the container
has been restarted, to prove the volume is where the state lives.

    python scripts/container_smoke.py fresh     http://127.0.0.1:8000 <invite code> <state file>
    python scripts/container_smoke.py restarted http://127.0.0.1:8000 <invite code> <state file>

Around a backup and a restore, `changed` adds a user after the backup, and `restored` finds
what was there before it and not that user.
"""

import asyncio
import io
import json
import pathlib
import sys
import tarfile

import httpx
from fastmcp.client import BearerAuth, Client, StreamableHttpTransport

from aistack.services.skill_archive import build_archive

SKILL_NAME = "container-proof"
TEAM = "ci"
SKILL_FILES = [
    ("SKILL.md", f"---\nname: {SKILL_NAME}\ndescription: Proves the container works.\n---\n"
                 "\n# Container proof\n".encode(), False),
    ("scripts/run.sh", b"#!/bin/sh\necho proof\n", True),
]


async def call(base_url: str, bearer: str, tool: str, **arguments) -> dict:
    transport = StreamableHttpTransport(f"{base_url}/mcp", auth=BearerAuth(bearer))
    async with Client(transport) as client:
        return (await client.call_tool(tool, arguments)).structured_content


async def fresh(base_url: str, invite_code: str, state_file: pathlib.Path) -> None:
    """A joins and invites B with a team link; A pushes and shares, B takes the same bytes."""
    # The setup page and the sync skill are package data: this is what proves the image
    # actually carries them.
    async with httpx.AsyncClient() as http:
        setup = await http.get(f"{base_url}/setup")
        sync_skill = await http.get(f"{base_url}/setup/sync-aistack/SKILL.md")
    assert setup.status_code == 200 and "claude mcp add" in setup.text, setup.text[:200]
    assert sync_skill.text.startswith("---\nname: sync-aistack\n"), sync_skill.text[:200]

    machine_a = (await call(base_url, invite_code, "join", username="ci-a",
                            machine_name="runner-a", os="LINUX"))["token"]
    await call(base_url, machine_a, "create_team", name=TEAM)
    team_code = (await call(base_url, machine_a, "invite_to_team", team=TEAM))["code"]
    # B's account comes from the team's invite code alone (ADR-0019).
    joined_b = await call(base_url, team_code, "join", username="ci-b",
                          machine_name="runner-b", os="LINUX")
    assert joined_b["team"] == TEAM, joined_b
    machine_b = joined_b["token"]

    issued = await call(base_url, machine_a, "push_skill", name=SKILL_NAME)
    async with httpx.AsyncClient() as http:
        pushed = (await http.put(issued["upload_url"], content=build_archive(SKILL_FILES))).json()
    assert pushed["revision"] == 1 and pushed["created"] is True, pushed

    # A push is private: the other user sees it only once it is shared.
    assert (await call(base_url, machine_b, "list_skills"))["skills"] == []
    await call(base_url, machine_a, "share_skill", name=SKILL_NAME, team=TEAM)
    listing = await call(base_url, machine_b, "list_skills")
    assert [(skill["name"], skill["team"]) for skill in listing["skills"]] == [
        (SKILL_NAME, TEAM)], listing

    skill = await call(base_url, machine_b, "get_skill", name=SKILL_NAME, team=TEAM)
    async with httpx.AsyncClient() as http:
        archive = (await http.get(skill["download_url"])).content
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
        installed = {member.name: (tar.extractfile(member).read(), bool(member.mode & 0o111))
                     for member in tar}
    assert installed == {path: (content, executable)
                         for path, content, executable in SKILL_FILES}, installed

    state_file.write_text(json.dumps({"machine_b": machine_b,
                                      "content_hash": pushed["content_hash"]}))
    print("fresh: joined two machines, pushed and shared from one, took it byte-identical on "
          "the other")


async def restarted(base_url: str, invite_code: str, state_file: pathlib.Path) -> None:
    """After a restart: the token still works and the skill B took is still its own."""
    state = json.loads(state_file.read_text())

    skill = await call(base_url, state["machine_b"], "get_skill", name=SKILL_NAME)
    assert skill["content_hash"] == state["content_hash"], skill
    assert skill["pushed_by"] == "ci-a", skill

    async with Client(StreamableHttpTransport(f"{base_url}/mcp",
                                              auth=BearerAuth(invite_code))) as client:
        rejoin = await client.call_tool("join", {"username": "ci-a", "machine_name": "again",
                                                 "os": "LINUX"}, raise_on_error=False)
    assert rejoin.is_error and "already taken" in rejoin.content[0].text, rejoin

    print("restarted: the machine token, the user, and the skill all survived")


LATE_USER = "ci-after-backup"


async def changed(base_url: str, invite_code: str, state_file: pathlib.Path) -> None:
    await call(base_url, invite_code, "join", username=LATE_USER, machine_name="late",
               os="LINUX")
    print("changed: joined a user after the backup")


async def restored(base_url: str, invite_code: str, state_file: pathlib.Path) -> None:
    """After the restore: what the backup held is there, and the later user is not."""
    await restarted(base_url, invite_code, state_file)
    again = await call(base_url, invite_code, "join", username=LATE_USER, machine_name="late",
                       os="LINUX")
    assert again["token"], again
    print("restored: the backup's state is back, and nothing written after it")


if __name__ == "__main__":
    phase, base_url, invite_code, state_path = sys.argv[1:5]
    phases = {"fresh": fresh, "restarted": restarted, "changed": changed, "restored": restored}
    asyncio.run(phases[phase](
        base_url.rstrip("/"), invite_code, pathlib.Path(state_path)))
