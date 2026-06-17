"""Shared pagination helpers. Every paginated listing route in
``app/routers`` exposes the same dict shape (``items``, ``total``,
``page``, ``page_size``, ``total_pages``); inlining
``(total + page_size - 1) // page_size`` per route is what let the
"empty result -> total_pages=0 vs total_pages=1" drift creep in.
"""


def total_pages_for(total: int, page_size: int) -> int:
    """Ceiling-divide ``total`` by ``page_size``. Returns 0 for an
    empty result instead of 1 - the listing API contract states
    "no rows means no pages", and frontend pagers rely on it for
    the "no results" empty state."""
    if total <= 0 or page_size <= 0:
        return 0
    return (total + page_size - 1) // page_size
