from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from app.database import Base
from app.utils.time import utcnow


class Notification(Base):
    __tablename__ = "notifications"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    type = Column(String, index=True, nullable=False)
    title = Column(String, nullable=False)
    message = Column(Text, nullable=False)
    auction_id = Column(
        Integer, ForeignKey("auctions.id", ondelete="SET NULL"), nullable=True
    )
    auction_title = Column(String, nullable=True)
    is_read = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)

    user = relationship("User", back_populates="notifications")

    __table_args__ = (
        # /api/notifications/unread-count
        Index("ix_notifications_user_unread", "user_id", "is_read"),
        # listing endpoint orders by created_at desc
        Index("ix_notifications_user_created", "user_id", "created_at"),
    )
