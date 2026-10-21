---
name: ship-a-change
description: Commit, open a pull request, and land it on AIStack's main. Use when work is ready to commit, a PR needs opening or merging, or a stack of PRs needs landing.
---

# Ship a change

One step of an issue is one branch and one pull request (`docs/agents/issue-tracker.md`, "Work in steps"). Each step below ends on its criterion.

## 1. Verify

- Run the suite as AGENTS.md "Running tests" says. Done when it is green on SQLite.
- A migration, a query, or anything concurrent: also green on PostgreSQL.
- A change to `bundled/dashboard.html`, `scripts/demo_seed.py`, or `tests/ui/`: also the browser tests.
- A test that pins a race: watched go red with the enforcement removed, then restored.

## 2. Commit

- Subject: imperative, in product terms, under ~70 characters ("Let a team's invite code create the account").
- Body: why first, then what changed, wrapped at 72. When an issue exists, the last line names it: `Part of #X.` or `Closes #X.`
- The body describes the change and nothing else: no plan step numbers, no finding ids, no account of how the work was checked (mutants caught, runs made). The PR holds that.
- No `Co-Authored-By` trailer, no "Generated with" footer, no mention of the tool that wrote it. Commits and PRs read as the author's own.
- One meaningful change per commit. A fix-up to an unmerged branch is folded into the commit it belongs to. Bookkeeping about the change, such as ticking a plan or a note in a doc, goes in the same commit, never in a commit of its own.

## 3. Open the PR

- Title: the commit subject. Body: one line placing it ("Part of #79 (ADR-0020)."), then bullets of what changed, then the tests and the databases they passed on. End on the gate sentence from step 4. No footer and no attribution line.
- Branch: `feat/<issue>-<slug>`, `fix/…`, or `docs/…`, from an up-to-date `main`.
- If your harness can watch the PR (Auto-fix in the Claude desktop app), turn it on, so a CI failure or a review comment wakes the session.

## 4. Gate

Work that was decided and planned, and passes, merges without waiting for a manual review. Arm auto-merge with the squash method on every PR: `gh pr merge <n> --auto --squash --delete-branch`. `main` gets one commit per PR, carrying the commit's message with `(#n)` added to its subject. Nothing reaches `main` except through a merged PR: never push to it, and never force-push it. `main` requires `pytest`, `browsers (chromium)`, `browsers (firefox)`, `browsers (webkit)`, `container`, `windows` and `macos`, and GitHub refuses auto-merge on a branch with no required checks.

A **trust-boundary** change (auth, sync, push validation and hashing, migrations or migration tooling, anything that deletes, any route that answers without a session) earns its merge with more evidence instead of a wait. Before arming it:

- review your own diff against AGENTS.md "Trust-boundary work gets a diff review": a missing authorization check, a path traversal, a secret in a log line;
- run the PostgreSQL half, and watch each enforcement test go red with the enforcement removed;
- say in the PR, in one sentence, that it is a trust-boundary change and what was verified.

Stop and ask only for a new design direction nobody decided, or a change that would make data unrecoverable.

## 5. Land a stack

When each PR is based on the one before it:

1. Arm auto-merge on the bottom PR only. When it merges, GitHub deletes its branch and retargets the next PR to `main`.
2. Rebase the next branch onto `main` (`git rebase --onto origin/main <old base> <branch>`), push it, and arm it. Repeat up the stack.
3. Remove the stack's worktrees once their PRs have merged.

Done when every PR in the stack shows merged and `git log origin/main` holds one commit per PR.

## Events while waiting

- A CI failure: reproduce locally, fix on the branch, push.
