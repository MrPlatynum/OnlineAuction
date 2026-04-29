"""Balance availability calculations.

A user's nominal ``balance`` field doesn't tell the whole story. While
they're the current top bidder on one or more active auctions, that
money is committed: if those auctions end with them as winner, the
amount is debited at completion time. So when checking whether they
can afford a *new* bid we need to subtract those existing commitments
from their balance.
"""

from sqlalchemy.orm import Session

from app.models import Auction, Bid


def get_committed_balance(db: Session, user_id: int) -> float:
    """Sum of ``current_price`` for active auctions where ``user_id``
    is currently the leader (their latest bid amount equals
    ``auction.current_price``)."""
    bid_auction_ids = (
        db.query(Bid.auction_id).filter(Bid.user_id == user_id).distinct().all()
    )
    if not bid_auction_ids:
        return 0.0

    auction_ids = [aid for (aid,) in bid_auction_ids]
    active_auctions = (
        db.query(Auction)
        .filter(Auction.id.in_(auction_ids), Auction.is_active == True)
        .all()
    )

    total = 0.0
    for auction in active_auctions:
        last_bid = (
            db.query(Bid)
            .filter(Bid.auction_id == auction.id)
            .order_by(Bid.timestamp.desc())
            .first()
        )
        if last_bid and last_bid.user_id == user_id:
            total += auction.current_price
    return total


def effective_committed_balance(
    db: Session, user_id: int, current_auction_id: int, current_price: float
) -> float:
    """Committed balance excluding any existing commit on the auction
    we're about to bid on — that commit is about to be replaced by the
    new bid amount, so it shouldn't count against availability."""
    committed = get_committed_balance(db, user_id)

    last_bid = (
        db.query(Bid)
        .filter(Bid.auction_id == current_auction_id)
        .order_by(Bid.timestamp.desc())
        .first()
    )
    if last_bid and last_bid.user_id == user_id:
        committed -= current_price
    return committed
