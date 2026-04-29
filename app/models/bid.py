from datetime import datetime

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer
from sqlalchemy.orm import relationship

from app.database import Base


class Bid(Base):
    __tablename__ = "bids"
    id = Column(Integer, primary_key=True, index=True)
    amount = Column(Float)
    timestamp = Column(DateTime, default=datetime.utcnow)
    user_id = Column(Integer, ForeignKey("users.id"))
    auction_id = Column(Integer, ForeignKey("auctions.id"))
    user = relationship("User", back_populates="bids")
    auction = relationship("Auction", back_populates="bids")
