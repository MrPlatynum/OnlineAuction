from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Auction, Bid, User
from app.schemas import NotificationSettings
from app.utils.security import get_current_user

router = APIRouter(prefix="/api", tags=["users"])


@router.put("/notification-settings")
async def update_notification_settings(
    settings: NotificationSettings,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    current_user.email_notifications = settings.email_notifications
    current_user.notify_outbid = settings.notify_outbid
    current_user.notify_winning = settings.notify_winning
    current_user.notify_ending = settings.notify_ending
    current_user.notify_sold = settings.notify_sold

    await db.commit()
    return {"message": "Settings updated successfully"}


@router.get("/users/{username}")
async def get_user_profile(username: str, db: AsyncSession = Depends(get_db)):
    user = (
        await db.execute(select(User).where(User.username == username))
    ).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    auctions = (
        await db.execute(
            select(Auction)
            .where(Auction.created_by == user.id)
            .order_by(Auction.start_time.desc())
        )
    ).scalars().all()
    my_bids = (
        await db.execute(select(Bid).where(Bid.user_id == user.id))
    ).scalars().all()
    bid_auction_ids = list({b.auction_id for b in my_bids})

    won_count = await db.scalar(
        select(func.count())
        .select_from(Auction)
        .where(Auction.winner_id == user.id, Auction.is_completed == True)
    )

    if bid_auction_ids:
        lost_count = await db.scalar(
            select(func.count())
            .select_from(Auction)
            .where(
                Auction.id.in_(bid_auction_ids),
                Auction.is_completed == True,
                Auction.winner_id != user.id,
            )
        )
    else:
        lost_count = 0

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
            "created_count": len(auctions),
            "total_bids": len(my_bids),
            "won_count": won_count,
            "lost_count": lost_count,
        },
    }
