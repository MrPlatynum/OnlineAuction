from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models import Auction, Bid, NotificationType, User
from app.schemas import BidCreate, BidResponse, PaginatedBidsResponse
from app.services.balance import effective_committed_balance
from app.services.notifications import notify_user
from app.services.websocket_manager import manager
from app.utils.money import to_decimal
from app.utils.rate_limit import limiter
from app.utils.security import get_current_user
from app.utils.time import utcnow

router = APIRouter(prefix="/api", tags=["bids"])


@router.get("/auctions/{auction_id}/bids", response_model=PaginatedBidsResponse)
async def get_auction_bids(
    auction_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    base_filter = Bid.auction_id == auction_id
    total = await db.scalar(
        select(func.count()).select_from(Bid).where(base_filter)
    )
    total_pages = (total + page_size - 1) // page_size

    offset = (page - 1) * page_size
    bids = (
        await db.execute(
            select(Bid)
            .where(base_filter)
            .options(selectinload(Bid.user))
            .order_by(Bid.timestamp.desc())
            .offset(offset)
            .limit(page_size)
        )
    ).scalars().all()

    result = [
        BidResponse(
            id=bid.id,
            amount=bid.amount,
            timestamp=bid.timestamp,
            user_id=bid.user_id,
            username=bid.user.username,
            auction_id=bid.auction_id,
        )
        for bid in bids
    ]

    return PaginatedBidsResponse(
        items=result,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.post("/bids")
@limiter.limit("60/minute")
async def place_bid(
    request: Request,
    bid: BidCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    bid_amount = to_decimal(bid.amount)

    # Take a row-level lock on the auction for the rest of this transaction.
    # Concurrent bids on the same auction queue here at the database, so the
    # read-check-write below is atomic across all workers/processes.
    auction = (
        await db.execute(
            select(Auction).where(Auction.id == bid.auction_id).with_for_update()
        )
    ).scalar_one_or_none()
    if not auction:
        raise HTTPException(status_code=404, detail="Auction not found")

    if not auction.is_active:
        raise HTTPException(status_code=400, detail="Auction is not active")

    if utcnow() > auction.end_time:
        auction.is_active = False
        await db.commit()
        raise HTTPException(status_code=400, detail="Auction has ended")

    if bid_amount <= auction.current_price:
        raise HTTPException(status_code=400, detail="Bid must be higher than current price")

    committed_elsewhere = await effective_committed_balance(
        db, current_user.id, bid.auction_id, auction.current_price
    )
    available = current_user.balance - committed_elsewhere
    if available < bid_amount:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Insufficient available balance. You have ${available:.2f} available "
                f"(${committed_elsewhere:.2f} already committed to other active auctions)."
            ),
        )

    previous_leader_bid = (
        await db.execute(
            select(Bid)
            .where(Bid.auction_id == bid.auction_id)
            .order_by(Bid.timestamp.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    db_bid = Bid(amount=bid_amount, user_id=current_user.id, auction_id=bid.auction_id)
    auction.current_price = bid_amount

    db.add(db_bid)
    await db.commit()
    await db.refresh(db_bid)

    if previous_leader_bid and previous_leader_bid.user_id != current_user.id:
        previous_leader = (
            await db.execute(select(User).where(User.id == previous_leader_bid.user_id))
        ).scalar_one_or_none()
        if previous_leader:
            await notify_user(
                db, previous_leader, NotificationType.BID_OUTBID,
                "😔 Вашу ставку перебили",
                f"{current_user.username} сделал ставку ${bid.amount:.2f}. Сделайте новую ставку, чтобы вернуть лидерство!",
                auction.id, auction.title, manager,
            )

    creator = (
        await db.execute(select(User).where(User.id == auction.created_by))
    ).scalar_one_or_none()
    if creator and creator.id != current_user.id:
        await notify_user(
            db, creator, NotificationType.BID_PLACED,
            "🎯 Новая ставка на ваш лот",
            f"{current_user.username} сделал ставку ${bid.amount:.2f}",
            auction.id, auction.title, manager,
        )

    await manager.broadcast({
        "type": "new_bid",
        "bid": {
            "id": db_bid.id,
            "amount": float(db_bid.amount),
            "username": current_user.username,
            "timestamp": db_bid.timestamp.isoformat(),
        },
        "current_price": float(auction.current_price),
    }, bid.auction_id)

    return {"message": "Bid placed successfully", "bid_id": db_bid.id}
