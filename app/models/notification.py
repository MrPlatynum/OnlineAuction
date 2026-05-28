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
    type = Column(String(50), index=True, nullable=False)
    title = Column(String(500), nullable=False)
    message = Column(Text, nullable=False)
    auction_id = Column(
        Integer, ForeignKey("auctions.id", ondelete="SET NULL"), nullable=True
    )
    auction_title = Column(String(500), nullable=True)
    is_read = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    user = relationship("User", back_populates="notifications")

    __table_args__ = (
        # /api/notifications/unread-count
        Index("ix_notifications_user_unread", "user_id", "is_read"),
        # listing endpoint orders by created_at desc
        Index("ix_notifications_user_created", "user_id", "created_at"),
        # ENDING_SOON per-recipient idempotency dedupe scan in
        # services/auctions.py filters by (auction_id, type); the two
        # composites above index user_id-led tuples and don't cover
        # that scan, which grew linearly with the notifications table.
        Index("ix_notifications_auction_type", "auction_id", "type"),
    )
