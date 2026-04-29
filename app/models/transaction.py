from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.database import Base
from app.utils.time import utcnow


class Transaction(Base):
    __tablename__ = "transactions"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    type = Column(String)  # deposit | withdrawal | bid_win | auction_sale | bin_purchase
    amount = Column(Float)
    balance_after = Column(Float)
    description = Column(String, nullable=True)
    auction_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    user = relationship("User", foreign_keys=[user_id])
