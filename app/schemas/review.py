
from pydantic import BaseModel, Field

REVIEW_COMMENT_MAX = 1000  # тоже используется на фронте — держим в синхроне


class ReviewCreate(BaseModel):
    seller_id: int
    # Required: every review must be tied to a specific won auction. With
    # auction_id optional, the (reviewer_id, auction_id) UNIQUE constraint
    # treated NULLs as distinct (Postgres semantics) — a reviewer could
    # spam unlimited "general" reviews on the same seller once they'd won
    # any auction from them.
    auction_id: int
    rating: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=REVIEW_COMMENT_MAX)
