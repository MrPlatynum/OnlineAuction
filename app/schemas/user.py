from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class UserLogin(BaseModel):
    username: str
    password: str


class UserResponse(BaseModel):
    model_config = {"from_attributes": True}
    id: int
    username: str
    email: str
    balance: float
    created_at: Optional[datetime] = None
    avatar_url: Optional[str] = None
    email_notifications: bool = True
    notify_outbid: bool = True
    notify_winning: bool = True
    notify_ending: bool = True
    notify_sold: bool = True
    notify_bid_received: bool = True
    notify_lost: bool = True


class NotificationSettings(BaseModel):
    email_notifications: bool
    notify_outbid: bool
    notify_winning: bool
    notify_ending: bool
    notify_sold: bool
    notify_bid_received: bool = True
    notify_lost: bool = True


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)
