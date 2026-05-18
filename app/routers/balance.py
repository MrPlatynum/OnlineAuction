"""Money-only operations on the user balance: deposit, withdraw, and
the paginated transaction ledger. Every mutating endpoint funnels
through ``services.transactions.add_transaction`` so every ₽-move has
a matching audit row with ``balance_after``.
"""

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Transaction, User
from app.schemas import DepositRequest, WithdrawRequest
from app.services.balance import get_committed_balance, lock_users_by_id
from app.services.transactions import add_transaction
from app.utils.money import money_to_float, to_decimal
from app.utils.rate_limit import limiter
from app.utils.security import get_current_user, require_verified_user

router = APIRouter(prefix="/api", tags=["balance"])

# Numeric(12, 2) accepts up to 9_999_999_999.99 before Postgres raises
# ``numeric field overflow``. Cap user-visible balance well below that
# so we can never hit the column ceiling: a determined attacker firing
# the maximum per-call deposit at the rate-limit ceiling would still
# saturate against this number, not blow up with a 500.
MAX_USER_BALANCE = Decimal("10000000.00")


@router.post("/deposit")
@limiter.limit("30/minute")
async def deposit(
    request: Request,
    data: DepositRequest,
    current_user: User = Depends(require_verified_user),
    db: AsyncSession = Depends(get_db),
):
    amount = to_decimal(data.amount)
    # Row-lock the user before reading balance so concurrent /deposit and
    # /withdraw on the same account serialise instead of racing on stale
    # in-memory copies and clobbering each other's update.
    await lock_users_by_id(db, current_user.id)
    new_balance = round(current_user.balance + amount, 2)
    if new_balance > MAX_USER_BALANCE:
        raise HTTPException(
            status_code=400,
            detail=f"Максимальный баланс — {MAX_USER_BALANCE:.2f} ₽",
        )
    current_user.balance = new_balance
    add_transaction(db, current_user, "deposit", amount, "Пополнение баланса")
    await db.commit()
    return {
        "balance": money_to_float(current_user.balance),
        "amount": float(data.amount),
    }


@router.post("/withdraw")
@limiter.limit("30/minute")
async def withdraw(
    request: Request,
    data: WithdrawRequest,
    current_user: User = Depends(require_verified_user),
    db: AsyncSession = Depends(get_db),
):
    amount = to_decimal(data.amount)
    await lock_users_by_id(db, current_user.id)
    # Subtract what's locked up as the current leader of active auctions —
    # otherwise a user could withdraw their balance while top-bidding on
    # lots, leaving us unable to debit them at completion time.
    committed = await get_committed_balance(db, current_user.id)
    available = current_user.balance - committed
    if available < amount:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Недостаточно средств. Доступно: {available:.2f} ₽ "
                f"({committed:.2f} ₽ удерживается на активных аукционах)."
            ),
        )
    current_user.balance = round(current_user.balance - amount, 2)
    add_transaction(db, current_user, "withdrawal", amount, "Вывод средств")
    await db.commit()
    return {
        "balance": money_to_float(current_user.balance),
        "amount": float(data.amount),
    }


@router.get("/transactions")
async def get_transactions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    base_query = (
        select(Transaction)
        .where(Transaction.user_id == current_user.id)
        .order_by(Transaction.created_at.desc())
    )
    total = await db.scalar(
        select(func.count())
        .select_from(Transaction)
        .where(Transaction.user_id == current_user.id)
    )
    items = (
        await db.execute(base_query.offset((page - 1) * page_size).limit(page_size))
    ).scalars().all()
    return {
        "balance": money_to_float(current_user.balance),
        "total": total,
        "page": page,
        "total_pages": max(1, (total + page_size - 1) // page_size),
        "items": [
            {
                "id": t.id,
                "type": t.type,
                "amount": money_to_float(t.amount),
                "balance_after": money_to_float(t.balance_after),
                "description": t.description,
                "auction_id": t.auction_id,
                "created_at": t.created_at.isoformat(),
            }
            for t in items
        ],
    }
