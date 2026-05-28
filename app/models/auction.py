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
    # Length matches AuctionCreate.title Pydantic max_length=300; the
    # schema-level cap is defence-in-depth against server-generated
    # code (e.g. snapshotting auction_title into notifications) that
    # bypasses the input validator.
    title = Column(String(300), index=True, nullable=False)
    description = Column(Text, nullable=False)
    starting_price = Column(Numeric(12, 2), nullable=False)
    current_price = Column(Numeric(12, 2), nullable=False)
    image_url = Column(String(2000), nullable=True)
    start_time = Column(DateTime(timezone=True), nullable=False)
    end_time = Column(DateTime(timezone=True), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    is_completed = Column(Boolean, default=False, nullable=False)
    winner_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=True, index=True)
    ending_soon_notified = Column(Boolean, default=False, nullable=False)
    auction_type = Column(String(10), default="bid", nullable=False)
    bin_price = Column(Numeric(12, 2), nullable=True)
    # Counts late-bid anti-sniping extensions on this lot. Capped at
    # MAX_EXTENSIONS in the /bids handler so two coordinated bidders
    # can't ping-pong late bids and keep the lot open indefinitely
    # (each extension is ANTISNIPING_EXTEND long, so the cap also
    # bounds the maximum additional lifetime to MAX_EXTENSIONS ×
    # ANTISNIPING_EXTEND seconds).
    extensions_count = Column(Integer, default=0, nullable=False)

    bids = relationship("Bid", back_populates="auction")
    category = relationship("Category", back_populates="auctions")
    # Two FKs land on users (created_by + winner_id), so the foreign_keys
    # kwarg is required to disambiguate which column this relationship
    # follows. Only used by the listing endpoints' selectinload - the
    # raw FK column ``created_by`` stays the canonical write path.
    creator = relationship("User", foreign_keys=[created_by])
    images = relationship(
        "AuctionImage",
        back_populates="auction",
        order_by="AuctionImage.order",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        # schedule_active_auctions walks active rows on startup; the
        # listing API also filters/orders by these columns.
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
    url = Column(String(2000), nullable=False)
    order = Column(Integer, default=0, nullable=False)
    auction = relationship("Auction", back_populates="images")
