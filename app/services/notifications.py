import asyncio
from typing import Optional

from sqlalchemy.orm import Session

from app.models import Notification, NotificationType, User
from app.services.email import build_notification_email_html, send_email_notification

# Strong references to in-flight email tasks so they don't get GC'd
# mid-execution. Python only keeps weak refs to bare ``asyncio.create_task``
# results.
_pending_email_tasks: set[asyncio.Task] = set()


def _fire_and_forget_email(to_email: str, subject: str, html: str) -> None:
    """Schedule an email send on the running event loop without
    awaiting it, so the caller (e.g. an HTTP handler) can return
    immediately."""
    task = asyncio.create_task(send_email_notification(to_email, subject, html))
    _pending_email_tasks.add(task)
    task.add_done_callback(_pending_email_tasks.discard)


def create_notification(
    db: Session,
    user_id: int,
    notification_type: NotificationType,
    title: str,
    message: str,
    auction_id: Optional[int] = None,
    auction_title: Optional[str] = None,
):
    """Создание уведомления в БД."""
    notification = Notification(
        user_id=user_id,
        type=notification_type.value,
        title=title,
        message=message,
        auction_id=auction_id,
        auction_title=auction_title,
    )
    db.add(notification)
    db.commit()
    db.refresh(notification)
    return notification


async def notify_user(
    db: Session,
    user: User,
    notification_type: NotificationType,
    title: str,
    message: str,
    auction_id: Optional[int] = None,
    auction_title: Optional[str] = None,
    manager=None,
):
    """In-app + email уведомление пользователя."""

    notification = create_notification(
        db, user.id, notification_type, title, message, auction_id, auction_title
    )

    if manager:
        await manager.send_notification(user.id, {
            "type": "notification",
            "notification": {
                "id": notification.id,
                "type": notification_type.value,
                "title": title,
                "message": message,
                "auction_id": auction_id,
                "auction_title": auction_title,
                "created_at": notification.created_at.isoformat(),
            },
        })

    if user.email_notifications:
        should_send_email = False

        if notification_type == NotificationType.BID_OUTBID and user.notify_outbid:
            should_send_email = True
        elif notification_type == NotificationType.AUCTION_WON and user.notify_winning:
            should_send_email = True
        elif notification_type == NotificationType.AUCTION_ENDING and user.notify_ending:
            should_send_email = True
        elif notification_type == NotificationType.AUCTION_SOLD and user.notify_sold:
            should_send_email = True
        elif notification_type == NotificationType.BID_PLACED and user.notify_sold:
            should_send_email = True

        if should_send_email:
            html_content = build_notification_email_html(
                notification_type.value, title, message, auction_id, auction_title
            )
            _fire_and_forget_email(user.email, title, html_content)
