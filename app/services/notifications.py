"""Three-channel notification dispatch: in-app row, WebSocket push,
and email. ``notify_user`` is the single fan-out helper every caller
goes through - per-user ``notify_*`` flags gate each channel so a
recipient can mute email without losing in-app history. Email send
is fire-and-forget via the persistent outbox queue so an SMTP
hiccup doesn't take down the request that triggered the notify.
"""

import asyncio
import logging

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

logger = logging.getLogger(__name__)

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
    # NEW_LOT has no dedicated per-type opt-out column: subscribing to a
    # seller is itself the opt-in (the user can unsubscribe to silence
    # the channel). Mapping to the master ``email_notifications`` flag
    # means the email fires whenever the outer if-check would already
    # have passed - effectively "no per-type opt-out, master toggle
    # still applies".
    NotificationType.NEW_LOT:        "email_notifications",
}


async def _fire_and_forget_email(
    to_email: str,
    subject: str,
    html: str,
    *,
    db: AsyncSession | None = None,
) -> None:
    """Single seam to the durable outbox. The name predates the
    rewrite to a persistent queue and is kept so existing test
    monkeypatches still hit every email the app schedules; the INSERT
    itself is now awaited synchronously so a SIGKILL after the HTTP
    response can't lose the row.

    When ``db`` is supplied the outbox row enrolls in the caller's
    session (atomic with whatever domain mutation triggered the mail);
    otherwise ``enqueue_email`` opens its own session as a fallback."""
    await enqueue_email(to_email, subject, html, db=db)


async def send_verification_email(
    user: User, *, db: AsyncSession | None = None
) -> None:
    """Post-register verification email. Goes through the durable
    outbox (``enqueue_email``): the background worker drains the
    table with retry/backoff and dead-lettering, so app crashes or
    SMTP outages don't lose mail.

    Pass ``db`` to make the outbox INSERT atomic with the caller's
    commit (the registration flow does this so the verification mail
    cannot exist for a user that never persisted, and vice versa)."""
    token = create_email_verify_token(user)
    link = f"{PUBLIC_BASE_URL}/verify-email.html?token={token}"
    html_content = build_verification_email_html(user.username, link)
    await _fire_and_forget_email(
        user.email,
        "Подтвердите email - Лотус",
        html_content,
        db=db,
    )


async def send_password_reset_email(
    user: User, *, db: AsyncSession | None = None
) -> None:
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
        db=db,
    )


