from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.utils.money import MAX_USER_BALANCE


class BidCreate(BaseModel):
    auction_id: int
    # Cap matches MAX_USER_BALANCE - a user can't bid more than they
    # could possibly hold. Single source of truth in utils/money.py
    # so changing the cap is one edit, not a sweep across schemas.
    # decimal_places=2 rejects sub-cent values at the boundary
    # instead of silently half-up rounding them later (a 100.005 bid
    # was previously credited as 100.01).
    amount: Decimal = Field(gt=0, le=MAX_USER_BALANCE, decimal_places=2)


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
