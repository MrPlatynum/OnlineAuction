
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import PUBLIC_BASE_URL
from app.models import Notification, NotificationType, User
from app.services.email import (
    build_notification_email_html,
    build_password_changed_email_html,
    build_password_reset_email_html,
    build_verification_email_html,
)
from app.services.email_outbox import enqueue_email
from app.utils.security import create_email_verify_token, create_password_reset_token


def _fire_and_forget_email(to_email: str, subject: str, html: str) -> None:
    """Backwards-compatible shim. Older callers all routed through
    here; now this just enqueues onto the durable outbox so the
    background worker handles delivery (with retry / dead-letter).
    Kept as a single seam so tests that monkeypatch this name still
    see every email the app schedules."""
    enqueue_email(to_email, subject, html)


def send_verification_email(user: User) -> None:
    """Post-register verification email. Goes through the durable
    outbox (``enqueue_email``): the background worker drains the
    table with retry/backoff and dead-lettering, so app crashes or
    SMTP outages don't lose mail. Caller is expected to have
    committed the User row so its id and current email are stable."""
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
    auction_id: int | None = None,
    auction_title: str | None = None,
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
    auction_id: int | None = None,
    auction_title: str | None = None,
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
