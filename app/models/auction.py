from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.database import Base


class Auction(Base):
    __tablename__ = "auctions"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, index=True)
    description = Column(String)
    starting_price = Column(Float)
    current_price = Column(Float)
    image_url = Column(String, nullable=True)
    start_time = Column(DateTime)
    end_time = Column(DateTime)
    is_active = Column(Boolean, default=True)
    is_completed = Column(Boolean, default=False)
    winner_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"))
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=True)
    ending_soon_notified = Column(Boolean, default=False)
    auction_type = Column(String, default="bid")
    bin_price = Column(Float, nullable=True)
    bids = relationship("Bid", back_populates="auction")
    category = relationship("Category", back_populates="auctions")
    images = relationship(
        "AuctionImage",
        back_populates="auction",
        order_by="AuctionImage.order",
        cascade="all, delete-orphan",
    )


class AuctionImage(Base):
    __tablename__ = "auction_images"
    id = Column(Integer, primary_key=True, index=True)
    auction_id = Column(Integer, ForeignKey("auctions.id", ondelete="CASCADE"))
    url = Column(String)
    order = Column(Integer, default=0)
    auction = relationship("Auction", back_populates="images")
