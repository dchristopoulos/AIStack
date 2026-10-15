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

# The longest names the server accepts, for checking that the page still fits around them.
LONG_USERNAME = "maximilian-alexandros-papadopoulos-konstantinidis-from-thessalia"
LONG_FULL_NAME = ("Maximilian Alexandros Konstantinos Papadopoulos-Konstantinidis of "
                  "Thessaloniki and the Saronic Isles")
LONG_MACHINE = "build-runner-in-the-basement-rack-number-seventeen-of-twenty-two"
LONG_TEAM = "platform-engineering-and-developer-experience-guild-of-the-north"
DEEP_GROUP = ("engineering/platform-infrastructure-and-reliability/linux-distributions-and-kernels/"
              "kernel-drivers-and-firmware/storage-and-filesystems/"
              "continuous-integration-pipelines/release-candidates-and-backports/"
              "nightly-builds-for-every-architecture")

SKILLS = {
    "code-review": ("Reviews a diff against the team's standards. Use before opening a pull "
                    "request.", {"checklist.md": "- tests cover the change\n- names say what "
                                                 "they mean\n- no secrets in the diff\n"}),
    "release-notes": ("Drafts release notes from merged pull requests. Use when cutting a "
                      "release.", {"template.md": "## Added\n\n## Changed\n\n## Fixed\n"}),
    "sql-style": ("Formats SQL the way the developers agreed. Use when writing or "
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

    async def dashboard_link(self) -> str:
        return (await self.tool("open_dashboard"))["url"]

    async def sign_in(self) -> None:
        assert (await self.browser.get(await self.dashboard_link())).status_code == 303

    async def page(self, route: str, **body) -> dict:
        response = await self.browser.post(f"/api{route}", json=body, headers=REQUEST_HEADER)
        assert response.status_code == 200, (route, response.text)
        return response.json()


async def seed(base_url: str, invite_code: str, long_names: bool = False) -> dict[str, str]:
    """Fill the server and return a dashboard link per person, each good for five minutes.

    With `long_names`, a fourth person adds every name at its longest: see `seed_long_names`.
    """
    dimitris, maria, alex = (Person(base_url, name) for name in ("dimitris", "maria", "alex"))
    await dimitris.join(invite_code, "macbook", "MACOS")
    await dimitris.tool("add_machine", name="desktop", os="LINUX")
    await maria.join(invite_code, "work-laptop", "LINUX")
    await alex.join(invite_code, "thinkpad", "WINDOWS")

    for name in ("code-review", "release-notes", "sql-style", "aistack-api-notes",
                 "pentest-checklist", "meeting-notes", "commit-messages"):
        await dimitris.push(name)
    for person in (dimitris, maria, alex):
        await person.sign_in()
    # The name teammates read beside a username. Alex leaves it empty: it is optional.
    await dimitris.page("/account", full_name="Dimitris Christopoulos")
    await maria.page("/account", full_name="Maria Papadopoulou")

    # The macbook's shared agents folder, which Codex reads, has synced once and holds two skills.
    macbook = (await dimitris.browser.get("/api/state")).json()["machines"][0]["id"]
    await dimitris.tool("sync", local={}, harness="agents")
    for name in ("commit-messages", "meeting-notes"):
        await dimitris.page(f"/skills/{name}/machines/{macbook}", enabled=True, harness="agents")

    # A company team, with a group per discipline and a narrower one inside it.
    await dimitris.page("/teams", name="aistack")
    for person in (maria, alex):
        code = (await dimitris.page("/teams/aistack/invite"))["code"]
        await person.page("/teams/join", code=code)
    await dimitris.page("/teams/aistack/groups", name="developers")
    await dimitris.page("/teams/aistack/groups", name="backend", parent="developers")
    await dimitris.page("/teams/aistack/groups", name="security", private=True)
    await dimitris.page("/teams/aistack/group/members", path="developers", username="maria",
                        member=True)

    for name, group in (("code-review", None), ("release-notes", None),
                        ("sql-style", "developers"), ("aistack-api-notes", "developers/backend"),
                        ("pentest-checklist", "security")):
        await dimitris.page(f"/skills/{name}/share", team="aistack", group=group)
    await dimitris.page("/skills/commit-messages/share", team="aistack")

    # Maria takes two skills and switches them on; then one of them changes under her.
    maria_laptop = (await maria.browser.get("/api/state")).json()["machines"][0]["id"]
    for name in ("code-review", "sql-style"):
        await maria.page("/teams/aistack/take", name=name)
        await maria.page(f"/skills/{name}/machines/{maria_laptop}", enabled=True)
    await dimitris.push("code-review", extra="Also check that migrations are reviewed.\n")
    await dimitris.page("/skills/code-review/share", team="aistack")

    # A friends team that has nothing to do with the company.
    await maria.push("meeting-notes")
    await maria.page("/teams", name="friends")
    await maria.page("/skills/meeting-notes/share", team="friends")

    people = [dimitris, maria, alex]
    if long_names:
        people.append(await seed_long_names(base_url, invite_code, dimitris))
    for person in people:
        await person.browser.aclose()
    return {person.username: await person.dashboard_link() for person in people}


async def seed_long_names(base_url: str, invite_code: str, dimitris: Person) -> Person:
    """Add a person, a computer, a team and a group path, each named at the server's limit.

    Dimitris administers the team and nests the groups eight deep. The new person is in the
    deepest group, shares a skill into it, and takes one of Dimitris's from it.
    """
    person = Person(base_url, LONG_USERNAME)
    await person.join(invite_code, LONG_MACHINE, "LINUX")
    await person.push("meeting-notes")
    await person.sign_in()
    await person.page("/account", full_name=LONG_FULL_NAME)

    await dimitris.page("/teams", name=LONG_TEAM)
    code = (await dimitris.page(f"/teams/{LONG_TEAM}/invite"))["code"]
    await person.page("/teams/join", code=code)
    parent = None
    for name in DEEP_GROUP.split("/"):
        await dimitris.page(f"/teams/{LONG_TEAM}/groups", name=name, parent=parent)
        parent = f"{parent}/{name}" if parent else name
    await dimitris.page(f"/teams/{LONG_TEAM}/group/members", path=DEEP_GROUP,
                        username=LONG_USERNAME, member=True)

    await person.page("/skills/meeting-notes/share", team=LONG_TEAM, group=DEEP_GROUP)
    await dimitris.page("/skills/code-review/share", team=LONG_TEAM, group=DEEP_GROUP)
    machine = (await person.browser.get("/api/state")).json()["machines"][0]["id"]
    await person.page(f"/teams/{LONG_TEAM}/take", name="code-review")
    await person.page(f"/skills/code-review/machines/{machine}", enabled=True)
    return person


def main() -> None:
    links = asyncio.run(seed(sys.argv[1].rstrip("/"), sys.argv[2]))
    print("Seeded: 3 people, 4 computers, teams 'aistack' and 'friends', 3 groups (one nested, "
          "one private).")
    print("Maria has an update to 'code-review' waiting. Alex is in 'aistack' and in no group, "
          "so the private 'security' group is hidden from him.\n")
    print("Dashboard links, each good for five minutes:")
    for username, link in links.items():
        print(f"  {username:<9} {link}")


if __name__ == "__main__":
    main()
