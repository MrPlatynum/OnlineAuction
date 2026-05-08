from typing import Optional

from pydantic import BaseModel, Field

REVIEW_COMMENT_MAX = 1000  # тоже используется на фронте — держим в синхроне


class ReviewCreate(BaseModel):
    seller_id: int
    auction_id: Optional[int] = None
    rating: int = Field(ge=1, le=5)
    comment: Optional[str] = Field(default=None, max_length=REVIEW_COMMENT_MAX)
