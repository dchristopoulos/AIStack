# Showing AIStack

The plan for how the project presents itself: the README, a demo video, and where it is announced. Written before any of it was built (2026-10-14), and kept as the checklist. Posting anywhere is done by the owner, from his own accounts; nothing here is automated.

## Who it is for

Two readers, with different amounts of time.

- **Someone deciding whether to try it** (a developer, a team lead, a self-hoster). They want to know in ten seconds what it does and in two minutes whether it works. They read the top of the README and watch a short clip.
- **Someone judging the engineering** (a hiring manager, a reviewer). They scroll. They want to see decisions, trade-offs, and tests, and they follow links to the ADRs.

The top of the README serves the first reader and everything below it serves the second. The same clip serves both.

## The one sentence

> A self-hosted home for your AI coding skills: backed up from every computer you use, shared with your team on your terms.

It is said the same way in the README, the repository description, and every post.

## 1. The README

| Change | Why |
|---|---|
| A moving demo at the very top, above the screenshots | A still cannot show "a teammate's change is offered, and you say yes". That exchange is the product |
| Screenshots retaken after the sidebar and Mono changes | The current ones show the page before both |
| "Try it in two minutes": start a server, seed it, open the link | Today the only way to see the page is to connect a real Claude Code. A reader will not |
| Repository description and topics set on GitHub | The repository page shows them before the README, and search uses them |

Not changing: the order and content of the engineering sections. They are what the second reader came for.

## 2. The demo

One recording, scripted, so it is retaken with a command when the page changes instead of going stale.

**How it is made.** `scripts/record_demo.py` starts from a server filled by `scripts/demo_seed.py`, drives the real page with Playwright, and captures it frame by frame as screenshots, with a pointer and a caption drawn by the script. Screenshots are used and not Playwright's own video because that video is a low, fixed bitrate and small text smears. The frames become:

- an **animated PNG** for the README: a handful of held frames, lossless, about 2 MB. GitHub shows an image from the repository inline and plays it; it shows a video only when it is uploaded by hand through the website, and caps an image at 10 MB.
- an **MP4** (H.264, 1920×1080, 30 fps) for LinkedIn and anywhere else, encoded with the Mac's own AVFoundation, so nothing is installed.

**What it shows**, in thirty seconds as first recorded (the phone scene is not in it yet: a video keeps one frame size), with a caption on every scene because most feed video plays muted:

1. My skills: every skill, and which computer has it. Switch one on for the desktop.
2. A teammate pushed a newer `code-review`. It is offered, with her name. Take it.
3. Share a skill into a nested group, from a dialog.
4. The sidebar: teams, their groups, a private one. Open a group.
5. The same page on a phone.
6. Closing card: the one sentence, and the repository address.

Not in it: the chat side ("sync aistack"). It is text scrolling in a terminal, it is slow, and it differs by coding agent. The README's table of sentences covers it.

## 3. Where it is announced

In this order, because each one makes the next easier. Each has rules that were checked in October 2026 and should be checked again on the day.

| Where | What goes there | Rule to respect |
|---|---|---|
| **GitHub** | Description, topics (`mcp`, `claude-code`, `self-hosted`, `agent-skills`), a `v0.1.0` release | |
| **LinkedIn** | The MP4 uploaded natively, with a short post: the problem, what it does, what was hard, the link in the first comment | Landscape suits a screen recording. Captions on screen. Say something in the first three seconds |
| **awesome-mcp-servers** | A pull request adding one line | It lists servers a person installs and runs themselves, which this is |
| **awesome-claude-code** | An issue from its template, not a pull request | It does not accept pull requests from people |
| **Show HN** | "Show HN: AIStack – self-hosted sync and sharing for AI coding skills", with a first comment saying why it exists and what it does not do | It must be something people can run; be there to answer for a few hours; do not ask anyone to upvote |
| **r/selfhosted** | A text post that describes it, link inside | Read the current rules first. New projects may be limited to a weekly thread |

A draft of the LinkedIn post and the Show HN comment is in the appendix below, to be rewritten in the owner's own voice.

## What has to be true first

- [ ] A stranger can run it from the README without help. Today that means building the image themselves.
- [ ] The demo and screenshots match the page as it is.
- [ ] The repository has a description, topics, and a tagged release.

## Open questions for the owner

1. **A published image.** `docker run ghcr.io/dchristopoulos/aistack` is the difference between "try it" and "build it". It needs a release workflow and a public package. Not started; it is a new piece of work.
2. **A public demo server**, read-only or reset nightly, so the first click is the product and not a README. It costs hosting and has abuse to think about. Not started.
3. **Voice-over.** The plan is captions only. A spoken version is a different recording.

## Appendix: drafts

**LinkedIn**

> My team kept copying the same AI coding skills between laptops, and a month later nobody had the same version.
>
> So I built AIStack: a small self-hosted server where every skill on your computers is backed up to a private space of your own, and shared with a team, or one group in it, when you choose.
>
> The part I cared most about: a teammate's edit to a skill is never applied to your machine. A skill is instructions to an agent. You are shown who changed it and you say yes.
>
> One container, SQLite or PostgreSQL, no passwords, 870 tests. The web dashboard is the product; your coding agent is connected to the same account over MCP.
>
> Open source. Link in the comments.

**Show HN, first comment**

> I use Claude Code on two computers and with a few teammates, and skills (the instruction folders an agent loads) drifted between all of them. Git works until someone edits a copy locally, and it has no idea which machine should have what.
>
> AIStack is a server you run yourself. Each person has a private space that mirrors their computers; sync backs up what it finds and never deletes or overwrites without asking. Teams and nested groups sit on top, and a teammate's change is an offer you accept, not something that arrives.
>
> What it does not do: it supports Claude Code only today (Codex is next), it does not merge, and nothing syncs in the background. The decisions and the ones I rejected are in docs/adr.
