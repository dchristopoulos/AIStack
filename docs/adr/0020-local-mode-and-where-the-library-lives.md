# AIStack runs on your own computers, and you choose where your Library lives

Status: proposed, 2026-10-14. Not built. Amends ADR-0002 and ADR-0017. Research: [docs/research/personal-library-storage.md](../research/personal-library-storage.md) and [docs/research/free-personal-hosting.md](../research/free-personal-hosting.md).

AIStack is free and open source, and there is no hosted service: everyone runs it themselves. Today that means one server that every computer reaches, so a person alone must keep a machine switched on, or pay a few dollars a month for a host, to share one Library between a laptop and a desktop. For one person that is the hardest part of setting AIStack up, and it is avoidable.

## Decisions

**Two ways to run AIStack.**

- **Server mode**, as today: one process that every computer reaches over HTTPS, with its own SQLite or PostgreSQL. It is the only mode for teams, because a team needs one trusted place that decides who sees what (`services/visibility.py`) and records who pushed what.
- **Local mode**, new: the coding agent starts AIStack on each computer as a local MCP server over stdio (`uvx aistack`), the dashboard is served on `127.0.0.1` by the same package, and only the Library's storage is shared between computers. Nothing has to stay switched on.

Both modes run the same `services/`. Push validation, the content hash (ADR-0011) and reconciliation (ADR-0007) are pure functions and do not change.

**Where your Library lives is a choice, offered with its cost stated.** Setup, and a page under Personal, ask "Where should your Library live?" and offer three answers, each with one honest line:

| Choice | Mode | What the person is told |
|---|---|---|
| A computer that stays on (Docker and Tailscale on a desktop, NAS or mini PC; or about $3 a month on Fly.io) | Server | Free on a computer you own, but it must stay on. The only choice that works for teams. |
| A free PostgreSQL database (Neon recommended; Supabase works) | Local | Free and nothing to keep on. You paste the database's address once; every other computer gets its own login by pairing. Supabase pauses after about a week unused and needs a click to wake; Neon wakes by itself. |
| A private GitHub repository | Local | Free, nothing to keep on, nothing pauses, and every change is visible on GitHub. |

**Setup does the work wherever a tool already can.** The `setup-aistack` instructions detect what is installed and act: `gh` signed in means the private repository is created for the person (`gh repo create --private`); a connection string pasted once is checked and stored for that computer. A choice that needs steps a person must do themselves (creating a Neon project, installing Tailscale) is walked through, not described.

**Build order.** PostgreSQL in local mode first: AIStack already runs with several concurrent writers on PostgreSQL, so the storage code is unchanged and the work is the local entrypoint. GitHub second: it is the better product, with no password to paste and nothing that pauses, but it needs a second storage backend with a files-only layout. Both come after the server work for several agents (#62, step 3), which local mode reuses.

## What local mode changes

- **Identity.** No invite code and no machine token: whoever can start the process on a computer is its user. A computer keeps a local id, stored beside its agent's configuration.
- **One database login per computer, handed out by pairing.** The owner's connection string is pasted once, on the first computer, and used only to create a login role for each computer (`CREATE ROLE ... LOGIN` with a random password, granted only AIStack's tables) and to run migrations. "Add a computer" on a connected one creates the next role and prints one command that carries its credential, as `add_machine` does today. A lost laptop is one `DROP ROLE`, and nothing else changes. The owner's password is never stored on a second computer. Sharing a password hash instead cannot work: PostgreSQL stores SCRAM verifiers, which are designed not to be usable as a login. Whether each provider allows `CREATE ROLE` from SQL is checked before building.
- **Bytes.** The process reads and writes the skills folder itself, so transfer URLs (ADR-0010) are not used. File content still never passes through the model.
- **Trust.** Anything holding the storage credential could write without validating, so an install validates and re-hashes what it read before writing it to disk.
- **Upgrades.** The first computer to upgrade migrates the shared database for every computer. `migrate_schema` takes a PostgreSQL advisory lock first, and a computer whose release is older than the database's schema refuses to start and says to upgrade.
- **Moving to a team.** A person who later joins a team moves their Library onto that team's server, which needs an export and import that do not exist yet.

## Rejected

- **Google Drive.** Its API has no compare-and-swap on a file, so two computers writing at once silently lose one write. Dropbox and OneDrive do have one and could back the files-only layout later.
- **A SQLite file in a synced folder** (iCloud Drive, Dropbox, Google Drive for desktop, OneDrive, Syncthing). Copying a database mid-transaction is a documented way to corrupt it, and two computers writing between syncs fork it. A files-only layout in a synced folder can be safe, and is the natural fourth choice once the GitHub backend exists.
- **Turso, Cloudflare D1, Firebase, Supabase Edge Functions.** Respectively: a driver with no Windows support, no path from Python, a service-account key with the same trade as a password and a new data model, and a second implementation of validation and hashing in TypeScript.
- **A hosted AIStack.** Not this project's aim.

## Consequences

- A second entrypoint (`aistack` over stdio, `aistack dashboard` on localhost) beside the container; the package is published so `uvx aistack` resolves.
- An advisory lock in `migrate_schema` on PostgreSQL, and a schema-version check at startup.
- A storage interface the services can sit on with two implementations (SQLAlchemy, then the files-only layout for GitHub), introduced when the second one is built, not before.
- The README leads with the three choices for one person, and with server mode for teams.
