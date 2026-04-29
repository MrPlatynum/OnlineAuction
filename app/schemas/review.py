from typing import Optional

from pydantic import BaseModel, Field


class ReviewCreate(BaseModel):
    seller_id: int
    auction_id: Optional[int] = None
    rating: int = Field(ge=1, le=5)
    comment: Optional[str] = None
