from sqlalchemy import Column, DateTime, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import relationship

from app.database import Base
from app.utils.time import utcnow


class Subscription(Base):
    __tablename__ = "subscriptions"
    id = Column(Integer, primary_key=True, index=True)
    subscriber_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    seller_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    subscriber = relationship("User", foreign_keys=[subscriber_id])
    seller = relationship("User", foreign_keys=[seller_id])

    __table_args__ = (
        UniqueConstraint("subscriber_id", "seller_id", name="uq_subscription_pair"),
    )
