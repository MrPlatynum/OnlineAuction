from datetime import UTC, datetime


def utcnow() -> datetime:
    """Return the current UTC time as a tz-aware datetime.

    Replacement for the deprecated ``datetime.utcnow()``. Aware (not
    naive) is the load-bearing choice: every ``DateTime`` column is
    declared ``DateTime(timezone=True)``, so a naive value mixed with
    a DB-loaded aware value would raise on subtraction or comparison.
    Serialising aware datetimes also emits the ``+00:00`` suffix in
    ISO format so the JS client parses them as UTC instead of
    interpreting them as the browser's local time zone.
    """
    return datetime.now(UTC)


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
