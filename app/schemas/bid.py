from datetime import datetime
from typing import List

from pydantic import BaseModel, Field


class BidCreate(BaseModel):
    auction_id: int
    amount: float = Field(gt=0)


class BidResponse(BaseModel):
    model_config = {"from_attributes": True}
    id: int
    amount: float
    timestamp: datetime
    user_id: int
    username: str
    auction_id: int


class PaginatedBidsResponse(BaseModel):
    items: List[BidResponse]
    total: int
    page: int
    page_size: int
    total_pages: int
