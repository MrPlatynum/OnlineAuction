"""Per-auction asyncio locks.

Serialise the read-check-write sequence inside ``place_bid`` so two
concurrent bids on the same auction can't both pass the
``bid.amount > current_price`` check before either commits.

This works for a single FastAPI process. Scaling to multiple workers
would require a database-level lock (``SELECT FOR UPDATE`` on Postgres
or MySQL) or an external coordinator like Redis.
"""

import asyncio
from collections import defaultdict


_bid_locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)


def get_bid_lock(auction_id: int) -> asyncio.Lock:
    return _bid_locks[auction_id]
