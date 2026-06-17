"""Shared DB helpers. Centralises the commit-or-409 recipe so the
three router sites that converted IntegrityError to a 400 ("user
exists", "already subscribed", "review already written") stop hand-
rolling the same rollback + HTTPException dance - and so any future
unique-constraint endpoint picks up the pattern by import instead of
copy-paste."""

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User


async def ensure_seller_exists(db: AsyncSession, seller_id: int) -> None:
    """Raise ``HTTPException(404, "Продавец не найден")`` when no user
    with ``seller_id`` exists. The reviews and subscriptions routers
    both gate seller-scoped endpoints on this same existence probe -
    a shared helper keeps the query and the 404 wording in one place
    instead of three hand-rolled copies that could drift apart.
    """
    exists = await db.scalar(
        select(func.count()).select_from(User).where(User.id == seller_id)
    )
    if not exists:
        raise HTTPException(status_code=404, detail="Продавец не найден")


async def commit_or_409(db: AsyncSession, *, detail: str) -> None:
    """Await ``db.commit()``; on ``IntegrityError`` roll the session
    back and raise ``HTTPException(400, detail)`` with the cause
    suppressed. Use at every endpoint where the pre-check + INSERT
    race against a unique constraint - two concurrent requests that
    both pass the pre-check (no row yet) and race the INSERT cleanly
    surface the same user-facing 400 as the pre-check would have.
    """
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=400, detail=detail) from None
