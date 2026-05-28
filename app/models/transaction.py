from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
)
from sqlalchemy.orm import relationship

from app.database import Base
from app.utils.time import utcnow


class Transaction(Base):
    __tablename__ = "transactions"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    type = Column(String(50), nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)
    balance_after = Column(Numeric(12, 2), nullable=False)
    description = Column(String(500), nullable=True)
    auction_id = Column(
        Integer, ForeignKey("auctions.id", ondelete="SET NULL"), nullable=True
    )
    created_at = Column(DateTime, default=utcnow, nullable=False)
    user = relationship("User", foreign_keys=[user_id])

    __table_args__ = (
        # transaction history listing
        Index("ix_transactions_user_created", "user_id", "created_at"),
        CheckConstraint("amount > 0", name="ck_transactions_amount_positive"),
        CheckConstraint(
            "type IN ('deposit', 'withdrawal', 'bid_win', 'auction_sale', "
            "'bin_purchase', 'commission')",
            name="ck_transactions_type_valid",
        ),
    )
