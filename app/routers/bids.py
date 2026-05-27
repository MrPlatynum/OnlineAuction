"""Bid placement and bid-history listing.

``POST /bids`` is the concurrency-critical write path: it takes a
``SELECT FOR UPDATE`` on the auction row and locks the bidder's user
row via the sorted-ids helper from ``services.balance`` so two
simultaneous bids by the same user on different lots can't both pass
the available-balance check.
"""

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models import Auction, Bid, NotificationType, User
from app.schemas import BidCreate, BidResponse, PaginatedBidsResponse
from app.services import auction_scheduler
from app.services.balance import effective_committed_balance, lock_users_by_id
from app.services.notifications import notify_user
from app.services.websocket_manager import manager
from app.utils.money import to_decimal
from app.utils.pagination import total_pages_for
from app.utils.rate_limit import limiter
from app.utils.security import require_verified_user
from app.utils.time import seconds_until, utcnow

router = APIRouter(prefix="/api", tags=["bids"])


def _build_bid_broadcast(
    db_bid: Bid, auction: Auction, bidder_username: str, *, extended: bool
) -> dict:
    """Shape the WS payload announced to every /ws/auction/{id} subscriber
    when a new bid lands. Pulled out of the request handler so the
    bid-placement flow reads top-down without a 20-line dict literal in
    the middle, and so the schema is easier to keep aligned with the
    JS-side ``connectWS`` handler in static/js/auction.js. ``bidder_username``
    is passed in rather than read off ``db_bid.user`` because the bid row
    was just inserted - its ``user`` relationship isn't eager-loaded."""
    payload: dict = {
        "type": "new_bid",
        "bid": {
            "id": db_bid.id,
            "amount": float(db_bid.amount),
            "username": bidder_username,
            "timestamp": db_bid.timestamp.isoformat(),
        },
        "current_price": float(auction.current_price),
    }
    if extended:
        payload["extended_until"] = auction.end_time.isoformat()
        # Use the shared helper so a freshly-extended lot whose deadline
        # the scheduler is about to settle never emits a negative
        # value over WS - the clamp + is_active guard live in one place.
        payload["time_remaining"] = seconds_until(
            auction.end_time, is_active=auction.is_active
        )
    return payload


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
    total_pages = total_pages_for(total, page_size)

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
    current_user: User = Depends(require_verified_user),
    db: AsyncSession = Depends(get_db),
):
    bid_amount = to_decimal(bid.amount)

    # FOR UPDATE so concurrent bids on the same lot queue here at the DB -
    # the read-check-write below is atomic across workers.
    auction = (
        await db.execute(
            select(Auction).where(Auction.id == bid.auction_id).with_for_update()
        )
    ).scalar_one_or_none()
    if not auction:
        raise HTTPException(status_code=404, detail="Аукцион не найден")

    if not auction.is_active:
        raise HTTPException(status_code=400, detail="Аукцион неактивен")

    if auction.auction_type == "bin":
        # BIN lots are fixed-price listings, not auctions: buyers go through
        # /buy-now. Accepting bids here would let one user push current_price
        # past bin_price while another could still call /buy-now and grab the
        # lot at the lower fixed price.
        raise HTTPException(
            status_code=400,
            detail="Это лот с фиксированной ценой - ставки не принимаются, используйте «Купить сразу»",
        )

    if auction.created_by == current_user.id:
        raise HTTPException(status_code=400, detail="Нельзя делать ставки на свой собственный лот")

    if utcnow() > auction.end_time:
        # Don't flip is_active here. complete_auction is the single path
        # that finalises a lot (winner_id + balance transfer + notifications);
        # writing is_active=False from a request handler short-circuits the
        # scheduler's later tick and strands the lot with no payout.
        raise HTTPException(status_code=400, detail="Аукцион завершён")

    if bid_amount <= auction.current_price:
        raise HTTPException(status_code=400, detail="Ставка должна быть больше текущей цены")

    previous_leader_bid = (
        await db.execute(
            select(Bid)
            .where(Bid.auction_id == bid.auction_id)
            .order_by(Bid.timestamp.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    if previous_leader_bid and previous_leader_bid.user_id == current_user.id:
        raise HTTPException(
            status_code=400,
            detail="Вы уже лидируете в этом аукционе - дождитесь чужой ставки",
        )

    # Lock the bidder's user row before reading balance / committed-elsewhere.
    # Without this, two concurrent bids by the same user on *different* auctions
    # both pass the available-balance check independently (each holds a different
    # auction lock) and end up over-committing past the user's actual balance.
    await lock_users_by_id(db, current_user.id)

    committed_elsewhere = await effective_committed_balance(
        db, current_user.id, bid.auction_id, auction.current_price
    )
    available = current_user.balance - committed_elsewhere
    if available < bid_amount:
        msg = f"Недостаточно средств на балансе. Доступно {available:.2f} ₽"
        if committed_elsewhere > 0:
            msg += (
                f" ({committed_elsewhere:.2f} ₽ уже зарезервировано в других "
                f"активных аукционах)"
            )
        raise HTTPException(status_code=400, detail=msg + ".")

    db_bid = Bid(amount=bid_amount, user_id=current_user.id, auction_id=bid.auction_id)
    auction.current_price = bid_amount

    # Anti-sniping: a bid within the closing window resets end_time to a
    # full extension from "now". Resetting ending_soon_notified lets the
    # five-minute warning fire again ahead of the new deadline.
    extended = False
    # Lower-clamp to a positive delta: if the bid slipped past the line-140
    # expiry guard by microseconds (concurrent scheduler tick + FOR UPDATE
    # serialisation), `end_time - utcnow()` is negative and would otherwise
    # extend an auction that should have completed.
    delta = auction.end_time - utcnow()
    if timedelta(0) < delta < auction_scheduler.ANTISNIPING_WINDOW:
        auction.end_time = utcnow() + auction_scheduler.ANTISNIPING_EXTEND
        auction.ending_soon_notified = False
        extended = True

    db.add(db_bid)
    await db.commit()
    await db.refresh(db_bid)

    if extended:
        # Cancel the old completion task (still sleeping at the previous
        # end_time) and start a fresh one at the new deadline. Without this
        # the old task would still fire on schedule, see end_time > now in
        # _wait_and_complete, and self-reschedule - functionally correct but
        # leaves a needless extra wake-up.
        auction_scheduler.schedule_auction(auction)

    if previous_leader_bid and previous_leader_bid.user_id != current_user.id:
        previous_leader = (
            await db.execute(select(User).where(User.id == previous_leader_bid.user_id))
        ).scalar_one_or_none()
        if previous_leader:
            await notify_user(
                db, previous_leader, NotificationType.BID_OUTBID,
                "😔 Вашу ставку перебили",
                f"{current_user.username} сделал ставку {bid.amount:.2f} ₽. Сделайте новую ставку, чтобы вернуть лидерство!",
                auction.id, auction.title, manager,
            )

    creator = (
        await db.execute(select(User).where(User.id == auction.created_by))
    ).scalar_one_or_none()
    if creator and creator.id != current_user.id:
        await notify_user(
            db, creator, NotificationType.BID_PLACED,
            "🎯 Новая ставка на ваш лот",
            f"{current_user.username} сделал ставку {bid.amount:.2f} ₽",
            auction.id, auction.title, manager,
        )

    broadcast_payload = _build_bid_broadcast(
        db_bid, auction, current_user.username, extended=extended,
    )
    await manager.broadcast(broadcast_payload, bid.auction_id)

    return {
        "message": "Ставка принята",
        "bid_id": db_bid.id,
        "extended_until": auction.end_time.isoformat() if extended else None,
    }
