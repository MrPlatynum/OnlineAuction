from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String
from sqlalchemy.orm import relationship

from app.database import Base
from app.utils.time import utcnow


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    email = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    balance = Column(Float, default=1000.0)
    created_at = Column(DateTime, default=utcnow)

    avatar_url = Column(String, nullable=True)

    email_notifications = Column(Boolean, default=True)
    notify_outbid = Column(Boolean, default=True)
    notify_winning = Column(Boolean, default=True)
    notify_ending = Column(Boolean, default=True)
    notify_sold = Column(Boolean, default=True)

    bids = relationship("Bid", back_populates="user")
    notifications = relationship("Notification", back_populates="user", cascade="all, delete-orphan")
