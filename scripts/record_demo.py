"""Retake everything the README shows: the screenshots, the animated demo, and its frames.

    python scripts/record_demo.py http://127.0.0.1:8000 <invite code> <output directory>

Run it against a server nobody has joined yet. It fills the server with `demo_seed.py`,
drives the real page in a browser, and writes:

    docs/images/dashboard-*.png   the README's screenshots
    docs/images/demo.png          the README's demo, an animated PNG of a few held frames
    <output>/frames/, frames.txt  every frame of the full demo, for `encode_frames.swift`

The demo is captured as screenshots and not as Playwright's own video, whose low fixed
bitrate smears small text. The pointer and the caption are drawn by this script; nothing
else on screen is. See docs/SHOWCASE.md for the storyboard and why it is what it is.
"""

import asyncio
import pathlib
import struct
import sys
import zlib

from playwright.async_api import Locator, Page, async_playwright

import demo_seed

ROOT = pathlib.Path(__file__).parents[1]
IMAGES = ROOT / "docs" / "images"
FPS = 30
VIEWPORT = {"width": 1280, "height": 720}
SCALE = 1.5  # 1280x720 on the page, 1920x1080 in the video

# The pointer and the caption live in the browser's top layer, above an open dialog. The
# caption sits in the top bar, right of the breadcrumb, where it covers no content and no toast.
OVERLAY = """() => {
  const box = document.createElement('div');
  box.id = 'reel';
  box.setAttribute('popover', 'manual');
  box.style.cssText = 'position:fixed;inset:0;width:100%;height:100%;margin:0;padding:0;border:0;' +
    'background:none;pointer-events:none;overflow:visible';
  const ring = document.createElement('div');
  ring.id = 'reel-ring';
  ring.style.cssText = 'position:absolute;width:36px;height:36px;margin:-18px 0 0 -18px;' +
    'border-radius:50%;background:rgba(0,112,243,.28);opacity:0';
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.id = 'reel-pointer';
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.style.cssText = 'position:absolute;width:24px;height:24px;filter:drop-shadow(0 1px 2px rgba(0,0,0,.35))';
  const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  path.setAttribute('d', 'M4 2l15 9.5-6.6 1.3L16.6 21l-3 1.3-4-8L5 18.5z');
  path.setAttribute('fill', '#111');
  path.setAttribute('stroke', '#fff');
  path.setAttribute('stroke-width', '1.4');
  path.setAttribute('stroke-linejoin', 'round');
  svg.append(path);
  const caption = document.createElement('div');
  caption.id = 'reel-caption';
  caption.style.cssText = 'position:absolute;left:58%;top:6px;transform:translateX(-50%);width:max-content;' +
    'max-width:800px;padding:8px 18px;border-radius:9px;background:rgba(10,10,10,.92);color:#fff;' +
    'font:500 18px/1.4 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;text-align:center;' +
    'box-shadow:0 0 0 1px rgba(255,255,255,.14),0 10px 30px rgba(0,0,0,.35);opacity:0';
  box.append(ring, svg, caption);
  document.documentElement.append(box);
  box.showPopover();
}"""


