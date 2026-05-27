from datetime import UTC, datetime


def utcnow() -> datetime:
    """Return the current UTC time as a naive datetime.

    Replacement for the deprecated ``datetime.utcnow()``. Returning a
    naive value matches the existing ``DateTime`` column behaviour so
    the database schema and stored values stay identical.
    """
    return datetime.now(UTC).replace(tzinfo=None)


def seconds_until(end_time: datetime | None, *, is_active: bool = True) -> int:
    """Whole-second countdown from now to ``end_time``, never negative.

    Single source of truth shared by every code path that serialises
    ``time_remaining`` into a payload - listing dicts in
    ``routers/auctions``, the live-bid broadcast in ``routers/bids``,
    the auction-room WS frame in ``routers/websocket``, the
    user-participation rows. Inlining the formula per call site used
    to drift: one call kept the ``max(0, ...)`` clamp + an
    ``is_active`` guard, another didn't, so a freshly-settled lot
    could emit a negative ``time_remaining`` value over WS while the
    HTTP listing showed 0. Defaults match the strictest of the
    earlier inlinings (clamp + is_active guard).
    """
    if not end_time or not is_active:
        return 0
    return max(0, int((end_time - utcnow()).total_seconds()))
