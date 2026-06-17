from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
)
from sqlalchemy.orm import relationship

from app.database import Base
from app.utils.time import utcnow


class Bid(Base):
    __tablename__ = "bids"
    id = Column(Integer, primary_key=True, index=True)
    amount = Column(Numeric(12, 2), nullable=False)
    timestamp = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    auction_id = Column(Integer, ForeignKey("auctions.id"), nullable=False)
    user = relationship("User", back_populates="bids")
    auction = relationship("Auction", back_populates="bids")

    __table_args__ = (
        # Used everywhere we look up "latest bid on auction X".
        Index("ix_bids_auction_timestamp", "auction_id", "timestamp"),
        CheckConstraint("amount > 0", name="ck_bids_amount_positive"),
    )
