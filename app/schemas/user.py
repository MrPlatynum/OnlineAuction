from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

# Username charset: Latin + Cyrillic letters, digits, underscore,
# hyphen. Defence-in-depth against stored-XSS: the username flows
# into Notification.message ("@<user> выставил новый лот: …") and
# auction listings; the frontend escapes through esc() everywhere
# today, but constraining the source means a future render-path
# regression that calls innerHTML directly on a username can't be
# exploited. Auction titles intentionally remain unrestricted -
# sellers need quotes / punctuation - so titles stay covered by
# the render-side escape discipline.
_USERNAME_PATTERN = r"^[A-Za-zА-Яа-яЁё0-9_-]+$"


def _normalize_username(value: str) -> str:
    """Lower-case the username at every input boundary so 'Alice' and
    'alice' collapse to the same row and the SQL UNIQUE constraint
    actually enforces "one account per name". Without this the
    column comparison ``User.username == ...`` is case-sensitive and
    both rows could legally coexist, making @-mentions ambiguous and
    profile lookups silently fail on case-mismatched URLs."""
    return value.lower() if isinstance(value, str) else value


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=32, pattern=_USERNAME_PATTERN)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)

    @field_validator("username", mode="after")
    @classmethod
    def _lower_username(cls, v: str) -> str:
        return _normalize_username(v)


class UserLogin(BaseModel):
    username: str
    # Match UserCreate / ChangePasswordRequest. Without an explicit cap a
    # multi-MB JSON body would parse before verify_password's internal
    # limit kicked in; 128 chars is well above NIST's recommended minimum
    # and what most major sites accept (AWS, Stripe, etc.).
    password: str = Field(max_length=128)

    @field_validator("username", mode="after")
    @classmethod
    def _lower_username(cls, v: str) -> str:
        return _normalize_username(v)


class UserResponse(BaseModel):
    model_config = {"from_attributes": True}
    id: int
    username: str
    email: str
    balance: float
    created_at: datetime | None = None
    avatar_url: str | None = None
    email_verified: bool = False
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


class VerifyEmailRequest(BaseModel):
    token: str


class PasswordResetRequestBody(BaseModel):
    email: EmailStr


class PasswordResetConfirmBody(BaseModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)
