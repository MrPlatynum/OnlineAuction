"""Regression: ``notify_user`` must *persist* the outbox row it enrols.

``create_notification`` commits the in-app row inside ``notify_user``;
the email row is enrolled afterwards via the ``enqueue_email(db=...)``
seam, which deliberately does not commit. ``get_db`` does not commit on
exit either, so without a trailing commit inside ``notify_user`` that
row is rolled back on session close and the email silently vanishes -
notably the last ``notify_user`` in a handler, whose row no subsequent
``create_notification`` commit happens to rescue.

The existing email assertions use the ``capture_emails`` / autouse stub
seams, which only observe the *call* and never the committed row, so
this gap went unseen. These tests drive the real outbox seam and assert
the row survives in a fresh session.
"""

from sqlalchemy import func, select

from app import database as _db_module
from app.models import EmailOutbox, User
from app.services import notifications as notif_mod
from app.services.email_outbox import enqueue_email
from app.services.notifications import NotificationType, notify_user
from tests.conftest import _register_and_verify


async def _outbox_count() -> int:
    async with _db_module.SessionLocal() as db:
        return await db.scalar(select(func.count()).select_from(EmailOutbox))


async def _load_user(user_id: int) -> User:
    async with _db_module.SessionLocal() as db:
        return (
            await db.execute(select(User).where(User.id == user_id))
        ).scalar_one()


async def test_notify_user_commits_outbox_row(client, monkeypatch):
    """A single ``notify_user`` call with email enabled leaves a
    committed outbox row behind, visible from a fresh session."""
    bundle = await _register_and_verify(client, "alice")
    user = await _load_user(bundle["user"]["id"])
    assert user.email_notifications and user.notify_outbid

    # Restore the real durable seam (the autouse fixture stubs it to a
    # no-op). This mirrors the production ``_fire_and_forget_email``:
    # enrol the row in the caller's session without committing.
    async def _real_seam(to, subject, html, *, db=None):
        await enqueue_email(to, subject, html, db=db)

    monkeypatch.setattr(notif_mod, "_fire_and_forget_email", _real_seam)

    # Drive ``notify_user`` exactly like a request handler: a session
    # that is closed WITHOUT a trailing commit (``get_db`` semantics).
    async with _db_module.SessionLocal() as db:
        await notify_user(
            db, user, NotificationType.BID_OUTBID,
            "Вашу ставку перебили", "Сделайте новую ставку",
            auction_id=None, auction_title=None,
        )

    assert await _outbox_count() == 1


async def test_notify_user_skips_outbox_when_email_disabled(client, monkeypatch):
    """The commit path is gated on an actual enrolment - a user who
    opted out of the per-type email leaves no row (and the no-email hot
    path stays a single round-trip)."""
    bundle = await _register_and_verify(client, "bob")
    async with _db_module.SessionLocal() as db:
        user = (
            await db.execute(select(User).where(User.id == bundle["user"]["id"]))
        ).scalar_one()
        user.notify_outbid = False
        await db.commit()
    user = await _load_user(bundle["user"]["id"])

    async def _real_seam(to, subject, html, *, db=None):
        await enqueue_email(to, subject, html, db=db)

    monkeypatch.setattr(notif_mod, "_fire_and_forget_email", _real_seam)

    async with _db_module.SessionLocal() as db:
        await notify_user(
            db, user, NotificationType.BID_OUTBID,
            "Вашу ставку перебили", "Сделайте новую ставку",
            auction_id=None, auction_title=None,
        )

    assert await _outbox_count() == 0
