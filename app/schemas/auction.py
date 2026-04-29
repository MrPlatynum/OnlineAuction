from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class AuctionCreate(BaseModel):
    title: str
    description: str
    starting_price: float = Field(gt=0)
    duration_minutes: int = Field(gt=0, le=10080)
    image_url: Optional[str] = None
    image_urls: Optional[List[str]] = None
    category_id: Optional[int] = None
    auction_type: str = "bid"
    bin_price: Optional[float] = None


class AuctionResponse(BaseModel):
    model_config = {"from_attributes": True}
    id: int
    title: str
    description: str
    starting_price: float
    current_price: float
    image_url: Optional[str]
    image_urls: Optional[List[str]] = None
    start_time: datetime
    end_time: datetime
    is_active: bool
    is_completed: bool = False
    winner_id: Optional[int]
    created_by: Optional[int] = None
    creator_username: Optional[str] = None
    creator_avatar_url: Optional[str] = None
    bids_count: Optional[int] = None
    time_remaining: Optional[int] = None
    category_id: Optional[int] = None
    category_name: Optional[str] = None
    category_icon: Optional[str] = None
    auction_type: Optional[str] = "bid"
    bin_price: Optional[float] = None


class PaginatedAuctionsResponse(BaseModel):
    items: List[AuctionResponse]
    total: int
    page: int
    page_size: int
    total_pages: int
