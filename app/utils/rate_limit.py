"""SlowAPI rate-limiter wired by IP.

Only sensitive endpoints carry an explicit ``@limiter.limit(...)`` —
everything else stays unmetered. The limiter can be turned off via
``AUCTION_RATE_LIMIT_ENABLED=false`` so the test suite (which fires
many requests at 127.0.0.1 inside one minute) doesn't trip itself.

Behind a reverse proxy the request.client.host is always the proxy's
own address — so without trusting a forwarded header every request
would share one bucket. ``AUCTION_TRUST_PROXY=true`` enables reading
the leftmost ``X-Forwarded-For`` entry, which is the standard "real
client" address set by nginx / Caddy / Cloudfront. Only enable when
the deployment actually has a proxy in front: a spoofable header
trusted on a direct-internet listener is worse than no limiter.
"""

import os

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request


def _is_enabled() -> bool:
    return os.getenv("AUCTION_RATE_LIMIT_ENABLED", "true").lower() not in {
        "false", "0", "no", "off",
    }


def _trust_proxy() -> bool:
    return os.getenv("AUCTION_TRUST_PROXY", "").lower() in {"true", "1", "yes", "on"}


def _client_key(request: Request) -> str:
    """Resolve the client identifier for the limiter bucket. Falls back
    to ``request.client.host`` when proxying isn't trusted (default)."""
    if _trust_proxy():
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            # Leftmost entry is the original client; the rest is the
            # proxy chain. Use a string split rather than a real parser
            # so we don't depend on a third-party header library.
            first = forwarded.split(",", 1)[0].strip()
            if first:
                return first
    return get_remote_address(request)


limiter = Limiter(key_func=_client_key, enabled=_is_enabled())
