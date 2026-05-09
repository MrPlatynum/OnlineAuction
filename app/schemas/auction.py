from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


def _check_image_url(value: str) -> str:
    """Reject anything that's not an http(s) absolute URL or a same-site
    /-relative path. Without this, ``javascript:``, ``data:``, ``vbscript:``
    URLs flow into the DB and end up rendered as ``<img src="...">`` —
    which is the exact stored-XSS shape we already escape on the client,
    but defence-in-depth: don't accept hostile content in the first place.
    """
    if not isinstance(value, str) or not value:
        raise ValueError("URL must be a non-empty string")
    if value.startswith(("http://", "https://")):
        return value
    if value.startswith("/") and not value.startswith("//"):
        return value
    raise ValueError("URL must be http(s):// or a /-relative path")


class AuctionCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=10000)
    starting_price: float = Field(gt=0)
    duration_minutes: int = Field(gt=0, le=10080)
    image_url: Optional[str] = Field(default=None, max_length=2000)
    image_urls: Optional[list[str]] = Field(default=None, max_length=10)
    category_id: Optional[int] = None
    auction_type: Literal["bid", "bin"] = "bid"
    bin_price: Optional[float] = Field(default=None, gt=0)

    @field_validator("image_url")
    @classmethod
    def _v_image_url(cls, v):
        return _check_image_url(v) if v else v

    @field_validator("image_urls")
    @classmethod
    def _v_image_urls(cls, v):
        if v is None:
            return v
        return [_check_image_url(u) for u in v]


class AuctionUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=10000)
    category_id: Optional[int] = None
    starting_price: Optional[float] = Field(default=None, gt=0)
    bin_price: Optional[float] = Field(default=None, gt=0)
    auction_type: Optional[Literal["bid", "bin"]] = None
    extend_minutes: Optional[int] = Field(default=None, ge=1, le=10080)
    image_urls: Optional[list[str]] = Field(default=None, max_length=10)

    @field_validator("image_urls")
    @classmethod
    def _v_image_urls(cls, v):
        if v is None:
            return v
        return [_check_image_url(u) for u in v]


class AuctionResponse(BaseModel):
    model_config = {"from_attributes": True}
    id: int
    title: str
    description: str
    starting_price: float
    current_price: float
    image_url: Optional[str]
    image_urls: Optional[list[str]] = None
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
    items: list[AuctionResponse]
    total: int
    page: int
    page_size: int
    total_pages: int
