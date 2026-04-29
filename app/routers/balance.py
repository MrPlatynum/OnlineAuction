from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Transaction, User
from app.schemas import DepositRequest, WithdrawRequest
from app.services.transactions import add_transaction
from app.utils.security import get_current_user

router = APIRouter(prefix="/api", tags=["balance"])


@router.post("/deposit")
def deposit(
    data: DepositRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    current_user.balance = round(current_user.balance + data.amount, 2)
    add_transaction(db, current_user, "deposit", data.amount, "Пополнение баланса")
    db.commit()
    return {"balance": current_user.balance, "amount": data.amount}


@router.post("/withdraw")
def withdraw(
    data: WithdrawRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.balance < data.amount:
        raise HTTPException(400, detail=f"Недостаточно средств. Доступно: ${current_user.balance:.2f}")
    current_user.balance = round(current_user.balance - data.amount, 2)
    add_transaction(db, current_user, "withdrawal", data.amount, "Вывод средств")
    db.commit()
    return {"balance": current_user.balance, "amount": data.amount}


@router.get("/transactions")
def get_transactions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = (
        db.query(Transaction)
        .filter(Transaction.user_id == current_user.id)
        .order_by(Transaction.created_at.desc())
    )
    total = q.count()
    items = q.offset((page - 1) * page_size).limit(page_size).all()
    return {
        "balance": current_user.balance,
        "total": total,
        "page": page,
        "total_pages": max(1, (total + page_size - 1) // page_size),
        "items": [
            {
                "id": t.id,
                "type": t.type,
                "amount": t.amount,
                "balance_after": t.balance_after,
                "description": t.description,
                "auction_id": t.auction_id,
                "created_at": t.created_at.isoformat(),
            }
            for t in items
        ],
    }
