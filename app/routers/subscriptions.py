"""Seller subscriptions.

A logged-in user can subscribe to another user's storefront; when the
seller posts a new lot, ``NEW_LOT`` notifications fan out to every
subscriber through ``services.notifications``. The endpoints handle
toggling the subscription, listing the caller's subscriptions, and
exposing the subscriber count for the seller's public profile.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.database import get_db
from app.models import Auction, Review, Subscription, User
from app.utils.db import ensure_seller_exists
from app.utils.rate_limit import limiter
from app.utils.security import get_current_user

router = APIRouter(prefix="/api", tags=["subscriptions"])


async def _subscriber_count(db: AsyncSession, seller_id: int) -> int:
    """Total subscribers for ``seller_id``. Shared between the three
    endpoints (toggle, status probe, unsubscribe) that each respond with
    the updated count after their mutation - keeps the COUNT(*) query in
    one place so the future Subscription model change touches one site."""
    return await db.scalar(
        select(func.count())
        .select_from(Subscription)
        .where(Subscription.seller_id == seller_id)
    )


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
    if not subs:
        return []

    seller_ids = [s.seller_id for s in subs]

    # Bulk-fetch sellers, lot counts, and review stats for the whole
    # subscription set in three aggregate queries instead of four
    # round-trips per subscription.
    sellers = {
        u.id: u
        for u in (
            await db.execute(select(User).where(User.id.in_(seller_ids)))
        ).scalars()
    }

    lot_stats: dict[int, tuple[int, int]] = {}
    for sid, total, active in (
        await db.execute(
            select(
                Auction.created_by,
                func.count(Auction.id),
                func.coalesce(
                    func.sum(case((Auction.is_active, 1), else_=0)), 0
                ),
            )
            .where(Auction.created_by.in_(seller_ids))
            .group_by(Auction.created_by)
        )
    ).all():
        lot_stats[sid] = (int(total), int(active))

    review_stats: dict[int, tuple[int, float]] = {}
    for sid, cnt, avg in (
        await db.execute(
            select(
                Review.seller_id,
                func.count(Review.id),
                func.avg(Review.rating),
            )
            .where(Review.seller_id.in_(seller_ids))
            .group_by(Review.seller_id)
        )
    ).all():
        review_stats[sid] = (int(cnt), round(float(avg), 1) if avg else 0)

    result = []
    for sub in subs:
        seller = sellers.get(sub.seller_id)
        if not seller:
            continue
        lots_count, active_lots_count = lot_stats.get(seller.id, (0, 0))
        reviews_count, avg_rating = review_stats.get(seller.id, (0, 0))
        result.append({
            "seller_id": seller.id,
            "username": seller.username,
            "avatar_url": seller.avatar_url,
            "lots_count": lots_count,
            "active_lots_count": active_lots_count,
            "reviews_count": reviews_count,
            "avg_rating": avg_rating,
            "subscribed_at": sub.created_at.isoformat(),
        })
    return result


@router.get("/sellers/{seller_id}/subscription")
async def get_subscription(
    seller_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Probe user existence so the UI can tell "real seller, you're not
    # subscribed yet" from "this seller does not exist" - otherwise both
    # answers come back as {subscribed: false, subscribers_count: 0} and
    # a typo'd profile link silently renders a working Subscribe button
    # whose POST then 404s.
    await ensure_seller_exists(db, seller_id)

    sub = (
        await db.execute(
            select(Subscription).where(
                Subscription.subscriber_id == current_user.id,
                Subscription.seller_id == seller_id,
            )
        )
    ).scalar_one_or_none()
    count = await _subscriber_count(db, seller_id)
    return {"subscribed": sub is not None, "subscribers_count": count}


@router.post("/sellers/{seller_id}/subscribe")
@limiter.limit("60/minute")
async def subscribe(
    request: Request,
    seller_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if seller_id == current_user.id:
        raise HTTPException(status_code=400, detail="Нельзя подписаться на себя")
    # Pre-check existence instead of letting the FK violation bubble as
    # 500 - a non-existent seller_id is a client mistake (stale link),
    # not an internal error.
    await ensure_seller_exists(db, seller_id)
    exists = (
        await db.execute(
            select(Subscription).where(
                Subscription.subscriber_id == current_user.id,
                Subscription.seller_id == seller_id,
            )
        )
    ).scalar_one_or_none()
    # Idempotent: a repeated POST on an existing subscription returns
    # the same 200 shape as a fresh subscribe, not 400. This matches
    # the convention every double-click-prone button expects (the UI
    # can retry on dropped responses without surfacing a fake error).
    if exists:
        count = await _subscriber_count(db, seller_id)
        return {"subscribed": True, "subscribers_count": count}
    db.add(Subscription(subscriber_id=current_user.id, seller_id=seller_id))
    # Two concurrent /subscribe calls on the same (subscriber, seller)
    # pair race the INSERT; the unique constraint loser is rolled back
    # and collapsed into the same idempotent "subscribed" response as
    # the winner. ``commit_or_409`` is bypassed here because its 400
    # raise contradicts the idempotency contract.
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
    count = await _subscriber_count(db, seller_id)
    return {"subscribed": True, "subscribers_count": count}


@router.delete("/sellers/{seller_id}/subscribe")
@limiter.limit("60/minute")
async def unsubscribe(
    request: Request,
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
    # Idempotent: DELETE on a missing subscription returns the same 200
    # shape as a successful unsubscribe (subscribed: false) instead of
    # 400. A reconciliation flow ("UI says subscribed, server says no -
    # retry DELETE") then converges instead of looping on a fake error.
    if sub is not None:
        await db.delete(sub)
        await db.commit()
    count = await _subscriber_count(db, seller_id)
    return {"subscribed": False, "subscribers_count": count}
