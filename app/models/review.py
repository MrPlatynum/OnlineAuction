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
    # ``index=True`` so "all reviews I wrote" lookups don't seq-scan -
    # ``seller_id`` was already indexed for the symmetric query, but the
    # reviewer side was missing its index.
    reviewer_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    # ``nullable=False``: Pydantic already requires ``auction_id`` at the
    # API boundary, but Postgres treats NULL as distinct in UNIQUE
    # indexes - so without the column-level NOT NULL the
    # ``uq_reviews_one_per_auction`` constraint could be bypassed by an
    # admin tool / data import writing NULL-rows. NOT NULL closes the
    # bypass at the schema layer.
    auction_id = Column(Integer, ForeignKey("auctions.id"), nullable=False)
    rating = Column(Integer, nullable=False)
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    seller = relationship("User", foreign_keys=[seller_id])
    reviewer = relationship("User", foreign_keys=[reviewer_id])

    __table_args__ = (
        CheckConstraint("rating BETWEEN 1 AND 5", name="ck_reviews_rating_range"),
        UniqueConstraint("reviewer_id", "auction_id", name="uq_reviews_one_per_auction"),
    )
