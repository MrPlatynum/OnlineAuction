from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr


class UserCreate(BaseModel):
    username: str
    email: EmailStr
    password: str


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


class NotificationSettings(BaseModel):
    email_notifications: bool
    notify_outbid: bool
    notify_winning: bool
    notify_ending: bool
    notify_sold: bool


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str
