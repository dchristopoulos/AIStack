from datetime import datetime, timezone


def utc_now() -> datetime:
    """Timezone-aware now, in UTC.

    Column defaults are computed in Python rather than by the database: SQLite's CURRENT_TIMESTAMP
    is naive UTC text and Postgres' now() is the transaction start time, so a server-side default
    would mean two different values depending on where the code happens to run.
    """
    return datetime.now(timezone.utc)


def as_utc(moment: datetime) -> datetime:
    """A stored timestamp as an aware UTC datetime, whichever database returned it.

    Postgres hands back timestamptz in the session's time zone, which is the database's
    default and need not be UTC. SQLite stores text and hands back a naive datetime, which
    Python would then read as local time. Every timestamp is written by `utc_now`, so a naive
    one is UTC by construction.
    """
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)
