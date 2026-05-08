"""SlowAPI rate-limiter wired by IP.

Only sensitive endpoints carry an explicit ``@limiter.limit(...)`` —
everything else stays unmetered. The limiter can be turned off via
``AUCTION_RATE_LIMIT_ENABLED=false`` so the test suite (which fires
many requests at 127.0.0.1 inside one minute) doesn't trip itself.
"""

import os

from slowapi import Limiter
from slowapi.util import get_remote_address


def _is_enabled() -> bool:
    return os.getenv("AUCTION_RATE_LIMIT_ENABLED", "true").lower() not in {
        "false", "0", "no", "off",
    }


limiter = Limiter(key_func=get_remote_address, enabled=_is_enabled())
