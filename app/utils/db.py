"""Shared DB helpers. Centralises the commit-or-409 recipe so the
three router sites that converted IntegrityError to a 400 ("user
exists", "already subscribed", "review already written") stop hand-
rolling the same rollback + HTTPException dance - and so any future
unique-constraint endpoint picks up the pattern by import instead of
copy-paste."""

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


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
