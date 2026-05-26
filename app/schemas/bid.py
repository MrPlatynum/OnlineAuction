from datetime import datetime

from pydantic import BaseModel, Field


class BidCreate(BaseModel):
    auction_id: int
    # Cap matches MAX_USER_BALANCE in routers/balance.py - a user can't
    # bid more than they could possibly hold. Without the upper bound a
    # value past ~10^10 would overflow Numeric(12, 2) at commit and
    # surface as an opaque 500.
    amount: float = Field(gt=0, le=10_000_000)


class BidResponse(BaseModel):
    model_config = {"from_attributes": True}
    id: int
    amount: float
    timestamp: datetime
    user_id: int
    username: str
    auction_id: int


class PaginatedBidsResponse(BaseModel):
    items: list[BidResponse]
    total: int
    page: int
    page_size: int
    total_pages: int
