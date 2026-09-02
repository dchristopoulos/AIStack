from datetime import datetime, timezone


def utc_now() -> datetime:
    """Timezone-aware now, in UTC.

    Column defaults are computed in Python rather than by the database: SQLite's CURRENT_TIMESTAMP
    is naive UTC text and Postgres' now() is the transaction start time, so a server-side default
    would mean two different values depending on where the code happens to run.
    """
    return datetime.now(timezone.utc)
