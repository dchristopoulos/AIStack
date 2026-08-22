# SQLite by default, Postgres via DATABASE_URL

Status: accepted

AIStack is self-hosted open source (no hosted SaaS), so every dependency the server needs is a dependency every user must run. Default database is SQLite in a file inside the container volume; setting `DATABASE_URL` switches to Postgres for larger teams. SQLAlchemy keeps the code identical for both.

Why: onboarding is one container instead of two, and the write volume (skill pushes, sync checks) is tiny — SQLite handles a small team without strain. Postgres stays the documented path for teams that outgrow it.
