"""Single helper that pins every balance mutation to an audit row.
Every ₽-move (deposit, withdrawal, bid_win, auction_sale, bin_purchase,
commission) goes through this function so the ``transactions`` table
always carries a row with ``balance_after`` matching the user object —
the foundation of the ledger view at ``GET /api/transactions``.
"""

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Transaction, User


def add_transaction(
    db: AsyncSession,
    user: User,
    tx_type: str,
    amount: Decimal,
    description: str,
    auction_id: int | None = None,
) -> None:
    """Append a balance-mutation audit row. ``amount`` is the absolute
    delta as a positive ``Decimal`` (the sign is implicit in ``tx_type``);
    every caller in services and routers already builds the value as
    ``Decimal`` via ``utils.money.to_decimal``."""
    tx = Transaction(
        user_id=user.id,
        type=tx_type,
        amount=amount,
        balance_after=user.balance,
        description=description,
        auction_id=auction_id,
    )
    db.add(tx)
