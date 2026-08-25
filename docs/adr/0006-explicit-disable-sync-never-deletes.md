# Explicit disable; sync never deletes; ask only when data can be lost

Status: accepted

Removing a skill from a machine is an explicit act: `disable_skill` sets `enabled = false` and the agent deletes the local folder. Sync never deletes a local file and never flips `enabled` silently. Sync acts silently only on skills enabled for the calling machine whose local copy is absent or matches a known revision; every other state (locally modified, disabled-but-present, undecided-but-present, orphan) is reported and the user decides.

Why: a bare `{name: hash}` payload cannot distinguish never-installed, half-installed, and deliberately deleted — all three arrive as "missing". The alternatives were tracking last-known state per machine (what dpkg conffiles and Unison do — a baseline archive), or making removal explicit. Explicit disable was chosen: it dissolves the ambiguity (missing + enabled always means install, so failed installs self-heal on the next sync), needs no new state, and keeps sync's promise simple enough to trust. The `enabled = false` row vs no-row distinction records "explicitly disabled" vs "no decision", which the sync contract depends on.

Rejected: baseline tracking (a bidirectional-sync engine the MVP doesn't need); inferring deletion as intent (silent data-loss risk); auto-pushing orphans (a fresh machine may hold dozens of third-party skills — importing them unasked creates false provenance).
