# The page is organised by project

Status: accepted, 2026-10-21. Amends the computer tree in `docs/design-system.md` ("Computers are a folder tree") and the dashboard section of `docs/DESIGN.md`. ADR-0017 (one HTML file, JSON routes on the same app) is unchanged.

The personal space showed computers as a tree: computer, then each coding agent, then its global folder and each project. With two computers, four agents and three projects that tree has seventeen leaves and scrolls off the screen; one project appears once per agent per computer, and answering "what does my agent read in this project?" takes five pages. Rules (ADR-0036) would add a second list to every leaf. A working prototype of three layouts of the same setup was compared before this decision.

## Decisions

**The sidebar lists places a person thinks in.** Library; Every project; Projects, each by name; Computers. A computer is no longer the parent of everything. Each computer keeps a page.

**A project is one page.** It shows where the project is (each computer, its folder, its agents, when it synced) and one table of everything the agents read there, in the order they read it: your rules for every project, the repository's rules, your rules for this project, then skills. Coding agents are the table's columns, with a tick where an agent reads a row. Something true on only one computer is said on its row ("Only on MacBook Pro"), not by repeating the project per computer.

**Every project is one page.** It holds the rules and skills that reach every project: the global folders of every agent, on every computer.

**A computer's page is about the computer.** Its coding agents and their files for every project, its projects with their folders, when it last synced, its settings. Connecting, renaming and removing a computer stay where they are.

**Adding happens from a + on the thing you add to.** Each sidebar heading and item that can take something has a +: on a computer, "A coding agent, A project, Skills, A rule"; on a project, "Skills, A rule, Another computer"; on Projects, "A folder on this computer, A project from another computer"; on Every project, "Skills, A rule". The + shows on hover, focus and the current item, and always on headings. The "Add an agent" and "Add a project" rows go.

**Clicking a rule opens it in the side panel**, as a skill's name already does: its text, which agents use it, Edit, and for a repository's file "Turn this file off for me" and Commit…. The editor is a plain text area with a preview; Save makes a revision.

**The agents shown are the ones the person has.** Columns are the coding agents found on their computers, in a fixed order. The `agents` harness is never shown as a folder: its readers are columns.

**Demo data uses names that say what they are.** The demo's team is `demo-team` and its projects `demo-api` and `demo-website`, in the page's demo and in `scripts/demo_seed.py`.

## Not doing

- A view per agent ("everything Codex reads"). The columns answer it on every page.
- Dragging skills between places.
- Hiding computers. A person with one computer still sees it, once.

## Consequences

- `docs/design-system.md` replaces "Computers are a folder tree" and "A project folder reads as '<agent> in <project>'" with the patterns above, and gains the + menu and the tick table as components.
- The browser tests that walk the computer tree are rewritten in the same change, by role and by the words a person reads.
- `/api/state` may gain fields that save the page from assembling a project across computers; the page never filters what `visibility` allowed.
- The prototype the decision was taken from stays on a branch, not on main.
