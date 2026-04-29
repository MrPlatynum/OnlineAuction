from datetime import datetime, timezone


def utcnow() -> datetime:
    """Return the current UTC time as a naive datetime.

    Replacement for the deprecated ``datetime.utcnow()``. Returning a
    naive value matches the existing ``DateTime`` column behaviour so
    the database schema and stored values stay identical.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)
