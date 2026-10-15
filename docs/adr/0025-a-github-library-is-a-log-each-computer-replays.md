# A Library on GitHub is a log each computer replays

Status: proposed, 2026-10-15. Amends ADR-0020, which planned a storage interface under the services with a files-only second implementation. Issue: #96.

ADR-0020 offers one person a private GitHub repository as the place their Library lives: free, nothing to keep switched on, nothing that pauses. Every service, the tools and the dashboard are written against SQLAlchemy. A second implementation of all of them over files would be the largest change AIStack has had, and it would have to reproduce, in a second form, everything the database enforces today.

## Decision

**Each computer keeps its own SQLite copy of the Library, and the repository holds the log of changes that built it.** The services, the tools and the dashboard run unchanged on the copy. Only what is shared differs: not the database, but a list of events.

**An event is one change, as a file.** Local mode records every change it makes as an event, in the same transaction as the change: a computer added, a revision pushed (with its files), a skill placed in or taken off a folder, a skill removed from the Library, a folder synced. The file is `log/<machine id>/<time>-<event id>.json`. A computer only ever adds files, and only in its own folder, so two computers never edit the same file and git never has a conflict to resolve. A push that is not up to date is refused by git, so a computer pulls and pushes again.

**Replay applies events through the same service calls the tools make,** so what the database enforces holds for an event from another computer exactly as for one made here. Ids that other computers must agree on travel in the event: the computer's id and the user's id. Revision numbers do not travel; they are assigned by replay, in a fixed order: by time, then machine id, then event id.

**A copy that is behind replays only what is new, and a copy that disagrees is rebuilt.** When everything pulled sorts after what this computer already applied, it is applied on top. When something sorts earlier, because two computers worked offline at once, the copy is emptied and the whole log replayed in order, inside one transaction, so every computer ends with the same revisions in the same order.

**git does the carrying, with the person's own GitHub login.** The repository is cloned into `~/.aistack/library`, through the `git` command and the credential `gh` set up, so AIStack stores no token. Setup creates the repository with `gh repo create --private`.

**What is never in the log:** a machine token, a session, a sign-in link. They are minted per computer and mean nothing on another.

## Consequences

- The copy can be deleted at any time and rebuilt from the repository, which is the backup.
- A rebuilt copy dates every revision from the rebuild, not from its push. The log keeps each event's time, so this can be corrected later without changing the format.
- History is git's: nothing is ever removed from the repository, including a skill that was removed from the Library.
- The same log works for local SQLite and PostgreSQL Libraries, which record it too, so a Library can later move to GitHub by publishing what it already has.
