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
from app.utils.time import seconds_until, utcnow

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
    auctions = (
        await db.execute(
            select(Auction)
            .where(Auction.created_by == user.id)
            .order_by(Auction.start_time.desc())
            .limit(USER_PROFILE_AUCTIONS_LIMIT)
        )
    ).scalars().all()
    created_count = await db.scalar(
        select(func.count()).select_from(Auction).where(Auction.created_by == user.id)
    )
    total_bids = await db.scalar(
        select(func.count()).select_from(Bid).where(Bid.user_id == user.id)
    )
    bid_auction_ids = [
        aid for (aid,) in (
            await db.execute(
                select(Bid.auction_id).where(Bid.user_id == user.id).distinct()
            )
        ).all()
    ]

    won_count = await db.scalar(
        select(func.count())
        .select_from(Auction)
        .where(Auction.winner_id == user.id, Auction.is_completed.is_(True))
    )

    if bid_auction_ids:
        # SQL NULL semantics: ``winner_id != user.id`` evaluates to NULL
        # (and is therefore filtered out) for completed lots that ended
        # with no winner. Those lots still count as "not won by this
        # user", so OR-in the NULL case explicitly.
        lost_count = await db.scalar(
            select(func.count())
            .select_from(Auction)
            .where(
                Auction.id.in_(bid_auction_ids),
                Auction.is_completed.is_(True),
                (Auction.winner_id != user.id) | Auction.winner_id.is_(None),
            )
        )
    else:
        lost_count = 0

    now = utcnow()
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
            "created_count": created_count,
            "total_bids": total_bids,
            "won_count": won_count,
            "lost_count": lost_count,
        },
    }
