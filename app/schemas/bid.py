from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class BidCreate(BaseModel):
    auction_id: int
    # Cap matches MAX_USER_BALANCE in routers/balance.py - a user can't
    # bid more than they could possibly hold. Without the upper bound a
    # value past ~10^10 would overflow Numeric(12, 2) at commit and
    # surface as an opaque 500. decimal_places=2 rejects sub-cent
    # values at the boundary instead of silently half-up rounding them
    # later (a 100.005 bid was previously credited as 100.01).
    amount: Decimal = Field(gt=0, le=Decimal("10000000"), decimal_places=2)


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
