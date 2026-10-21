"""Files AIStack ships and serves as they are: the setup instructions, the sync skill, and
the dashboard page, plus local mode's own setup and sync skill.

They live inside the package so the container image carries them, and a new user's agent can
fetch them from the server it is joining. A fresh vault cannot install the skill that talks
to it, so that one skill comes from here.
"""

import base64
import hashlib
from importlib import resources

SYNC_SKILL_NAME = "sync-aistack"

# The logo, for the browser tab of every page the server answers with. Inline, because those
# pages load nothing from anywhere; without it a browser asks for /favicon.ico on each load.
ICON_LINK = (
    '<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns=\'http://www.w3.org/2000/svg\' '
    "viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='8' fill='%232259d6'/%3E"
    "%3Cpath d='M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5' "
    "transform='translate(5 5) scale(.92)' fill='none' stroke='white' stroke-width='2.2' "
    "stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E\">")

# The dashboard's tokens (docs/design-system.md) for a page outside it, following the system's
# light or dark theme: such a page has no settings to choose one.
_PLAIN_STYLE = (
    ":root{--bg:#f4f4f6;--surface:#fff;--surface-2:#efeff2;--border:#e2e2e7;--border-strong:#cdcdd4;"
    "--text:#18181b;--muted:#585962;--accent:#2259d6;--on-accent:#fff;"
    "--accent-text:color-mix(in srgb,var(--accent) 88%,var(--text));"
    "--font:-apple-system,BlinkMacSystemFont,'Segoe UI Variable Text','Segoe UI',system-ui,Roboto,"
    "sans-serif;--mono:ui-monospace,SFMono-Regular,'SF Mono','Cascadia Mono',Menlo,Consolas,"
    "monospace}"
    "@media (prefers-color-scheme:dark){:root{--bg:#161719;--surface:#1e1f23;--surface-2:#26272c;"
    "--border:#2e2f35;--border-strong:#41434a;--text:#ececef;--muted:#a6a8b0;--accent:#7aa7ff;"
    "--on-accent:#0c1a36}}"
    "*{box-sizing:border-box}"
    "body{margin:0;background:var(--bg);color:var(--text);font:14px/1.55 var(--font)}"
    "main{max-width:36rem;margin:0 auto;padding:10vh 16px 48px}"
    ".brand{display:flex;align-items:center;gap:10px;margin-bottom:28px;font-weight:600;"
    "font-size:15px;letter-spacing:-.02em}"
    ".logo{width:26px;height:26px;border-radius:8px;background:var(--accent);"
    "color:var(--on-accent);display:grid;place-items:center}"
    "h1{font-size:24px;font-weight:600;letter-spacing:-.02em;line-height:1.25;margin:0 0 8px}"
    "h2{font-size:15px;font-weight:600;margin:0 0 4px}"
    "h1 code{font-size:.9em}p{margin:0 0 12px}"
    ".lede{color:var(--muted);font-size:15px;margin-bottom:20px}"
    "section{background:var(--surface);border:1px solid var(--border);border-radius:12px;"
    "padding:18px 20px;margin-top:12px}section>:last-child{margin-bottom:0}"
    "section p{color:var(--muted)}a{color:var(--accent-text)}"
    "code,pre{font-family:var(--mono);font-size:13px}"
    "pre{white-space:pre-wrap;overflow-wrap:anywhere;margin:0 0 12px;padding:10px 12px;"
    "background:var(--surface-2);border-radius:8px;color:var(--text)}"
    "button{font:500 13.5px var(--font);height:32px;padding:0 12px;border-radius:8px;"
    "cursor:pointer;border:1px solid var(--accent);background:var(--accent);"
    "color:var(--on-accent)}"
    "pre+button{margin:-4px 0 12px;background:var(--surface);color:var(--text);"
    "border-color:var(--border-strong)}"
    ":focus-visible{outline:2px solid var(--accent);outline-offset:2px}")

_LOGO = ('<span class=logo><svg viewBox="0 0 24 24" width=14 height=14 fill=none '
         'stroke=currentColor stroke-width=2 stroke-linecap=round stroke-linejoin=round '
         'aria-hidden=true><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/>'
         '</svg></span>')

# A Copy button under every sentence to paste. Made by the script, so a browser that runs no
# script shows no button that does nothing; the clipboard needs https or localhost, so
# anywhere else the button selects the sentence and copies it the old way.
PLAIN_PAGE_SCRIPT = (
    "for(const p of document.querySelectorAll('pre')){const b=document.createElement('button');"
    "b.type='button';b.textContent='Copy';b.onclick=async()=>{try{"
    "await navigator.clipboard.writeText(p.textContent)}catch{"
    "getSelection().selectAllChildren(p);document.execCommand('copy')}"
    "b.textContent='Copied'};p.after(b)}")


def script_source(script: str) -> str:
    """The Content-Security-Policy source that lets exactly this inline script run."""
    return f"'sha256-{base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()}'"


def plain_page(title: str, body: str) -> str:
    """A page the server answers with outside the dashboard, such as the signed-out and invite
    pages: the logo, a language, a main landmark, and the dashboard's tokens in both themes.
    `title` and `body` are HTML the caller has escaped. Its headers allow `PLAIN_PAGE_SCRIPT`
    by `script_source`."""
    return ("<!doctype html><html lang=en><meta charset=utf-8>"
            '<meta name=viewport content="width=device-width,initial-scale=1">'
            '<meta name=color-scheme content="light dark">'
            f"<title>{title}</title>{ICON_LINK}<style>{_PLAIN_STYLE}</style>"
            f"<body><main><div class=brand>{_LOGO}AIStack</div>{body}</main>"
            f"<script>{PLAIN_PAGE_SCRIPT}</script>")


# Every sentence that runs or installs AIStack, in the README, the operator's guide, setup,
# the sync skill and the page, starts with one of these, and a test holds them to it, so a
# change to where AIStack is installed from is made once and cannot miss a sentence.
RUN_COMMAND = "uvx aistack-mcp"
INSTALL_COMMAND = "uv tool install aistack-mcp"


def setup_instructions() -> str:
    """The instructions template, with `{server_url}` and `{mcp_url}` still to fill in."""
    return _read("setup-aistack.md")


def dashboard_page() -> str:
    """The whole web application: one file, with its own styles and script (ADR-0017)."""
    return _read("dashboard.html")


def sync_skill_document() -> str:
    return _read(f"skills/{SYNC_SKILL_NAME}/SKILL.md")


def local_setup_instructions() -> str:
    """`aistack setup`: local mode's setup, which has no server to fetch it from (ADR-0020)."""
    return _read("local/setup.md")


def local_sync_skill_document() -> str:
    """The sync skill for local mode, where the tools read and write the folders themselves."""
    return _read(f"local/{SYNC_SKILL_NAME}/SKILL.md")


def _read(relative_path: str) -> str:
    return resources.files(__name__).joinpath(relative_path).read_text(encoding="utf-8")
