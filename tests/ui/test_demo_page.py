"""The page opened from disk, which shows demo data (IMP-17): every screen draws, and its
script throws nothing. The demo backend is JavaScript nobody else runs."""

import pathlib

import pytest
from playwright.async_api import expect

pytestmark = pytest.mark.anyio

PAGE = pathlib.Path(__file__).parents[2] / "src" / "aistack" / "bundled" / "dashboard.html"


async def test_every_screen_of_the_demo_draws_without_an_error(browser):
    page = await browser.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("console", lambda message: errors.append(message.text)
            if message.type == "error" else None)
    await page.goto(PAGE.as_uri() + "?demo")
    await expect(page.get_by_text("Demo data")).to_be_visible()

    screens = await page.locator("aside a[href^='#/']").evaluate_all(
        "links => [...new Set(links.map(link => link.getAttribute('href')))]")
    assert len(screens) > 5
    for screen in screens:
        await page.evaluate("hash => { location.hash = hash; }", screen)
        await expect(page.locator("main h1")).to_be_visible()

    assert errors == []
    await page.close()