async def send_password_changed_email(
    user: User, *, db: AsyncSession | None = None
) -> None:
    """Notification email sent right after /password-reset/confirm
    succeeds. The legitimate user sees the trail even if the reset
    was triggered by someone who'd taken over their inbox - they
    can react before the attacker has time to dig in."""
    html_content = build_password_changed_email_html(user.username)
    await _fire_and_forget_email(
        user.email,
        "Пароль изменён - Лотус",
        html_content,
        db=db,
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

    # ``create_notification`` above already committed, so the outbox row
    # ``_maybe_send_email`` enrols lands in a *fresh* transaction with no
    # commit behind it. ``get_db`` doesn't commit on exit, so without the
    # commit below the row is rolled back on session close and the email
    # silently vanishes - notably the last ``notify_user`` in a handler,
    # whose row no later ``create_notification`` commit happens to rescue.
    # Commit only when a row was actually enrolled to keep the no-email
    # hot path (most notifications) at a single round-trip.
    if await _maybe_send_email(
        user, notification_type, title, message, auction_id, auction_title, db=db
    ):
        await db.commit()


def _email_enabled(user: User, notification_type: NotificationType) -> bool:
    if not user.email_notifications:
        return False
    opt_out_flag = _EMAIL_OPT_OUT_FLAG.get(notification_type)
    return bool(opt_out_flag) and getattr(user, opt_out_flag, False)


async def _maybe_send_email(
    user: User,
    notification_type: NotificationType,
    title: str,
    message: str,
    auction_id: int | None,
    auction_title: str | None,
    *,
    db: AsyncSession | None = None,
) -> bool:
    """Enrol the notification email in the outbox when the user opted in.

    Returns ``True`` when a row was enrolled in ``db`` (so the caller knows
    it owns an uncommitted outbox row), ``False`` otherwise.
    """
    if _email_enabled(user, notification_type):
        html_content = build_notification_email_html(
            notification_type.value, title, message, auction_id, auction_title
        )
        await _fire_and_forget_email(user.email, title, html_content, db=db)
        return True
    return False


async def notify_many(
    db: AsyncSession,
    payloads: list[tuple[User, NotificationType, str, str]],
    *,
    auction_id: int | None = None,
    auction_title: str | None = None,
    manager=None,
) -> None:
    """Batched fan-out for a multi-recipient notification dispatch.

    All in-app ``Notification`` rows AND the per-recipient ``EmailOutbox``
    rows (for users whose email channel is enabled) enrol in the
    caller's session and commit together - a single DB round-trip
    persists both channels' durability state instead of the prior
    pattern of one Notification commit + one outbox SessionLocal +
    commit per recipient. WS pushes don't touch the database and run
    concurrently after the commit, so a slow client cannot block the
    next recipient.

    The financial commit has already landed by the time callers reach
    this helper, so the notification side is best-effort - per-channel
    WS failures are logged and isolated inside the dispatcher. A DB
    failure on the batch commit will roll back both channels together,
    matching the durability invariant of the outbox pattern.

    Preferred over a ``for ... await notify_user`` loop on any path
    that touches more than a handful of recipients (auction completion,
    new-lot subscriber broadcast); single-recipient sites still use
    ``notify_user`` directly because the batching gains nothing there.
    """
    if not payloads:
        return

    notif_rows: list[Notification] = []
    outbox_jobs: list[tuple[User, NotificationType, str, str]] = []
    for user, notif_type, title, message in payloads:
        notif_rows.append(
            Notification(
                user_id=user.id,
                type=notif_type.value,
                title=title,
                message=message,
                auction_id=auction_id,
                auction_title=auction_title,
            )
        )
        if _email_enabled(user, notif_type):
            outbox_jobs.append((user, notif_type, title, message))

    db.add_all(notif_rows)
    for user, notif_type, title, message in outbox_jobs:
        html_content = build_notification_email_html(
            notif_type.value, title, message, auction_id, auction_title
        )
        # Goes through the documented _fire_and_forget_email seam so
        # tests that monkeypatch it for capture/noop still observe every
        # email this path enqueues. The seam forwards db=db to
        # enqueue_email, which enrols the row in the current session
        # without committing; the batch commit below covers it.
        await _fire_and_forget_email(user.email, title, html_content, db=db)
    await db.commit()
    # No per-row ``db.refresh(row)`` loop here. ``id`` lands via the
    # INSERT...RETURNING that SQLAlchemy issues on commit (every PK in
    # this project is autoincrement), and ``created_at`` is a Python-
    # side ``default=utcnow`` which the insert machinery evaluates
    # before sending the SQL - both attributes are already populated
    # on the in-memory instances. The prior per-row refresh added N
    # extra round-trips and undid the batching win on hot fan-out
    # paths (auction settle, NEW_LOT subscriber broadcast).

    if manager is None:
        return

    async def _push_ws(user: User, notif_type: NotificationType, title: str,
                      message: str, row: Notification) -> None:
        try:
            await manager.send_notification(user.id, {
                "type": "notification",
                "notification": {
                    "id": row.id,
                    "type": notif_type.value,
                    "title": title,
                    "message": message,
                    "auction_id": auction_id,
                    "auction_title": auction_title,
                    "created_at": row.created_at.isoformat(),
                },
            })
        except Exception:
            logger.exception(
                "WS notification push failed for user %s (type=%s)",
                user.id, notif_type.value,
            )

    await asyncio.gather(*(
        _push_ws(user, notif_type, title, message, row)
        for (user, notif_type, title, message), row in zip(payloads, notif_rows, strict=True)
    ))
