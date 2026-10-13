"""Fill a fresh AIStack server with a small, believable team, and print dashboard links.

For trying the product and for showing it: three people, a company team with nested groups,
skills at each level, and one update waiting to be taken. Everything goes through the same
tools and routes a real user's agent and browser would use, so it is also an end-to-end check.

    python scripts/demo_seed.py http://127.0.0.1:8000 <invite code>

Run it once, against a server nobody has joined yet.
"""

import asyncio
import sys

import httpx
from fastmcp.client import BearerAuth, Client, StreamableHttpTransport

from aistack.services.skill_archive import build_archive

REQUEST_HEADER = {"X-AIStack-Request": "1"}

SKILLS = {
    "code-review": ("Reviews a diff against the team's standards. Use before opening a pull "
                    "request.", {"checklist.md": "- tests cover the change\n- names say what "
                                                 "they mean\n- no secrets in the diff\n"}),
    "release-notes": ("Drafts release notes from merged pull requests. Use when cutting a "
                      "release.", {"template.md": "## Added\n\n## Changed\n\n## Fixed\n"}),
    "sql-style": ("Formats SQL the way the backend group agreed. Use when writing or "
                  "reviewing a query.", {"examples/select.sql": "SELECT id\nFROM skill\n"
                                                                "WHERE archived = FALSE;\n"}),
    "aistack-api-notes": ("How AIStack's own routes and tools are laid out. Use when changing "
                          "the server.", {"routes.md": "- /mcp: the tools\n- /transfer: "
                                                       "bytes\n- /api: the dashboard\n"}),
    "pentest-checklist": ("Steps for a first-pass security review of a web service. Use "
                          "before a release.", {"steps.md": "1. authentication\n2. "
                                                            "authorization\n3. input\n"}),
    "meeting-notes": ("Turns a rough transcript into decisions and actions. Use after a "
                      "meeting.", {}),
    "commit-messages": ("Writes a commit message that explains why. Use when committing.", {}),
}


def archive(name: str, extra: str = "") -> bytes:
    description, files = SKILLS[name]
    document = f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n\n{extra}"
    return build_archive([("SKILL.md", document.encode(), False),
                          *((path, content.encode(), False)
                            for path, content in files.items())])


class Person:
    """One user: their machine token for the tools, and a signed-in browser for the page."""

    def __init__(self, base_url: str, username: str):
        self.base_url, self.username = base_url, username
        self.token = ""
        self.browser = httpx.AsyncClient(base_url=base_url)

    async def call(self, bearer: str, tool: str, **arguments) -> dict:
        transport = StreamableHttpTransport(f"{self.base_url}/mcp", auth=BearerAuth(bearer))
        async with Client(transport) as client:
            return (await client.call_tool(tool, arguments)).structured_content

    async def tool(self, tool: str, **arguments) -> dict:
        return await self.call(self.token, tool, **arguments)

    async def join(self, invite_code: str, machine_name: str, os: str) -> None:
        joined = await self.call(invite_code, "join", username=self.username,
                                 machine_name=machine_name, os=os)
        self.token = joined["token"]

    async def push(self, name: str, extra: str = "") -> None:
        issued = await self.tool("push_skill", name=name)
        async with httpx.AsyncClient() as http:
            stored = (await http.put(issued["upload_url"], content=archive(name, extra))).json()
        assert "revision" in stored, stored

    async def sign_in(self) -> str:
        link = (await self.tool("open_dashboard"))["url"]
        assert (await self.browser.get(link)).status_code == 303
        return (await self.tool("open_dashboard"))["url"]

    async def page(self, route: str, **body) -> dict:
        response = await self.browser.post(f"/api{route}", json=body, headers=REQUEST_HEADER)
        assert response.status_code == 200, (route, response.text)
        return response.json()


async def seed(base_url: str, invite_code: str) -> None:
    dimitris, maria, alex = (Person(base_url, name) for name in ("dimitris", "maria", "alex"))
    await dimitris.join(invite_code, "macbook", "MACOS")
    await dimitris.tool("add_machine", name="desktop", os="LINUX")
    await maria.join(invite_code, "work-laptop", "LINUX")
    await alex.join(invite_code, "thinkpad", "WINDOWS")

    for name in ("code-review", "release-notes", "sql-style", "aistack-api-notes",
                 "pentest-checklist", "meeting-notes", "commit-messages"):
        await dimitris.push(name)
    links = {person.username: await person.sign_in() for person in (dimitris, maria, alex)}

    # A company team, with a group per discipline and a project inside one of them.
    await dimitris.page("/teams", name="acme")
    code = (await dimitris.page("/teams/acme/invite"))["code"]
    for person in (maria, alex):
        await person.page("/teams/join", code=code)
    await dimitris.page("/teams/acme/groups", name="backend")
    await dimitris.page("/teams/acme/groups", name="aistack", parent="backend")
    await dimitris.page("/teams/acme/groups", name="security", private=True)
    await dimitris.page("/teams/acme/group/members", path="backend", username="maria",
                        member=True)

    for name, group in (("code-review", None), ("release-notes", None),
                        ("sql-style", "backend"), ("aistack-api-notes", "backend/aistack"),
                        ("pentest-checklist", "security")):
        await dimitris.page(f"/skills/{name}/share", team="acme", group=group)
    await dimitris.page("/skills/commit-messages/share", team="everyone")

    # Maria takes two skills and switches them on; then one of them changes under her.
    maria_laptop = (await maria.browser.get("/api/state")).json()["machines"][0]["id"]
    for name in ("code-review", "sql-style"):
        await maria.page("/teams/acme/take", name=name)
        await maria.page(f"/skills/{name}/machines/{maria_laptop}", enabled=True)
    await dimitris.push("code-review", extra="Also check that migrations are reviewed.\n")
    await dimitris.page("/skills/code-review/share", team="acme")

    # A friends team that has nothing to do with the company.
    await maria.push("meeting-notes")
    await maria.page("/teams", name="friends")
    await maria.page("/skills/meeting-notes/share", team="friends")

    for person in (dimitris, maria, alex):
        await person.browser.aclose()

    print("Seeded: 3 people, 4 computers, teams 'acme' and 'friends', 3 groups (one nested, "
          "one private).")
    print("Maria has an update to 'code-review' waiting. Alex is in 'acme' and in no group, "
          "so the private 'security' group is hidden from him.\n")
    print("Dashboard links, each good for five minutes:")
    for username, link in links.items():
        print(f"  {username:<9} {link}")


if __name__ == "__main__":
    asyncio.run(seed(sys.argv[1].rstrip("/"), sys.argv[2]))
