"""Three-channel notification dispatch: in-app row, WebSocket push,
and email. ``notify_user`` is the single fan-out helper every caller
goes through - per-user ``notify_*`` flags gate each channel so a
recipient can mute email without losing in-app history. Email send
is fire-and-forget via the persistent outbox queue so an SMTP
hiccup doesn't take down the request that triggered the notify.
"""

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

# Per-type opt-out: every NotificationType maps to the boolean column on
# ``User`` whose ``False`` value silences the email channel for that type
# (in-app + WS push fire unconditionally). Adding a new type means one
# more row here plus the matching User column - no branching elsewhere.
_EMAIL_OPT_OUT_FLAG: dict[NotificationType, str] = {
    NotificationType.BID_OUTBID:     "notify_outbid",
    NotificationType.AUCTION_WON:    "notify_winning",
    NotificationType.AUCTION_ENDING: "notify_ending",
    NotificationType.AUCTION_SOLD:   "notify_sold",
    NotificationType.BID_PLACED:     "notify_bid_received",
    NotificationType.AUCTION_LOST:   "notify_lost",
}


async def _fire_and_forget_email(to_email: str, subject: str, html: str) -> None:
    """Single seam to the durable outbox. The name predates the
    rewrite to a persistent queue and is kept so existing test
    monkeypatches still hit every email the app schedules; the
    INSERT itself is now awaited synchronously so a SIGKILL after
    the HTTP response can't lose the row."""
    await enqueue_email(to_email, subject, html)


async def send_verification_email(user: User) -> None:
    """Post-register verification email. Goes through the durable
    outbox (``enqueue_email``): the background worker drains the
    table with retry/backoff and dead-lettering, so app crashes or
    SMTP outages don't lose mail. Caller is expected to have
    committed the User row so its id and current email are stable."""
    token = create_email_verify_token(user)
    link = f"{PUBLIC_BASE_URL}/verify-email.html?token={token}"
    html_content = build_verification_email_html(user.username, link)
    await _fire_and_forget_email(
        user.email,
        "Подтвердите email - Лотус",
        html_content,
    )


async def send_password_reset_email(user: User) -> None:
    """Outbox-backed password-reset link. The token's ``tv`` claim is
    read from the user's current ``token_version`` - a later
    successful /password-reset/confirm bumps tv so this link (and any
    other in-flight reset link for the same account) auto-invalidate."""
    token = create_password_reset_token(user)
    link = f"{PUBLIC_BASE_URL}/password-reset.html?token={token}"
    html_content = build_password_reset_email_html(user.username, link)
    await _fire_and_forget_email(
        user.email,
        "Сброс пароля - Лотус",
        html_content,
    )


async def send_password_changed_email(user: User) -> None:
    """Notification email sent right after /password-reset/confirm
    succeeds. The legitimate user sees the trail even if the reset
    was triggered by someone who'd taken over their inbox - they
    can react before the attacker has time to dig in."""
    html_content = build_password_changed_email_html(user.username)
    await _fire_and_forget_email(
        user.email,
        "Пароль изменён - Лотус",
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
    """Insert one ``Notification`` row and return the persisted instance.

    Caller-facing helper used by ``notify_user`` and the few places that
    need to write a row without fanning out the WS / email channels
    (e.g. legacy paths that pre-date the multi-channel dispatcher).
    """
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
    """Fan a notification out across all three channels.

    Always writes the in-app row (via ``create_notification``). The WS
    push runs when ``manager`` is supplied. The email send runs only
    when the user has the per-type opt-out flag enabled - the mapping
    lives in ``_EMAIL_OPT_OUT_FLAG`` so adding a new ``NotificationType``
    is one line, not another branch in this function.
    """

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
        opt_out_flag = _EMAIL_OPT_OUT_FLAG.get(notification_type)
        should_send_email = bool(opt_out_flag) and getattr(user, opt_out_flag, False)

        if should_send_email:
            html_content = build_notification_email_html(
                notification_type.value, title, message, auction_id, auction_title
            )
            await _fire_and_forget_email(user.email, title, html_content)
