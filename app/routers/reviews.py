from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Auction, Review, User
from app.schemas import ReviewCreate
from app.utils.security import get_current_user

router = APIRouter(prefix="/api", tags=["reviews"])


@router.get("/sellers/{seller_id}/reviews")
def get_seller_reviews(seller_id: int, db: Session = Depends(get_db)):
    reviews = (
        db.query(Review)
        .filter(Review.seller_id == seller_id)
        .order_by(Review.created_at.desc())
        .all()
    )
    total = len(reviews)
    avg = round(sum(r.rating for r in reviews) / total, 1) if total else 0
    dist = {i: 0 for i in range(1, 6)}
    for r in reviews:
        dist[r.rating] = dist.get(r.rating, 0) + 1

    reviewer_ids = [r.reviewer_id for r in reviews]
    reviewers = (
        {u.id: u for u in db.query(User).filter(User.id.in_(reviewer_ids)).all()}
        if reviewer_ids
        else {}
    )

    auction_ids = [r.auction_id for r in reviews if r.auction_id]
    auctions_map = (
        {a.id: a for a in db.query(Auction).filter(Auction.id.in_(auction_ids)).all()}
        if auction_ids
        else {}
    )

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
def create_review(
    data: ReviewCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if data.seller_id == current_user.id:
        raise HTTPException(400, "Нельзя оставить отзыв о себе")
    seller = db.query(User).filter(User.id == data.seller_id).first()
    if not seller:
        raise HTTPException(404, "Продавец не найден")
    if data.auction_id:
        exists = (
            db.query(Review)
            .filter(
                Review.reviewer_id == current_user.id,
                Review.auction_id == data.auction_id,
            )
            .first()
        )
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
    db.commit()
    return {"message": "Отзыв добавлен", "id": review.id}


@router.delete("/reviews/{review_id}")
def delete_review(
    review_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    review = db.query(Review).filter(Review.id == review_id).first()
    if not review:
        raise HTTPException(404, "Отзыв не найден")
    if review.reviewer_id != current_user.id:
        raise HTTPException(403, "Нельзя удалить чужой отзыв")
    db.delete(review)
    db.commit()
    return {"message": "Отзыв удалён"}
