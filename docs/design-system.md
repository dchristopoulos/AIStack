# Dashboard design system

How the dashboard looks and behaves, so every change comes back looking the same. The page is
`src/aistack/bundled/dashboard.html`: one file, no build, no framework, no outside requests
(ADR-0017). Everything below is a CSS custom property or a small function in that file. Change
the token, not the place that uses it.

`docs/DESIGN.md` is the product plan. This document is only about the page.

## The idea

A calm tool someone opens for two minutes, a few times a week, to see where their skills are
and move one. So:

- **Graphite, not black.** The dark theme is a soft grey (#161719 page) with lighter panels,
  like the professional tools people already use all day. Pure black reads as a toy.
- **One accent, for action and place.** The accent fills the primary button, the current item
  in the sidebar, checked boxes, switches, the focus ring, and the "update available" dot.
  Nothing decorative is coloured. Red means something will be removed; green means connected.
- **Words over symbols.** Every control says what it does: "Add to computer", "Details",
  "Manage", "Move here…". No bare "⋯", no two-letter badges.
- **Where you are reads like a path.** The top bar shows `dimitris / computers / macbook /
  Claude Code / ~/.claude/skills`; each part above the last opens that place.

## Tokens

### Colour

Light is the base on `:root`; `:root[data-theme="dark"]` swaps the neutrals. Both are set before
the page paints by the script in `<head>` (see Settings below).

| Token | Light | Dark | Use |
|---|---|---|---|
| `--bg` | #f4f4f6 | #161719 | page, sidebar |
| `--band` | #fafafb | #1a1b1e | top bar, page header band |
| `--surface` | #ffffff | #1e1f23 | cards, tables, dialogs, inputs |
| `--surface-2` | #efeff2 | #26272c | rail, account bar, code, hover on surface |
| `--head` | #f8f8fa | #212226 | table header, dialog and card footers |
| `--active` | #e7e7eb | #2c2d33 | hover on the sidebar |
| `--border` | #e2e2e7 | #2e2f35 | hairlines |
| `--border-strong` | #cdcdd4 | #41434a | buttons, indent guides |
| `--text` | #18181b | #ececef | body text |
| `--muted` | #585962 | #a6a8b0 | secondary text (≥ 6:1) |
| `--faint` | #696a73 | #8f919a | counts, hints (≥ 4.5:1 on every surface) |
| `--track` | #8b8c95 | #71737c | an off switch, the border of a text field or select (≥ 3:1) |
| `--danger`, `--danger-soft` | #c4242b | #ff7a7f | removing |
| `--ok` | #1f8a3d | #6bcb7f | connected |
| `--purple`, `--purple-soft` | | | the Private badge only |
| `--amber-dot` | | | the Demo data badge only |

Accent: `[data-accent]` on `<html>` sets `--a-l`/`--a-d` (the fill in light and dark) and
`--on-a-l`/`--on-a-d` (the text on it). Everything else derives from `--accent`:

| Accent | Light fill | Dark fill |
|---|---|---|
| Blue (default) | #2259d6 | #7aa7ff |
| Teal | #0e7369 | #4fd1c0 |
| Green | #1b7a3c | #6ad38a |
| Amber | #a85208 | #f5b942 |
| Rose | #c0264b | #ff8aa0 |
| Graphite | #18181b | #ececef |

- `--accent`: fills. `--on-accent`: text and icons on a fill.
- `--accent-text`: accent used as text (links on hover, update counts).
- `--accent-soft`: tinted background (current sidebar item, a computer's icon tile).
- `--accent-hover`: a filled control under the pointer.

Every pair is at least 4.5:1, checked for each accent in both themes. A new accent must pass
the same check: white on its light fill, its dark fill on `--surface`, and `--on-a-d` on it.

### Type

The system font (`--font`) and the system monospace (`--mono`). No web fonts: the page may not
fetch one, and embedding one costs ~100 KB for no gain in a tool.

- Monospace only for things a person might type or paste: skill names, group paths, folder
  paths, revisions, sentences to copy. Never for labels, counts, or people's names.
- Sizes: page title 28px/600, card and dialog titles 18px, section titles 15px, body 14px,
  secondary 13px, small 12–12.5px. Nothing smaller than 11.5px.
- Counts use `font-variant-numeric: tabular-nums`.
- Sentence case everywhere. No ALL CAPS labels, no eyebrows above headings.
- Real ellipsis `…` on a control that opens a further step ("Move here…", "Copy from…"), and
  in placeholders. Never `...`.
- No "A · B · C" strings: join with commas.

### Spacing, radius, elevation, motion

- Spacing on a 4px grid: 4, 8, 12, 16, 24, 32. `--gutter` 32px (16px on a phone).
- Radius: `--r-sm` 8px for controls, `--r` 12px for cards and tables, `--r-lg` 16px for dialogs
  and the side panel. Pills and avatars are round.
- Elevation: flat by default. `--shadow-menu` for menus and toasts, `--shadow-lg` for dialogs.
  Cards have a border, not a shadow.
- Motion: 120–200ms, `--ease`, only on what a person did (opening, expanding, toggling). Nothing
  moves on its own. `prefers-reduced-motion` turns all of it off.

## Layout

```
┌────────────────────────────────────────────────────────────────┐
│ ◆ AIStack  [▢ dimitris / computers / macbook / Claude Code]  ● Library: GitHub │
├──┬──────────────┬──────────────────────────────────────────────┤
│P │ Personal     │ Page title                         [actions] │
│──│ Library    7 │ one line on what this page is for            │
│A │ Computers  + │──────────────────────────────────────────────│
│+ │ ▾ macbook    │ content: a table, cards, or an empty state   │
│  │   Claude Code│                                              │
│  │     Global 7 │                                              │
│  │ + Add agent  │                                              │
│  │ Where it lives                                              │
│  │ Settings     │                                              │
│  ├──────────────┤                                              │
│  │ dimitris   ⇥ │                                              │
└──┴──────────────┴──────────────────────────────────────────────┘
```

- **Rail** (left column): Personal, then each team, then Add a team. Hidden in local mode
  (`state.server === false`), which has no teams.
- **Sidebar**: the space's own navigation. In Personal: Library, the computer tree, then Where
  it lives and Settings at the foot.
- **Top bar**: the logo (home), the path, and a pill saying where the Library lives, which
  opens that page.
- Under 820px the rail and sidebar become a drawer behind the menu button, and the path keeps
  only its last two parts, the last of which never gives way.
- Tables become stacked cards when the content area beside the sidebar is under 760px, a
  container query on `.wrap.body` and not a viewport width: a tablet in portrait keeps the
  sidebar and has less room than a phone in landscape.
- Nothing scrolls sideways, at any width and with any name. Text a person chose (a computer,
  a username, a team, a group path) wraps in tables, cards and badges, and is never `nowrap`
  there. Only a one-line place (the path, a computer in the sidebar, the account bar) may cut
  it with an ellipsis, with the full text in its title.

## Components

Each is a function in the page. Use the existing one; add a variant to it only when a case
cannot be said with what is there.

| Component | Function | Variants |
|---|---|---|
| Button | `btn(label, props, icon)` | default (outlined), `primary` (accent fill, one per view), `ghost` (quiet, in rows), `danger` (removing), `danger solid` (the confirm of a removal), `sm`, `icon` (only with `aria-label`) |
| Switch | `sw()` | on/off, with a tooltip saying what each state means; its word never changes with its state (`aria-checked` carries that); one that cannot be turned is `disabled` (kept focusable) with its reason as `why`, shown beside it |
| Dialog | `openDialog()` | centred (a decision or a form), `sheet: true` (a side panel about one thing: a skill's details) |
| Confirm | `confirmDialog()` | for anything that removes; says what stays; opens on Cancel, and its lines are the dialog's description |
| Copy field | `copyField(value, label)` | any sentence or command a person pastes elsewhere |
| Menu | `menu(label, fk, items)` | a labelled "Manage" button, never a bare "⋯"; only for secondary admin actions in a row |
| Table | `.tbl` + `.tr` + `td()` | `library`, `folder`, `tree` (indent guides), member and group grids |
| Empty state | `empty(icon, title, …body)` | says what to do next, with the button that does it |
| Toast | `toast(text, kind)` | `ok`, `warn`, `error`; the sentence names what happened; outcomes stay until dismissed |
| Card | `.card` + `.card-body` + `.card-foot` | `danger`, `choice-card` (an option with its own button) |
| Facts | `dl.facts` | label on the left, value on the right |
| Picker | `fieldset.picker` | checkboxes or radios, grouped by computer (`target-group`) |

Explicit variants over flags: when a dialog says different things in different situations,
write one small function per situation and pick it from a table. `ADD_COMPUTER` is the model:
one entry per place the Library can live.

## Patterns

- **Clicking a thing opens it.** A skill's name opens its side panel: what it is, where it is
  (ticks per computer and agent), its revision and files, Share, Remove.
- **Where something is, is information.** Computers and agents are listed as words with links
  to that folder. Removal happens in the panel or on the folder page, never by clicking a tag.
- **Computers are a folder tree**: computer, then each coding agent, then its folders: Global
  (its home skills folder), then each project the computer manages, by the repository's name
  in monospace with the `repo` icon.
- **A project folder reads as "<agent> in <project>"** everywhere a folder is named: the
  picker, "Where it is", page titles. Its page says the folder relative to the repository
  (`.claude/skills`), where the repository was last seen on that computer, and, until it
  syncs there, a card saying how its skills arrive. A skill also in the global folder gets one
  help line saying which copy the agent uses. "Add a project" offers two cards: a project
  another computer manages, added at once, and a new repository, which starts with a sentence
  said inside it. "Stop managing…" confirms and says the files stay. Project folders are a
  server's for now: the localhost dashboard shows no "Add a project".
- **Adding an agent is local until it matters.** A picked agent shows on its computer at once
  (kept in this browser), and becomes real when a skill is placed there or it syncs.
- **Say what is true for this setup.** Text that depends on where the Library lives, or on
  server versus local mode, is chosen from `state`, never written for the server and left
  wrong elsewhere.
- **Choices kept in the browser** (theme, accent, picked agents) live in `localStorage` under
  versioned keys (`aistack.appearance.v1`, `aistack.picked-agents.v1`), every access in
  try/catch. The page works without them.
- **Destructive actions confirm** and say what is not lost ("It stays in your library").

## Keyboard and screen reader

- The first Tab reaches "Skip to content", which moves focus to `main`.
- A new page (a link, Back, the drawer) takes focus to its `h1`, unless focus is on something
  still there. A new page closes any dialog that was open.
- An action that takes away its own button hands focus on: to the control named in its
  `data-next`, else the next control of the same kind, else the heading. Never to the page.
- A dialog that saves says its outcome in a toast after it closes, never while it is open.
- Open on a phone, the drawer is modal: everything behind it is inert and Tab goes round
  inside it.
- A button repeated on every row names its row: "Take update to code-review", with the
  visible words first.
- Every row of a table has as many cells as its header, or says how many it spans with
  `aria-colspan`. Avatars and other letters drawn as pictures are `aria-hidden`.
- A page title is `<view>, <place>, AIStack`, and each team tab has its own.
- Escape hides a tooltip until the pointer or focus leaves its control.
- axe (`tests/ui`) finds nothing on any screen, in both themes and with the drawer open.

## Settings

`#/settings`: Appearance (Match the system, Light, Dark; six accents) and Account. The script in
`<head>` reads `aistack.appearance.v1` and sets `data-theme` and `data-accent` on `<html>` before
anything paints, follows the system when the choice is "Match the system", and updates
`<meta name="theme-color">`. `window.appearance.set({theme, accent})` saves and applies.

## Avoid

These make a page look generated or confuse people, and were removed on purpose:

- Pure black backgrounds, neon accents, glows, gradients, glass.
- More than one accent at a time, or colour used as decoration.
- Monospace for labels and names; ALL CAPS; eyebrow labels; "A · B · C" strings; "→" on buttons.
- Icon-only controls without a visible label, except the close ×, the drawer button, and the
  sidebar's +, which all carry an `aria-label` and a tooltip.
- Two-letter badges standing for names (CC, AG).
- Chips that act when clicked.
- Identical cards for content that is really a list: a list is a table.

## Checking a change

- Look at it in both themes and at 390px wide.
- Run the browser tests (`tests/ui/`). They find controls by role and by the words a person
  reads, so a renamed button changes its test in the same commit.
- New text on a new surface: check its contrast against both themes' `--surface` and `--bg`.
