# Local mode writes rules in the release that adds them

Status: accepted, 2026-10-21. Amends ADR-0026's rule that a new Library log event kind is replayed one release before any release records it, for the kinds named here only.

ADR-0026 has a release replay a new kind of change a week or more before any release records one, so that a computer still on the older release never meets a change it cannot read. The rule kinds from ADR-0036 (`rule_created`, `rule_edited`, `rule_renamed`, `rule_removed`, `rule_agents_set`) were added that way: the coming release replays them and, under the rule, would record none. Local mode would then show rules read-only for a whole release, and a project's own files, whose ticks and turn-offs have no event kind at all yet, would be listed and never kept.

## Decision

**The coming release records the five rule kinds, and three new kinds for a project's files, in the release that adds them.**

- `project_files_listed`: the project's key and name, the folder it was found in on the computer that recorded it, and its files by path, size and tick, as Add a project lists them.
- `project_file_ticked`: the project's key, the file's path, and whether the page shows it.
- `project_file_turned_off`: the project's key, the file's path, and whether it is turned off for the person.

An edit of a repository file made in local mode is written straight into the working copy of the computer the page runs on, and shared from there, so it is not a change to the Library and has no event.

**Why this is safe enough now.** No release that records these kinds has been published. The only published release that reads a GitHub Library's log, 0.1.1, stops reading at a kind it does not know without changing anything, says the Library needs a newer release, and updates itself within a day (`bootstrap/self_update.py`). The trade-off, plainly: a computer still on 0.1.1 sees none of the person's other changes from the first rule change recorded elsewhere until it has updated, which is at most a day for anyone who leaves updates on, and for as long as they choose for anyone who turned them off. Nothing is lost: the log keeps every change, and the updated release replays it.

**The rule stands for every later kind.** A kind added after this release is replayed one release before any release records it, as ADR-0026 says.

## Consequences

- `library_log._REPLAY_ONLY` no longer holds the rule kinds; the project folder kinds and `library_moved` stay in it.
- The localhost dashboard serves the rule routes and the project file routes, with the session cookie and the request header like every other action. Each route that changes the Library records its event in the same transaction.
- Local mode keeps a project's files without managing its skills folders, which waits for the project folder kinds. A project added on the localhost dashboard is listed by its files.
- The folder a project was listed from is read back from this computer's own `project_files_listed` events, and the working copy found there must still be that project's repository before anything is written into it.
