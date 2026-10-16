"""Retake the README's screenshots from a freshly seeded server.

    python scripts/retake_screenshots.py http://127.0.0.1:8000 <invite code>

Run it against a server nobody has joined yet: it fills it with `demo_seed.py` first.
"""

import asyncio
import pathlib
import sys

import demo_seed
from playwright.async_api import async_playwright

IMAGES = pathlib.Path(__file__).parents[1] / "docs" / "images"
WIDE = {"width": 1440, "height": 900}


async def main() -> None:
    base_url, invite_code = sys.argv[1].rstrip("/"), sys.argv[2]
    links = await demo_seed.seed(base_url, invite_code)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        # A computer's page is addressed by its id, so it is opened from the sidebar instead.
        shots = [("dimitris", "light", "#/library", "library"), ("dimitris", "light", "macbook / Claude Code", "computer"),
                 ("dimitris", "light", "#/t/aistack/skills", "team"),
                 ("dimitris", "light", "#/t/aistack/groups", "groups"), ("maria", "dark", "#/library", "update-dark")]
        # A sign-in link works once, so each person signs in once and keeps the tab.
        pages = {}
        for username, scheme, route, name in shots:
            if username not in pages:
                context = await browser.new_context(viewport=WIDE, device_scale_factor=2)
                pages[username] = await context.new_page()
                await pages[username].goto(links[username])
                await pages[username].get_by_role("heading", name="Library", level=1).wait_for()
            page = pages[username]
            await page.emulate_media(color_scheme=scheme)
            if route.startswith("#"):
                await page.goto(f"{base_url}/app{route}")
            else:
                await page.get_by_role("navigation", name="Main").get_by_role("link", name=route).click()
            await page.wait_for_timeout(400)
            await page.screenshot(path=str(IMAGES / f"dashboard-{name}.png"))
        await browser.close()
    print(f"Retook {len(shots)} screenshots in {IMAGES}.")


if __name__ == "__main__":
    asyncio.run(main())
