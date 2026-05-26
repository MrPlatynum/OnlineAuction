
from pydantic import BaseModel, Field

REVIEW_COMMENT_MAX = 1000  # also used by the frontend - keep in sync


class ReviewCreate(BaseModel):
    seller_id: int
    # Required: every review must be tied to a specific won auction. With
    # auction_id optional, the (reviewer_id, auction_id) UNIQUE constraint
    # treated NULLs as distinct (Postgres semantics) - a reviewer could
    # spam unlimited "general" reviews on the same seller once they'd won
    # any auction from them.
    auction_id: int
    rating: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=REVIEW_COMMENT_MAX)


class SellerReviewsStats(BaseModel):
    """Aggregate over the full reviews set for a seller. ``distribution``
    is a 1..5 -> count map; JSON serialisation turns the int keys into
    strings, which is what the frontend reads as ``distribution['5']``."""
    total: int
    avg: float
    distribution: dict[int, int]


class SellerReviewItem(BaseModel):
    """One row in the paginated reviews list. ``created_at`` is the
    pre-formatted ISO string the router builds (kept as str to avoid
    a round-trip through datetime parse + re-emit)."""
    id: int
    rating: int
    comment: str | None
    created_at: str
    auction_id: int | None
    auction_title: str | None
    reviewer_username: str
    reviewer_avatar_url: str | None


class SellerReviewsResponse(BaseModel):
    """GET /api/sellers/{id}/reviews payload. Tests consume
    ``body['stats']['avg']`` and ``body['reviews']`` directly."""
    stats: SellerReviewsStats
    reviews: list[SellerReviewItem]
