# Contributing to AIStack

AIStack keeps a person's coding-agent skills and rules in one private Library, syncs them to every computer and agent they use, and shares them with a team. It runs as a self-hosted server or entirely on one computer (local mode).

## How it is built

AIStack is built with coding agents, Claude Code and Codex among them. Every change is reviewed, tested on SQLite and PostgreSQL and in three browsers, and merged by the maintainer. `AGENTS.md` is the brief those agents work from, and it is also the best summary of the project's conventions for a person.

## Getting started

```bash
poetry install
poetry run playwright install chromium   # once, for the dashboard tests
poetry run pytest -q                     # SQLite, with the browser tests
```

The PostgreSQL half needs a database: `docker compose -f compose.test.yaml up -d`, then run the suite with `TEST_DATABASE_URL=postgresql+psycopg://aistack:aistack@localhost:5433/aistack_test`. `poetry run pytest -q tests/ui` runs only the browser tests; `AISTACK_UI_BROWSER=firefox` or `webkit` runs them in another browser.

## What to read first

1. [`README.md`](README.md): what AIStack does and the commands.
2. [`CONTEXT.md`](CONTEXT.md): the words the code and the page use. Use them exactly.
3. [`docs/DESIGN.md`](docs/DESIGN.md) §1 and §4: what AIStack is, its tools, flows and sync contract.
4. [`docs/adr/`](docs/adr/): the decisions already made, each with its reasoning. To reverse one, write a new ADR rather than changing the code around it.
5. [`AGENTS.md`](AGENTS.md): the conventions, and [`docs/design-system.md`](docs/design-system.md) before changing the page.

## Changes

- Open an issue before a larger change, so the design can be agreed first.
- A pull request is one change, squash-merged into one commit on `main`.
- Commit subject: imperative, in product words, under 72 characters ("Let a team's invite code create the account"). Body: why, then what, wrapped at 72. End with `Part of #N.` or `Closes #N.` when there is an issue. No trailers.
- Tests come with the change, and a test that pins old words changes with the words. Run the PostgreSQL half for a migration, a query or anything concurrent, and the browser tests for any change to the page.
- A change at a trust boundary (authentication, sync, push validation and hashing, migrations, anything that deletes, any route that answers without a session) also needs the PostgreSQL run and a test that fails with the check removed. Say in the pull request that it is one and what was verified.

## Security

Report a vulnerability privately as [`SECURITY.md`](SECURITY.md) describes, never in a public issue.
