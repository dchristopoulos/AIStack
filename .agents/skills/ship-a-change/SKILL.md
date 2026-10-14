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

The history reads as the owner's own engineering work.

- Subject: imperative, in product terms, under ~70 characters ("Let a team's invite code create the account").
- Body: why first, then what changed, wrapped at 72. Last line names the issue: `Step N of #X.`, `Part of #X.`, or `Closes #X.`
- The body describes the change and nothing else: no co-author trailer, no "Generated with" line, no mention of chats, reviews, or who asked.
- One meaningful change per commit. A fix-up to an unmerged branch is folded into the commit it belongs to.

## 3. Open the PR

- Title: the commit subject. Body: one line placing it ("Step 2 of #79 (ADR-0020)."), then bullets of what changed, then the tests and the databases they passed on. End on the gate sentence from step 4. No footer.
- Branch: `feat/<issue>-<slug>`, `fix/…`, or `docs/…`, from an up-to-date `main`.
- If your harness can watch the PR (Auto-fix in the Claude desktop app), turn it on, so a CI failure or a review comment wakes the session.

## 4. Gate

Decide which kind of change it is. Done when the PR says which, in one sentence.

- **Trust boundary**: auth, sync, push validation and hashing, migrations or migration tooling, anything that deletes, any route that answers without a session. It waits for the owner's diff review, with auto-merge left off. Write "This is <kind>, so it needs your diff review; auto-merge is not armed." and move on to the next piece of work.
- **Everything else** (docs, UI, tests, a change the owner already approved): arm auto-merge with the rebase method. `main` requires `pytest`, `browsers (firefox)`, `browsers (webkit)` and `container`, and GitHub refuses auto-merge on a branch with no required checks.

When the owner says "merge when green", that is the go-ahead for a trust-boundary PR too: arm it, or land it as below.

## 5. Land a stack

When each PR is based on the one before it and every one is approved:

1. Check every head is green on its exact commit and fast-forwards from `main` (`git merge-base --is-ancestor origin/main <head>`).
2. Push each head to `main` in order: `git push origin <sha>:refs/heads/main`. Commits keep the SHAs CI tested.
3. GitHub marks a PR merged only when its own base contains its head, and it misses some. Retarget the next open PR to `main` and arm it, or close a PR it missed with a note naming the commit now on `main`.
4. Delete the stack's branches, locally and on `origin`, and remove their worktrees.

Done when every PR in the stack shows merged or closed with that note, and `git log origin/main` holds each commit once.

## Events while waiting

- A Copilot review summary that says it hit its quota is noise: nothing to fix.
- A CI failure: reproduce locally, fix on the branch, push.