class Reel:
    """The frames of the demo, and the pointer that moves through them."""

    def __init__(self, out: pathlib.Path):
        self.frames = out / "frames"
        self.frames.mkdir(parents=True, exist_ok=True)
        self.timeline: list[tuple[str, int]] = []  # (file, how many frames it is held for)
        self.keys: list[tuple[bytes, float]] = []  # (small screenshot, seconds) for the README
        self.page: Page | None = None
        self.at = (700.0, 110.0)  # over the page's heading band, where nothing reacts to it

    async def use(self, page: Page) -> None:
        self.page = page
        await page.evaluate(OVERLAY)
        await self._place(*self.at)

    async def _place(self, x: float, y: float) -> None:
        self.at = (x, y)
        await self.page.mouse.move(x, y)
        await self.page.evaluate(
            """([x, y]) => {
              const box = document.getElementById('reel');
              box.hidePopover(); box.showPopover();  // back on top of a dialog opened since
              for (const id of ['reel-pointer', 'reel-ring']) {
                const part = document.getElementById(id);
                part.style.left = x + 'px'; part.style.top = y + 'px';
              }
            }""", [x, y])

    async def shot(self, repeat: int = 1) -> None:
        name = f"{len(self.timeline):05d}.png"
        await self.page.screenshot(path=str(self.frames / name))
        self.timeline.append((name, repeat))

    async def hold(self, seconds: float) -> None:
        """Let what just happened settle on screen: a few live frames, then the last one held."""
        live = min(8, int(seconds * FPS))
        for _ in range(live):
            await self.shot()
        await self.shot(max(1, int(seconds * FPS) - live))

    async def caption(self, text: str) -> None:
        await self.page.evaluate(
            """text => { const c = document.getElementById('reel-caption');
                         c.textContent = text; c.style.opacity = text ? 1 : 0; }""", text)

    async def key(self, seconds: float = 2.8) -> None:
        """Keep this moment for the README's animation, at one pixel per CSS pixel."""
        self.keys.append((await self.page.screenshot(scale="css"), seconds))

    async def move_to(self, target: Locator, seconds: float = 0.7) -> None:
        await target.scroll_into_view_if_needed()
        box = await target.bounding_box()
        end = (box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        start, steps = self.at, max(2, int(seconds * FPS))
        for step in range(1, steps + 1):
            eased = 1 - (1 - step / steps) ** 3
            await self._place(start[0] + (end[0] - start[0]) * eased,
                              start[1] + (end[1] - start[1]) * eased)
            await self.shot()

    async def click(self, target: Locator) -> None:
        await self.move_to(target)
        await self.page.evaluate("document.getElementById('reel-ring').style.opacity = 1")
        await self.shot(3)
        await target.click()
        await self.page.evaluate("document.getElementById('reel-ring').style.opacity = 0")
        await self._place(*self.at)
        await self.hold(0.5)

    async def scroll(self, pixels: int) -> None:
        for _ in range(abs(pixels) // 20):
            await self.page.mouse.wheel(0, 20 if pixels > 0 else -20)
            await self.shot()

    def write_manifest(self, out: pathlib.Path) -> None:
        (out / "frames.txt").write_text(
            "".join(f"{self.frames / name}\t{repeat}\n" for name, repeat in self.timeline))


def animated_png(frames: list[tuple[bytes, float]]) -> bytes:
    """Join same-sized PNGs into one animated PNG, each held for its own number of seconds.

    An animated PNG is a PNG whose first frame every viewer can show, plus the other frames
    in chunks an ordinary viewer skips. Nothing is re-encoded.
    """
    def chunks(png: bytes):
        at = 8
        while at < len(png):
            length, kind = struct.unpack(">I4s", png[at:at + 8])
            yield kind, png[at + 8:at + 8 + length]
            at += 12 + length

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    header = next(data for kind, data in chunks(frames[0][0]) if kind == b"IHDR")
    width, height = struct.unpack(">II", header[:8])
    out = [b"\x89PNG\r\n\x1a\n", chunk(b"IHDR", header),
           chunk(b"acTL", struct.pack(">II", len(frames), 0))]
    sequence = 0
    for index, (png, seconds) in enumerate(frames):
        assert next(data for kind, data in chunks(png) if kind == b"IHDR") == header
        out.append(chunk(b"fcTL", struct.pack(">IIIIIHHBB", sequence, width, height, 0, 0,
                                              round(seconds * 100), 100, 0, 0)))
        sequence += 1
        for kind, data in chunks(png):
            if kind != b"IDAT":
                continue
            if index == 0:
                out.append(chunk(b"IDAT", data))
            else:
                out.append(chunk(b"fdAT", struct.pack(">I", sequence) + data))
                sequence += 1
    out.append(chunk(b"IEND", b""))
    return b"".join(out)


CLOSING = """<!doctype html><meta charset=utf-8><body style="margin:0;height:100vh;display:grid;
place-items:center;background:#000;color:#ededed;font:16px -apple-system,BlinkMacSystemFont,
'Segoe UI',sans-serif;text-align:center"><div><div style="font:600 64px/1.1 inherit;
letter-spacing:-.04em;font-family:inherit">AIStack</div><p style="font-size:26px;line-height:1.4;
color:#a1a1a1;max-width:820px;margin:24px auto 36px">A self-hosted home for your AI coding skills:
backed up from every computer you use, shared with your team on your terms.</p><p style="font:500
22px ui-monospace,Menlo,monospace">github.com/dchristopoulos/AIStack</p></div>"""


async def opened(browser, link: str, scheme: str, viewport=VIEWPORT, scale=SCALE) -> Page:
    context = await browser.new_context(viewport=viewport, device_scale_factor=scale,
                                        color_scheme=scheme)
    page = await context.new_page()
    await page.goto(link)
    await page.get_by_role("heading", name="My skills", level=1).wait_for()
    return page


async def stills(browser, base_url: str, links: dict[str, str]) -> None:
    """The README's four screenshots, before the demo changes anything."""
    wide = {"width": 1440, "height": 900}
    page = await opened(browser, links["dimitris"], "light", wide, 2)
    for name, route in (("my-skills", "#/mine"), ("team", "#/t/acme/skills"),
                        ("groups", "#/t/acme/groups")):
        await page.goto(f"{base_url}/app{route}")
        await page.wait_for_timeout(400)
        await page.screenshot(path=str(IMAGES / f"dashboard-{name}.png"))
    await page.context.close()
    page = await opened(browser, links["maria"], "dark", wide, 2)
    await page.wait_for_timeout(400)
    await page.screenshot(path=str(IMAGES / "dashboard-update-dark.png"))
    await page.context.close()


async def demo(browser, links: dict[str, str], reel: Reel) -> None:
    page = await opened(browser, links["dimitris"], "light")
    await reel.use(page)
    await reel.caption("Every skill on your computers, backed up to a space only you see.")
    await reel.hold(3.2)
    await reel.key()

    await reel.caption("You choose which computer runs which skill.")
    await reel.click(page.get_by_role("switch", name="aistack-api-notes on desktop"))
    await reel.hold(2.4)
    await reel.key()

    await reel.caption("Share one with your team, or with a single group inside it.")
    await reel.scroll(140)
    row = page.get_by_role("row").filter(has_text="meeting-notes")
    await reel.click(row.get_by_role("button", name="Share"))
    dialog = page.get_by_role("dialog")
    await reel.click(dialog.get_by_role("radio", name="backend/aistack"))
    await reel.hold(1.2)
    await reel.key(2.2)
    await reel.click(dialog.get_by_role("button", name="Share", exact=True))
    await reel.hold(2.4)
    await reel.key()

    await reel.caption("Teams and their groups are on the left, like channels. A lock marks a private one.")
    navigation = page.get_by_role("navigation", name="Main")
    await reel.click(navigation.get_by_role("link", name="aistack"))
    await reel.hold(3.0)
    await reel.key()
    await page.context.close()

    page = await opened(browser, links["maria"], "dark")
    await reel.use(page)
    await reel.caption("A teammate's change is never applied for you. It is offered, with their name.")
    await reel.hold(3.4)
    await reel.key(3.2)
    await reel.caption("You say yes, and it reaches each computer at its next sync.")
    await reel.click(page.get_by_role("button", name="Take update"))
    await reel.hold(2.8)
    await reel.key()

    await page.set_content(CLOSING)
    reel.page = page
    await reel.shot(int(3.5 * FPS))
    reel.keys.append((await page.screenshot(scale="css"), 3.5))
    await page.context.close()


async def main() -> None:
    base_url, invite_code, out = sys.argv[1].rstrip("/"), sys.argv[2], pathlib.Path(sys.argv[3])
    reel = Reel(out)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        # One set of links serves both passes: a link is good for five minutes, not for one use.
        links = await demo_seed.seed(base_url, invite_code)
        await stills(browser, base_url, links)
        await demo(browser, links, reel)
        await browser.close()
    reel.write_manifest(out)
    (IMAGES / "demo.png").write_bytes(animated_png(reel.keys))
    seconds = sum(repeat for _, repeat in reel.timeline) / FPS
    print(f"{len(reel.timeline)} screenshots, {seconds:.0f} seconds of video at {FPS} fps.")
    print(f"README demo: {IMAGES / 'demo.png'} ({len(reel.keys)} frames).")
    print(f"For an MP4: swift scripts/encode_frames.swift {out / 'frames.txt'} {out / 'demo.mp4'}")


if __name__ == "__main__":
    asyncio.run(main())
