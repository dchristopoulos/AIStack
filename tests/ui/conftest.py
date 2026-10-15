import importlib.util
import os
import pathlib

import pytest

# The page is served by the same in-process server the MCP tests start.
from tests.conftest import INVITE_CODE
from tests.mcp.conftest import (  # noqa: F401
    anyio_backend_fixture,
    server_url_fixture,
    session_factory_fixture,
)

playwright_api = pytest.importorskip("playwright.async_api")

# Chromium unless told otherwise: AISTACK_UI_BROWSER=firefox or webkit runs the same tests there.
BROWSER = os.environ.get("AISTACK_UI_BROWSER", "chromium")

_SEED_SCRIPT = pathlib.Path(__file__).parents[2] / "scripts" / "demo_seed.py"


def pytest_configure(config):
    config.addinivalue_line("markers", "long_names: seed a fourth person whose names are all as "
                                       "long as the server allows")


def _demo_seed():
    spec = importlib.util.spec_from_file_location("demo_seed", _SEED_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(name="links")
async def links_fixture(server_url, request) -> dict[str, str]:
    """A server filled by the demo script, and a sign-in link per person.

    dimitris administers `aistack`; maria is in its `developers` group and has an update
    waiting; alex is in `aistack` and in no group, so the private `security` group is hidden
    from them. A test marked `long_names` also gets a fourth person whose names, computer,
    team and group path are all as long as the server allows.
    """
    return await _demo_seed().seed(server_url.removesuffix("/mcp"), INVITE_CODE,
                                   long_names=request.node.get_closest_marker("long_names")
                                   is not None)


@pytest.fixture(name="browser")
async def browser_fixture():
    async with playwright_api.async_playwright() as playwright:
        try:
            browser = await getattr(playwright, BROWSER).launch()
        except playwright_api.Error as error:
            pytest.skip(f"{BROWSER} for Playwright is not installed: run "
                        f"'poetry run playwright install {BROWSER}'. ({error.message[:80]})")
        yield browser
        await browser.close()


class Opened:
    """One person's browser tab, with everything that went wrong in it collected."""

    def __init__(self, page, base_url: str):
        self.page, self.base_url = page, base_url
        self.console_errors: list[str] = []
        self.foreign_requests: list[str] = []
        page.on("console", lambda message: self.console_errors.append(message.text)
                if message.type == "error" else None)
        page.on("pageerror", lambda error: self.console_errors.append(str(error)))
        page.on("request", lambda request: self.foreign_requests.append(request.url)
                if not request.url.startswith((base_url, "data:")) else None)

    async def state(self) -> dict:
        """What the server holds for this person, read through their own session."""
        return await (await self.page.request.get(f"{self.base_url}/api/state")).json()


@pytest.fixture(name="sign_in")
async def sign_in_fixture(browser, server_url, links):
    """Open the dashboard as one of the seeded people, each in a browser context of their own."""
    base_url = server_url.removesuffix("/mcp")
    contexts = []

    async def sign_in(username: str, viewport: tuple[int, int] = (1280, 900)) -> Opened:
        context = await browser.new_context(viewport={"width": viewport[0],
                                                      "height": viewport[1]})
        contexts.append(context)
        page = await context.new_page()
        opened = Opened(page, base_url)
        await page.goto(links[username])
        await page.get_by_role("heading", name="Library", level=1).wait_for()
        return opened

    yield sign_in
    for context in contexts:
        await context.close()
