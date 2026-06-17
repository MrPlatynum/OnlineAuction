"""Atomic balance-mutation + audit-row helper.

Every ₽-move (deposit, withdrawal, bid_win, auction_sale, bin_purchase,
commission) goes through ``apply_balance_delta``: the helper mutates
``user.balance`` and writes the matching ``Transaction`` audit row in
one call, so the "balance_after matches the running balance" invariant
that powers ``GET /api/transactions`` is structural instead of an
implicit convention every caller has to remember.
"""

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Transaction, User
from app.utils.money import quantize_money


def apply_balance_delta(
    db: AsyncSession,
    user: User,
    delta: Decimal,
    tx_type: str,
    description: str,
    auction_id: int | None = None,
) -> None:
    """Apply ``delta`` to ``user.balance`` (signed: positive credit,
    negative debit) and append the matching ``Transaction`` audit row
    with ``balance_after`` reflecting the post-mutation value. The
    audit row's ``amount`` is the absolute delta - the sign is implicit
    in ``tx_type`` per the existing ledger contract.

    Replaces the older ``user.balance += X; add_transaction(...)``
    pattern: the new shape makes it impossible to forget the
    mutation-then-audit ordering or to mutate by a different amount
    than the audit row records."""
    user.balance = quantize_money(user.balance + delta)
    tx = Transaction(
        user_id=user.id,
        type=tx_type,
        amount=abs(delta),
        balance_after=user.balance,
        description=description,
        auction_id=auction_id,
    )
    db.add(tx)


