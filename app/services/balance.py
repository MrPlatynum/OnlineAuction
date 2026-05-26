"""Balance availability calculations.

A user's nominal ``balance`` field doesn't tell the whole story. While
they're the current top bidder on one or more active auctions, that
money is committed: if those auctions end with them as winner, the
amount is debited at completion time. So when checking whether they
can afford a *new* bid we need to subtract those existing commitments
from their balance.
"""

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Auction, Bid, User


async def lock_users_by_id(db: AsyncSession, *user_ids: int) -> dict[int, User]:
    """Take ``SELECT ... FOR UPDATE`` row locks on the given users in
    ascending-id order to avoid deadlocks across transactions that
    touch the same pair of users (e.g. /buy-now and complete_auction).

    Returns the locked ``User`` instances keyed by id. Duplicates and
    ``None`` ids are filtered. ``populate_existing`` is set so any copy
    already in the session's identity map is refreshed from the locked
    row, not served stale.
    """
    sorted_ids = sorted({uid for uid in user_ids if uid is not None})
    locked: dict[int, User] = {}
    for uid in sorted_ids:
        user = (
            await db.execute(
                select(User)
                .where(User.id == uid)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if user is not None:
            locked[uid] = user
    return locked


async def get_committed_balance(db: AsyncSession, user_id: int) -> Decimal:
    """Sum of ``current_price`` for active auctions where ``user_id``
    is currently the leader (their latest bid amount equals
    ``auction.current_price``).

    One query: ``DISTINCT ON (auction_id) ... ORDER BY timestamp DESC``
    picks the latest bidder per auction (Postgres-specific), join to the
    active-auction set, sum the ``current_price`` of those where the
    leader is ``user_id``. Replaces the previous per-auction
    ``SELECT ... LIMIT 1`` loop, which was an N+1 on the bid path.
    """
    latest_bidder = (
        select(Bid.auction_id, Bid.user_id.label("leader_id"))
        .order_by(Bid.auction_id, Bid.timestamp.desc())
        .distinct(Bid.auction_id)
        .subquery()
    )
    total = await db.scalar(
        select(func.coalesce(func.sum(Auction.current_price), 0))
        .join(latest_bidder, latest_bidder.c.auction_id == Auction.id)
        .where(
            Auction.is_active.is_(True),
            latest_bidder.c.leader_id == user_id,
        )
    )
    return Decimal(str(total or 0))


async def effective_committed_balance(
    db: AsyncSession,
    user_id: int,
    current_auction_id: int,
    current_price: Decimal,
) -> Decimal:
    """Committed balance excluding any existing commit on the auction
    we're about to bid on - that commit is about to be replaced by the
    new bid amount, so it shouldn't count against availability.

    Caller invariant: must hold ``SELECT ... FOR UPDATE`` on the user
    row (via ``lock_users_by_id``) *before* calling this. Without the
    user-row lock, a concurrent ``complete_auction`` of another lot
    where the same user leads could deduct from ``user.balance``
    between our committed-balance read and the caller's availability
    arithmetic, surfacing as a false-negative "недостаточно средств"
    on a bid that would otherwise have fit. The committed query
    itself is intentionally unlocked - it reads many auction rows at
    once and locking them would deadlock against bid placement on
    those same auctions."""
    committed = await get_committed_balance(db, user_id)

    last_bid = (
        await db.execute(
            select(Bid)
            .where(Bid.auction_id == current_auction_id)
            .order_by(Bid.timestamp.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if last_bid and last_bid.user_id == user_id:
        committed -= current_price
    return committed
