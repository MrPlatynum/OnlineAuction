from sqlalchemy import Boolean, Column, DateTime, Integer, Numeric, String
from sqlalchemy.orm import relationship

from app.database import Base
from app.utils.time import utcnow


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    # Bumped by /change-password (and any future invalidation event) so
    # tokens issued before the bump fail at /me / get_current_user. JWT
    # carries the value as a ``tv`` claim; mismatch → 401.
    token_version = Column(Integer, default=0, nullable=False)
    balance = Column(Numeric(12, 2), default=1000.0, nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)

    avatar_url = Column(String, nullable=True)

    email_notifications = Column(Boolean, default=True, nullable=False)
    notify_outbid = Column(Boolean, default=True, nullable=False)
    notify_winning = Column(Boolean, default=True, nullable=False)
    notify_ending = Column(Boolean, default=True, nullable=False)
    notify_sold = Column(Boolean, default=True, nullable=False)
    notify_bid_received = Column(Boolean, default=True, nullable=False)
    notify_lost = Column(Boolean, default=True, nullable=False)

    bids = relationship("Bid", back_populates="user")
    notifications = relationship("Notification", back_populates="user", cascade="all, delete-orphan")
