"""In-app notification feed.

Lists the user's notifications, exposes an unread counter for the nav
bell badge, and toggles read/unread state. Delivery (in-app + WS +
email) happens in ``services.notifications.notify_user`` - this router
only owns the recipient-side read API.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.database import get_db
from app.models import Notification, User
from app.schemas import NotificationResponse, PaginatedNotificationsResponse
from app.utils.rate_limit import limiter
from app.utils.security import get_current_user

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("", response_model=PaginatedNotificationsResponse)
async def get_notifications(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    unread_only: bool = Query(False),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Envelope + offset so older notifications past the first page are
    # actually reachable - the prior shape returned a bare list capped
    # at `limit` with no way to fetch anything older. The `Notification.id`
    # tiebreaker keeps pagination stable when multiple rows share a
    # `created_at` (batched fan-out on auction settle stamps the same
    # timestamp across all recipients' notifications).
    base = select(Notification).where(Notification.user_id == current_user.id)
    if unread_only:
        base = base.where(Notification.is_read.is_(False))

    total = await db.scalar(
        select(func.count()).select_from(base.subquery())
    )

    items = (
        await db.execute(
            base
            .order_by(Notification.created_at.desc(), Notification.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).scalars().all()

    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/unread-count")
async def get_unread_count(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    count = await db.scalar(
        select(func.count())
        .select_from(Notification)
        .where(Notification.user_id == current_user.id, Notification.is_read.is_(False))
    )
    return {"count": count}


@router.post("/{notification_id}/read")
@limiter.limit("120/minute")
async def mark_notification_read(
    request: Request,
    notification_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    notification = (
        await db.execute(
            select(Notification).where(
                Notification.id == notification_id,
                Notification.user_id == current_user.id,
            )
        )
    ).scalar_one_or_none()

    if not notification:
        raise HTTPException(status_code=404, detail="Уведомление не найдено")

    notification.is_read = True
    await db.commit()
    return {"message": "Уведомление помечено как прочитанное"}


@router.post("/mark-all-read")
@limiter.limit("30/minute")
async def mark_all_read(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await db.execute(
        update(Notification)
        .where(
            Notification.user_id == current_user.id,
            Notification.is_read.is_(False),
        )
        .values(is_read=True)
    )
    await db.commit()
    return {"message": "Все уведомления отмечены как прочитанные"}


@router.delete("/{notification_id}")
@limiter.limit("120/minute")
async def delete_notification(
    request: Request,
    notification_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    notification = (
        await db.execute(
            select(Notification).where(
                Notification.id == notification_id,
                Notification.user_id == current_user.id,
            )
        )
    ).scalar_one_or_none()

    if not notification:
        raise HTTPException(status_code=404, detail="Уведомление не найдено")

    await db.delete(notification)
    await db.commit()
    return {"message": "Уведомление удалено"}
