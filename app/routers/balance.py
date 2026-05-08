from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Transaction, User
from app.schemas import DepositRequest, WithdrawRequest
from app.services.balance import lock_users_by_id
from app.services.transactions import add_transaction
from app.utils.money import money_to_float, to_decimal
from app.utils.security import get_current_user

router = APIRouter(prefix="/api", tags=["balance"])


@router.post("/deposit")
async def deposit(
    data: DepositRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    amount = to_decimal(data.amount)
    # Row-lock the user before reading balance so concurrent /deposit and
    # /withdraw on the same account serialise instead of racing on stale
    # in-memory copies and clobbering each other's update.
    await lock_users_by_id(db, current_user.id)
    current_user.balance = round(current_user.balance + amount, 2)
    add_transaction(db, current_user, "deposit", amount, "Пополнение баланса")
    await db.commit()
    return {
        "balance": money_to_float(current_user.balance),
        "amount": float(data.amount),
    }


@router.post("/withdraw")
async def withdraw(
    data: WithdrawRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    amount = to_decimal(data.amount)
    await lock_users_by_id(db, current_user.id)
    if current_user.balance < amount:
        raise HTTPException(400, detail=f"Недостаточно средств. Доступно: ${current_user.balance:.2f}")
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
