from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Auction, Review, Subscription, User
from app.utils.security import get_current_user

router = APIRouter(prefix="/api", tags=["subscriptions"])


@router.get("/my/subscriptions")
def get_my_subscriptions(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    subs = (
        db.query(Subscription)
        .filter(Subscription.subscriber_id == current_user.id)
        .order_by(Subscription.created_at.desc())
        .all()
    )

    result = []
    for sub in subs:
        seller = db.query(User).filter(User.id == sub.seller_id).first()
        if not seller:
            continue
        lots_count = db.query(Auction).filter(Auction.created_by == seller.id).count()
        reviews = db.query(Review).filter(Review.seller_id == seller.id).all()
        avg = round(sum(r.rating for r in reviews) / len(reviews), 1) if reviews else 0
        result.append({
            "seller_id": seller.id,
            "username": seller.username,
            "avatar_url": seller.avatar_url,
            "lots_count": lots_count,
            "active_lots_count": db.query(Auction).filter(
                Auction.created_by == seller.id, Auction.is_active == True
            ).count(),
            "reviews_count": len(reviews),
            "avg_rating": avg,
            "subscribed_at": sub.created_at.isoformat(),
        })
    return result


@router.get("/sellers/{seller_id}/subscription")
def get_subscription(
    seller_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    sub = (
        db.query(Subscription)
        .filter(
            Subscription.subscriber_id == current_user.id,
            Subscription.seller_id == seller_id,
        )
        .first()
    )
    count = db.query(Subscription).filter(Subscription.seller_id == seller_id).count()
    return {"subscribed": sub is not None, "subscribers_count": count}


@router.post("/sellers/{seller_id}/subscribe")
def subscribe(
    seller_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if seller_id == current_user.id:
        raise HTTPException(400, "Нельзя подписаться на себя")
    exists = (
        db.query(Subscription)
        .filter(
            Subscription.subscriber_id == current_user.id,
            Subscription.seller_id == seller_id,
        )
        .first()
    )
    if exists:
        raise HTTPException(400, "Уже подписаны")
    db.add(Subscription(subscriber_id=current_user.id, seller_id=seller_id))
    db.commit()
    count = db.query(Subscription).filter(Subscription.seller_id == seller_id).count()
    return {"subscribed": True, "subscribers_count": count}


@router.delete("/sellers/{seller_id}/subscribe")
def unsubscribe(
    seller_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    sub = (
        db.query(Subscription)
        .filter(
            Subscription.subscriber_id == current_user.id,
            Subscription.seller_id == seller_id,
        )
        .first()
    )
    if not sub:
        raise HTTPException(400, "Вы не подписаны")
    db.delete(sub)
    db.commit()
    count = db.query(Subscription).filter(Subscription.seller_id == seller_id).count()
    return {"subscribed": False, "subscribers_count": count}
