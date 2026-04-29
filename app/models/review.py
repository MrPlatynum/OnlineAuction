from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.database import Base
from app.utils.time import utcnow


class Review(Base):
    __tablename__ = "reviews"
    id = Column(Integer, primary_key=True, index=True)
    seller_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    reviewer_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    auction_id = Column(Integer, ForeignKey("auctions.id"), nullable=True)
    rating = Column(Integer, nullable=False)
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    seller = relationship("User", foreign_keys=[seller_id])
    reviewer = relationship("User", foreign_keys=[reviewer_id])

    __table_args__ = (
        CheckConstraint("rating BETWEEN 1 AND 5", name="ck_reviews_rating_range"),
        # one review per (reviewer, auction) — only enforced when auction_id present
        UniqueConstraint("reviewer_id", "auction_id", name="uq_reviews_one_per_auction"),
    )
