"""Balance availability calculations.

A user's nominal ``balance`` field doesn't tell the whole story. While
they're the current top bidder on one or more active auctions, that
money is committed: if those auctions end with them as winner, the
amount is debited at completion time. So when checking whether they
can afford a *new* bid we need to subtract those existing commitments
from their balance.
"""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Auction, Bid


async def get_committed_balance(db: AsyncSession, user_id: int) -> Decimal:
    """Sum of ``current_price`` for active auctions where ``user_id``
    is currently the leader (their latest bid amount equals
    ``auction.current_price``)."""
    auction_id_rows = (
        await db.execute(
            select(Bid.auction_id).where(Bid.user_id == user_id).distinct()
        )
    ).all()
    if not auction_id_rows:
        return Decimal("0")

    auction_ids = [aid for (aid,) in auction_id_rows]
    active_auctions = (
        await db.execute(
            select(Auction).where(
                Auction.id.in_(auction_ids), Auction.is_active == True
            )
        )
    ).scalars().all()

    total = Decimal("0")
    for auction in active_auctions:
        last_bid = (
            await db.execute(
                select(Bid)
                .where(Bid.auction_id == auction.id)
                .order_by(Bid.timestamp.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if last_bid and last_bid.user_id == user_id:
            total += auction.current_price
    return total


async def effective_committed_balance(
    db: AsyncSession,
    user_id: int,
    current_auction_id: int,
    current_price: Decimal,
) -> Decimal:
    """Committed balance excluding any existing commit on the auction
    we're about to bid on — that commit is about to be replaced by the
    new bid amount, so it shouldn't count against availability."""
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
