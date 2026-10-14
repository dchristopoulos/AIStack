"""Retake the README's screenshots from a freshly seeded server.

    python scripts/retake_screenshots.py http://127.0.0.1:8000 <invite code>

Run it against a server nobody has joined yet: it fills it with `demo_seed.py` first.
"""

import asyncio
import pathlib
import sys

from playwright.async_api import async_playwright

import demo_seed

IMAGES = pathlib.Path(__file__).parents[1] / "docs" / "images"
WIDE = {"width": 1440, "height": 900}


async def main() -> None:
    base_url, invite_code = sys.argv[1].rstrip("/"), sys.argv[2]
    links = await demo_seed.seed(base_url, invite_code)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        shots = [("dimitris", "light", "#/mine", "my-skills"), ("dimitris", "light", "#/t/acme/skills", "team"),
                 ("dimitris", "light", "#/t/acme/groups", "groups"), ("maria", "dark", "#/mine", "update-dark")]
        for username, scheme, route, name in shots:
            context = await browser.new_context(viewport=WIDE, device_scale_factor=2, color_scheme=scheme)
            page = await context.new_page()
            await page.goto(links[username])
            await page.get_by_role("heading", name="My skills", level=1).wait_for()
            await page.goto(f"{base_url}/app{route}")
            await page.wait_for_timeout(400)
            await page.screenshot(path=str(IMAGES / f"dashboard-{name}.png"))
            await context.close()
        await browser.close()
    print(f"Retook {len(shots)} screenshots in {IMAGES}.")


if __name__ == "__main__":
    asyncio.run(main())
