import asyncio
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import PUBLIC_BASE_URL
from app.models import Notification, NotificationType, User
from app.services.email import (
    build_notification_email_html,
    build_password_changed_email_html,
    build_password_reset_email_html,
    build_verification_email_html,
    send_email_notification,
)
from app.utils.security import create_email_verify_token, create_password_reset_token

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


async def flush_pending_emails(timeout: float = 5.0) -> None:
    """Drain in-flight SMTP roundtrips on shutdown. Called from the
    FastAPI lifespan ``finally`` so a SIGTERM doesn't drop emails that
    were already on the wire."""
    if not _pending_email_tasks:
        return
    pending = list(_pending_email_tasks)
    try:
        await asyncio.wait_for(
            asyncio.gather(*pending, return_exceptions=True),
            timeout=timeout,
        )
    except TimeoutError:
        import logging
        logging.getLogger(__name__).warning(
            "Pending email tasks did not finish within %.1fs (%d still in flight)",
            timeout, len(_pending_email_tasks),
        )


def send_verification_email(user: User) -> None:
    """Fire-and-forget the post-register verification email. Same
    pattern as notification emails: scheduled on the loop, strong-ref'd
    so the GC doesn't kill it mid-send, drained on shutdown via
    flush_pending_emails. Caller is expected to have committed the
    User row so its id and current email are stable."""
    token = create_email_verify_token(user)
    link = f"{PUBLIC_BASE_URL}/verify-email.html?token={token}"
    html_content = build_verification_email_html(user.username, link)
    _fire_and_forget_email(
        user.email,
        "Подтвердите email — Лотус",
        html_content,
    )


def send_password_reset_email(user: User) -> None:
    """Fire-and-forget the password-reset link. The token's ``tv``
    claim is read from the user's current ``token_version`` — a later
    successful /password-reset/confirm bumps tv so this link (and any
    other in-flight reset link for the same account) auto-invalidate."""
    token = create_password_reset_token(user)
    link = f"{PUBLIC_BASE_URL}/password-reset.html?token={token}"
    html_content = build_password_reset_email_html(user.username, link)
    _fire_and_forget_email(
        user.email,
        "Сброс пароля — Лотус",
        html_content,
    )


def send_password_changed_email(user: User) -> None:
    """Notification email sent right after /password-reset/confirm
    succeeds. The legitimate user sees the trail even if the reset
    was triggered by someone who'd taken over their inbox — they
    can react before the attacker has time to dig in."""
    html_content = build_password_changed_email_html(user.username)
    _fire_and_forget_email(
        user.email,
        "Пароль изменён — Лотус",
        html_content,
    )


async def create_notification(
    db: AsyncSession,
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
    await db.commit()
    await db.refresh(notification)
    return notification


async def notify_user(
    db: AsyncSession,
    user: User,
    notification_type: NotificationType,
    title: str,
    message: str,
    auction_id: Optional[int] = None,
    auction_title: Optional[str] = None,
    manager=None,
):
    """In-app + email уведомление пользователя."""

    notification = await create_notification(
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
        elif notification_type == NotificationType.BID_PLACED and user.notify_bid_received:
            should_send_email = True
        elif notification_type == NotificationType.AUCTION_LOST and user.notify_lost:
            should_send_email = True

        if should_send_email:
            html_content = build_notification_email_html(
                notification_type.value, title, message, auction_id, auction_title
            )
            _fire_and_forget_email(user.email, title, html_content)
