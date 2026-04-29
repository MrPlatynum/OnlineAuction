from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from app.database import Base


class Auction(Base):
    __tablename__ = "auctions"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, index=True, nullable=False)
    description = Column(Text, nullable=False)
    starting_price = Column(Numeric(12, 2), nullable=False)
    current_price = Column(Numeric(12, 2), nullable=False)
    image_url = Column(String, nullable=True)
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    is_completed = Column(Boolean, default=False, nullable=False)
    winner_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=True, index=True)
    ending_soon_notified = Column(Boolean, default=False, nullable=False)
    auction_type = Column(String, default="bid", nullable=False)
    bin_price = Column(Numeric(12, 2), nullable=True)

    bids = relationship("Bid", back_populates="auction")
    category = relationship("Category", back_populates="auctions")
    images = relationship(
        "AuctionImage",
        back_populates="auction",
        order_by="AuctionImage.order",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        # check_expired_auctions polls active auctions ordered by end_time.
        Index("ix_auctions_active_end_time", "is_active", "end_time"),
        CheckConstraint("starting_price > 0", name="ck_auctions_starting_price_positive"),
        CheckConstraint(
            "auction_type IN ('bid', 'bin')",
            name="ck_auctions_type_valid",
        ),
        CheckConstraint(
            "auction_type != 'bin' OR bin_price IS NOT NULL",
            name="ck_auctions_bin_requires_price",
        ),
    )


class AuctionImage(Base):
    __tablename__ = "auction_images"
    id = Column(Integer, primary_key=True, index=True)
    auction_id = Column(
        Integer, ForeignKey("auctions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    url = Column(String, nullable=False)
    order = Column(Integer, default=0, nullable=False)
    auction = relationship("Auction", back_populates="images")
