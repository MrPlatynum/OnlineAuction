from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Auction, Review, User
from app.schemas import ReviewCreate
from app.utils.security import get_current_user, require_verified_user

router = APIRouter(prefix="/api", tags=["reviews"])

# Hard cap on the reviews list returned per seller. Stats (total, avg,
# distribution) are still computed over the full set; only the listed
# rows are bounded so a seller with thousands of reviews doesn't pull
# the whole table into memory on every page view.
_REVIEWS_LIST_CAP = 50


@router.get("/sellers/{seller_id}/reviews")
async def get_seller_reviews(seller_id: int, db: AsyncSession = Depends(get_db)):
    base_filter = Review.seller_id == seller_id

    total = await db.scalar(
        select(func.count()).select_from(Review).where(base_filter)
    )

    avg = 0
    dist = {i: 0 for i in range(1, 6)}
    if total:
        avg_val = await db.scalar(
            select(func.avg(Review.rating)).where(base_filter)
        )
        avg = round(float(avg_val), 1)
        for rating, cnt in (
            await db.execute(
                select(Review.rating, func.count(Review.id))
                .where(base_filter)
                .group_by(Review.rating)
            )
        ).all():
            dist[rating] = cnt

    reviews = (
        await db.execute(
            select(Review)
            .where(base_filter)
            .order_by(Review.created_at.desc())
            .limit(_REVIEWS_LIST_CAP)
        )
    ).scalars().all()

    reviewer_ids = [r.reviewer_id for r in reviews]
    if reviewer_ids:
        users = (
            await db.execute(select(User).where(User.id.in_(reviewer_ids)))
        ).scalars().all()
        reviewers = {u.id: u for u in users}
    else:
        reviewers = {}

    auction_ids = [r.auction_id for r in reviews if r.auction_id]
    if auction_ids:
        auctions = (
            await db.execute(select(Auction).where(Auction.id.in_(auction_ids)))
        ).scalars().all()
        auctions_map = {a.id: a for a in auctions}
    else:
        auctions_map = {}

    return {
        "stats": {"total": total, "avg": avg, "distribution": dist},
        "reviews": [
            {
                "id": r.id,
                "rating": r.rating,
                "comment": r.comment,
                "created_at": r.created_at.isoformat(),
                "auction_id": r.auction_id,
                "auction_title": auctions_map[r.auction_id].title if r.auction_id and r.auction_id in auctions_map else None,
                "reviewer_username": reviewers[r.reviewer_id].username if r.reviewer_id in reviewers else "—",
                "reviewer_avatar_url": reviewers[r.reviewer_id].avatar_url if r.reviewer_id in reviewers else None,
            }
            for r in reviews
        ],
    }


@router.post("/reviews")
async def create_review(
    data: ReviewCreate,
    current_user: User = Depends(require_verified_user),
    db: AsyncSession = Depends(get_db),
):
    if data.seller_id == current_user.id:
        raise HTTPException(400, "Нельзя оставить отзыв о себе")
    seller = (
        await db.execute(select(User).where(User.id == data.seller_id))
    ).scalar_one_or_none()
    if not seller:
        raise HTTPException(404, "Продавец не найден")

    # Reviewer must have actually transacted with this seller — won the
    # referenced completed auction (the only way Auction.winner_id is set
    # is through complete_auction or /buy-now). Without this gate, anyone
    # can post a review on any seller.
    qualifying = (
        await db.execute(
            select(Auction.id).where(
                Auction.id == data.auction_id,
                Auction.created_by == data.seller_id,
                Auction.winner_id == current_user.id,
                Auction.is_completed == True,
            ).limit(1)
        )
    ).scalar_one_or_none()
    if not qualifying:
        raise HTTPException(
            403, "Можно оставить отзыв только продавцу, у которого вы что-то выиграли"
        )

    exists = (
        await db.execute(
            select(Review).where(
                Review.reviewer_id == current_user.id,
                Review.auction_id == data.auction_id,
            )
        )
    ).scalar_one_or_none()
    if exists:
        raise HTTPException(400, "Вы уже оставили отзыв на этот аукцион")
    review = Review(
        seller_id=data.seller_id,
        reviewer_id=current_user.id,
        auction_id=data.auction_id,
        rating=data.rating,
        comment=data.comment,
    )
    db.add(review)
    await db.commit()
    return {"message": "Отзыв добавлен", "id": review.id}


@router.delete("/reviews/{review_id}")
async def delete_review(
    review_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    review = (
        await db.execute(select(Review).where(Review.id == review_id))
    ).scalar_one_or_none()
    if not review:
        raise HTTPException(404, "Отзыв не найден")
    if review.reviewer_id != current_user.id:
        raise HTTPException(403, "Нельзя удалить чужой отзыв")
    await db.delete(review)
    await db.commit()
    return {"message": "Отзыв удалён"}
