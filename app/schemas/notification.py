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
