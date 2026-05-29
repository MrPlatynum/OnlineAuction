"""Seller reviews.

A review is anchored to a settled auction the reviewer participated in -
either as the winning bidder or as the BIN buyer. The endpoints handle
creation, deletion by the author, and the seller-side aggregate
(average + per-rating histogram) consumed by the auction page.
"""

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.database import get_db
from app.models import Auction, Review, User
from app.schemas import ReviewCreate, SellerReviewsResponse
from app.utils.db import commit_or_409, ensure_seller_exists
from app.utils.rate_limit import limiter
from app.utils.security import get_current_user, require_verified_user
from app.utils.time import utcnow

# Reviews freeze 24 hours after creation: long enough that a reviewer
# can retract a mistake, short enough that the seller's review history
# isn't rewritable indefinitely (the original review-bombing surface
# was delete + immediate recreate to spam fresh notifications).
_REVIEW_EDIT_WINDOW = timedelta(hours=24)

router = APIRouter(prefix="/api", tags=["reviews"])

# Hard cap on the reviews list returned per seller. Stats (total, avg,
# distribution) are still computed over the full set; only the listed
# rows are bounded so a seller with thousands of reviews doesn't pull
# the whole table into memory on every page view.
_REVIEWS_LIST_CAP = 50


@router.get("/sellers/{seller_id}/reviews", response_model=SellerReviewsResponse)
async def get_seller_reviews(seller_id: int, db: AsyncSession = Depends(get_db)):
    # Probe user existence before serving review aggregates - otherwise
    # an unknown seller_id silently returns the same `{total: 0, avg: 0,
    # distribution: zeros, reviews: []}` shape as a real seller with no
    # reviews yet, and any client trying to tell the two apart can't.
    await ensure_seller_exists(db, seller_id)

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
                "reviewer_username": reviewers[r.reviewer_id].username if r.reviewer_id in reviewers else "-",
                "reviewer_avatar_url": reviewers[r.reviewer_id].avatar_url if r.reviewer_id in reviewers else None,
            }
            for r in reviews
        ],
    }


@router.post("/reviews")
@limiter.limit("10/minute")
async def create_review(
    request: Request,
    data: ReviewCreate,
    current_user: User = Depends(require_verified_user),
    db: AsyncSession = Depends(get_db),
):
    if data.seller_id == current_user.id:
        raise HTTPException(status_code=400, detail="Нельзя оставить отзыв о себе")
    await ensure_seller_exists(db, data.seller_id)

    # Reviewer must have actually transacted with this seller - won the
    # referenced completed auction (the only way Auction.winner_id is set
    # is through complete_auction or /buy-now). Without this gate, anyone
    # can post a review on any seller.
    qualifying = (
        await db.execute(
            select(Auction.id).where(
                Auction.id == data.auction_id,
                Auction.created_by == data.seller_id,
                Auction.winner_id == current_user.id,
                Auction.is_completed.is_(True),
            ).limit(1)
        )
    ).scalar_one_or_none()
    if not qualifying:
        raise HTTPException(
            status_code=403,
            detail="Можно оставить отзыв только продавцу, у которого вы что-то выиграли",
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
        raise HTTPException(status_code=400, detail="Вы уже оставили отзыв на этот аукцион")
    review = Review(
        seller_id=data.seller_id,
        reviewer_id=current_user.id,
        auction_id=data.auction_id,
        rating=data.rating,
        comment=data.comment,
    )
    db.add(review)
    # Two concurrent POSTs for the same (reviewer, auction) pair race
    # the INSERT; ``uq_reviews_one_per_auction`` surfaces the loser
    # through the shared 400 path.
    await commit_or_409(db, detail="Вы уже оставили отзыв на этот аукцион")
    return {"message": "Отзыв добавлен", "id": review.id}


@router.delete("/reviews/{review_id}")
@limiter.limit("10/minute")
async def delete_review(
    request: Request,
    review_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    review = (
        await db.execute(select(Review).where(Review.id == review_id))
    ).scalar_one_or_none()
    if not review:
        raise HTTPException(status_code=404, detail="Отзыв не найден")
    if review.reviewer_id != current_user.id:
        raise HTTPException(status_code=403, detail="Это не ваш отзыв")
    # Edit window: a review older than _REVIEW_EDIT_WINDOW is frozen.
    # Without this, a hostile reviewer could keep deleting and re-
    # creating the same one-star review to spam the seller with fresh
    # notifications, and the seller's review history would be
    # rewritable indefinitely.
    if utcnow() - review.created_at > _REVIEW_EDIT_WINDOW:
        raise HTTPException(
            status_code=400,
            detail="Отзыв нельзя удалить - окно редактирования истекло",
        )
    await db.delete(review)
    await db.commit()
    return {"message": "Отзыв удалён"}
