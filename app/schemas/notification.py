from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class NotificationResponse(BaseModel):
    model_config = {"from_attributes": True}
    id: int
    type: str
    title: str
    message: str
    auction_id: Optional[int]
    auction_title: Optional[str]
    is_read: bool
    created_at: datetime
