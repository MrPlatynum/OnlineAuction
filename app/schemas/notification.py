from datetime import datetime

from pydantic import BaseModel


class NotificationResponse(BaseModel):
    model_config = {"from_attributes": True}
    id: int
    type: str
    title: str
    message: str
    auction_id: int | None
    auction_title: str | None
    is_read: bool
    created_at: datetime


class PaginatedNotificationsResponse(BaseModel):
    """Listing envelope so the client can page past the first batch.
    Without ``total`` and ``offset`` the feed silently truncates at
    ``limit`` and the UI has no way to fetch older notifications."""
    items: list[NotificationResponse]
    total: int
    limit: int
    offset: int
