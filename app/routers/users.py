"""Public user profile + per-user notification preferences.

The profile endpoint returns the read-only view (lots created, bids
placed, win/lose counts, the seller's recent listings) consumed by
``user.html``. The notification-settings endpoint owns the
``notify_*`` flag toggles that gate email delivery in
``services.notifications.notify_user``.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.database import get_db
from app.models import Auction, Bid, User
from app.schemas import NotificationSettings
from app.utils.rate_limit import limiter
from app.utils.security import get_current_user
from app.utils.time import seconds_until

router = APIRouter(prefix="/api", tags=["users"])


@router.put("/notification-settings")
@limiter.limit("30/minute")
async def update_notification_settings(
    request: Request,
    settings: NotificationSettings,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    current_user.email_notifications = settings.email_notifications
    current_user.notify_outbid = settings.notify_outbid
    current_user.notify_winning = settings.notify_winning
    current_user.notify_ending = settings.notify_ending
    current_user.notify_sold = settings.notify_sold
    current_user.notify_bid_received = settings.notify_bid_received
    current_user.notify_lost = settings.notify_lost

    await db.commit()
    return {"message": "Настройки сохранены"}


@router.get("/users/{username}")
async def get_user_profile(username: str, db: AsyncSession = Depends(get_db)):
    user = (
        await db.execute(select(User).where(User.username == username))
    ).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    # Cap recent auctions in the response: a power-seller with thousands
    # of lots would otherwise serialise the whole list on every profile
    # hit. ``created_count`` below preserves the true total for the UI.
    USER_PROFILE_AUCTIONS_LIMIT = 100

    # Fold every aggregate count into a single SELECT with scalar
    # subqueries. The prior shape ran five sequential ``await
    # db.scalar / db.execute`` calls (created_count, total_bids,
    # bid_auction_ids, won_count, lost_count) - six round-trips per
    # profile hit on the unauthenticated public endpoint. Now: one
    # round-trip for the stats + one for the auctions list = two.
    # AsyncSession is not safe for concurrent use, so a single
    # SELECT beats asyncio.gather here.
    bid_auction_ids_subq = (
        select(Bid.auction_id)
        .where(Bid.user_id == user.id)
        .distinct()
        .scalar_subquery()
    )
    stats_row = (
        await db.execute(
            select(
                select(func.count())
                .select_from(Auction)
                .where(Auction.created_by == user.id)
                .scalar_subquery()
                .label("created_count"),
                select(func.count())
                .select_from(Bid)
                .where(Bid.user_id == user.id)
                .scalar_subquery()
                .label("total_bids"),
                select(func.count())
                .select_from(Auction)
                .where(
                    Auction.winner_id == user.id,
                    Auction.is_completed.is_(True),
                )
                .scalar_subquery()
                .label("won_count"),
                # SQL NULL semantics: ``winner_id != user.id`` is NULL
                # for completed lots that ended with no winner. Those
                # lots still count as "not won by this user", so OR-in
                # the NULL case explicitly.
                select(func.count())
                .select_from(Auction)
                .where(
                    Auction.id.in_(bid_auction_ids_subq),
                    Auction.is_completed.is_(True),
                    (Auction.winner_id != user.id) | Auction.winner_id.is_(None),
                )
                .scalar_subquery()
                .label("lost_count"),
            )
        )
    ).one()

    auctions = (
        await db.execute(
            select(Auction)
            .where(Auction.created_by == user.id)
            .order_by(Auction.start_time.desc(), Auction.id.desc())
            .limit(USER_PROFILE_AUCTIONS_LIMIT)
        )
    ).scalars().all()

    auction_list = [
        {
            "id": a.id,
            "title": a.title,
            "current_price": float(a.current_price),
            "starting_price": float(a.starting_price),
            "is_active": a.is_active,
            "is_completed": a.is_completed,
            "end_time": a.end_time.isoformat(),
            "winner_id": a.winner_id,
            "image_url": a.image_url,
            "time_remaining": seconds_until(a.end_time, is_active=a.is_active),
        }
        for a in auctions
    ]

    return {
        "user": {
            "id": user.id,
            "username": user.username,
            "avatar_url": user.avatar_url,
            "created_at": user.created_at.isoformat() if user.created_at else None,
        },
        "auctions": auction_list,
        "stats": {
            "created_count": stats_row.created_count,
            "total_bids": stats_row.total_bids,
            "won_count": stats_row.won_count,
            "lost_count": stats_row.lost_count,
        },
    }
