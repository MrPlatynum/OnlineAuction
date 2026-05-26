from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


def _check_image_url(value: str) -> str:
    """Reject anything that's not an http(s) absolute URL or a same-site
    /-relative path. Without this, ``javascript:``, ``data:``, ``vbscript:``
    URLs flow into the DB and end up rendered as ``<img src="...">`` -
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
    title: str = Field(min_length=1, max_length=300)
    description: str = Field(min_length=1, max_length=20000)
    # Money fields are stored as Numeric(12, 2). Cap at MAX_USER_BALANCE
    # so an out-of-range starting / bin price 400s through Pydantic
    # instead of overflowing the DB column at commit and surfacing as
    # an opaque 500.
    starting_price: float = Field(gt=0, le=10_000_000)
    duration_minutes: int = Field(gt=0, le=10080)
    image_url: str | None = Field(default=None, max_length=2000)
    image_urls: list[str] | None = Field(default=None, max_length=10)
    category_id: int | None = None
    auction_type: Literal["bid", "bin"] = "bid"
    bin_price: float | None = Field(default=None, gt=0, le=10_000_000)

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
    title: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=20000)
    category_id: int | None = None
    starting_price: float | None = Field(default=None, gt=0, le=10_000_000)
    bin_price: float | None = Field(default=None, gt=0, le=10_000_000)
    auction_type: Literal["bid", "bin"] | None = None
    extend_minutes: int | None = Field(default=None, ge=1, le=10080)
    image_urls: list[str] | None = Field(default=None, max_length=10)

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
    image_url: str | None
    image_urls: list[str] | None = None
    start_time: datetime
    end_time: datetime
    is_active: bool
    is_completed: bool = False
    winner_id: int | None
    created_by: int | None = None
    creator_username: str | None = None
    creator_avatar_url: str | None = None
    bids_count: int | None = None
    time_remaining: int | None = None
    category_id: int | None = None
    category_name: str | None = None
    category_icon: str | None = None
    auction_type: str | None = "bid"
    bin_price: float | None = None


class PaginatedAuctionsResponse(BaseModel):
    items: list[AuctionResponse]
    total: int
    page: int
    page_size: int
    total_pages: int
