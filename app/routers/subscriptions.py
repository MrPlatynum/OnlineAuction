from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Auction, Review, Subscription, User
from app.utils.security import get_current_user

router = APIRouter(prefix="/api", tags=["subscriptions"])


@router.get("/my/subscriptions")
async def get_my_subscriptions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    subs = (
        await db.execute(
            select(Subscription)
            .where(Subscription.subscriber_id == current_user.id)
            .order_by(Subscription.created_at.desc())
        )
    ).scalars().all()

    result = []
    for sub in subs:
        seller = (
            await db.execute(select(User).where(User.id == sub.seller_id))
        ).scalar_one_or_none()
        if not seller:
            continue
        lots_count = await db.scalar(
            select(func.count())
            .select_from(Auction)
            .where(Auction.created_by == seller.id)
        )
        active_lots_count = await db.scalar(
            select(func.count())
            .select_from(Auction)
            .where(Auction.created_by == seller.id, Auction.is_active == True)
        )
        reviews = (
            await db.execute(select(Review).where(Review.seller_id == seller.id))
        ).scalars().all()
        avg = round(sum(r.rating for r in reviews) / len(reviews), 1) if reviews else 0
        result.append({
            "seller_id": seller.id,
            "username": seller.username,
            "avatar_url": seller.avatar_url,
            "lots_count": lots_count,
            "active_lots_count": active_lots_count,
            "reviews_count": len(reviews),
            "avg_rating": avg,
            "subscribed_at": sub.created_at.isoformat(),
        })
    return result


@router.get("/sellers/{seller_id}/subscription")
async def get_subscription(
    seller_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    sub = (
        await db.execute(
            select(Subscription).where(
                Subscription.subscriber_id == current_user.id,
                Subscription.seller_id == seller_id,
            )
        )
    ).scalar_one_or_none()
    count = await db.scalar(
        select(func.count())
        .select_from(Subscription)
        .where(Subscription.seller_id == seller_id)
    )
    return {"subscribed": sub is not None, "subscribers_count": count}


@router.post("/sellers/{seller_id}/subscribe")
async def subscribe(
    seller_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if seller_id == current_user.id:
        raise HTTPException(400, "Нельзя подписаться на себя")
    exists = (
        await db.execute(
            select(Subscription).where(
                Subscription.subscriber_id == current_user.id,
                Subscription.seller_id == seller_id,
            )
        )
    ).scalar_one_or_none()
    if exists:
        raise HTTPException(400, "Уже подписаны")
    db.add(Subscription(subscriber_id=current_user.id, seller_id=seller_id))
    await db.commit()
    count = await db.scalar(
        select(func.count())
        .select_from(Subscription)
        .where(Subscription.seller_id == seller_id)
    )
    return {"subscribed": True, "subscribers_count": count}


@router.delete("/sellers/{seller_id}/subscribe")
async def unsubscribe(
    seller_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    sub = (
        await db.execute(
            select(Subscription).where(
                Subscription.subscriber_id == current_user.id,
                Subscription.seller_id == seller_id,
            )
        )
    ).scalar_one_or_none()
    if not sub:
        raise HTTPException(400, "Вы не подписаны")
    await db.delete(sub)
    await db.commit()
    count = await db.scalar(
        select(func.count())
        .select_from(Subscription)
        .where(Subscription.seller_id == seller_id)
    )
    return {"subscribed": False, "subscribers_count": count}
