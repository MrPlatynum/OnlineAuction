from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Transaction, User


def add_transaction(
    db: AsyncSession,
    user: User,
    tx_type: str,
    amount: float,
    description: str,
    auction_id: int = None,
):
    """Записывает транзакцию. amount — всегда положительное число."""
    tx = Transaction(
        user_id=user.id,
        type=tx_type,
        amount=amount,
        balance_after=user.balance,
        description=description,
        auction_id=auction_id,
    )
    db.add(tx)
