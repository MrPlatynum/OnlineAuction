"""Email outbox worker.

Validates that ``_fire_and_forget_email`` now persists rows through
``enqueue_email``; the worker drains pending rows, retries SMTP
failures with exponential backoff, and dead-letters after the retry
budget is exhausted.

Run-one-tick API is preferred over the periodic loop: tests assert
behaviour after a deterministic number of attempts instead of racing
against ``WORKER_TICK_SECONDS``.
"""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models import EmailOutbox
from app.services import email_outbox
from app.utils.time import utcnow


async def _insert(to_email: str = "to@example.com", **overrides) -> int:
    """Helper that awaits ``enqueue_email`` directly so a test can
    assert on the persisted row without racing the worker tick."""
    await email_outbox.enqueue_email(
        to_email=to_email,
        subject=overrides.get("subject", "Subject"),
        html_body=overrides.get("html_body", "<p>body</p>"),
        max_attempts=overrides.get("max_attempts", 3),
    )
    async with SessionLocal() as db:
        row = (
            await db.execute(select(EmailOutbox).order_by(EmailOutbox.id.desc()))
        ).scalars().first()
    return row.id


async def _get_row(row_id: int) -> EmailOutbox:
    async with SessionLocal() as db:
        return (
            await db.execute(select(EmailOutbox).where(EmailOutbox.id == row_id))
        ).scalar_one()


async def test_enqueue_creates_pending_row():
    row_id = await _insert(to_email="alice@example.com", subject="Hi")
    row = await _get_row(row_id)
    assert row.status == "pending"
    assert row.to_email == "alice@example.com"
    assert row.subject == "Hi"
    assert row.attempts == 0
    assert row.next_attempt_at is not None
    assert row.sent_at is None


async def test_tick_processes_pending_row_to_sent(monkeypatch):
    """SMTP succeeds → row is marked ``sent`` with a ``sent_at``
    timestamp; attempts stay at 0 because we count *failures*, not
    deliveries."""
    sent: list[tuple[str, str, str]] = []

    async def fake_send(to, subject, html):
        sent.append((to, subject, html))

    monkeypatch.setattr(email_outbox, "send_email_notification", fake_send)

    row_id = await _insert(to_email="ok@example.com")
    processed = await email_outbox._run_one_tick()

    assert processed == 1
    row = await _get_row(row_id)
    assert row.status == "sent"
    assert row.sent_at is not None
    assert sent == [("ok@example.com", "Subject", "<p>body</p>")]


async def test_tick_reschedules_after_failure(monkeypatch):
    """SMTP raises → attempts increment, ``next_attempt_at`` jumps
    forward by the backoff schedule, status stays ``pending`` so the
    worker picks it up on a later tick. ``last_error`` records the
    exception so an operator can grep the table later."""

    async def boom(*_a, **_kw):
        raise RuntimeError("SMTP refused")

    monkeypatch.setattr(email_outbox, "send_email_notification", boom)

    before = utcnow()
    row_id = await _insert(to_email="fail@example.com", max_attempts=3)
    await email_outbox._run_one_tick()

    row = await _get_row(row_id)
    assert row.status == "pending"
    assert row.attempts == 1
    assert "SMTP refused" in (row.last_error or "")
    # Next attempt should be at least the 1m backoff away from "now".
    assert (row.next_attempt_at - before) >= timedelta(seconds=55)


async def test_tick_skips_rows_whose_next_attempt_is_future(monkeypatch):
    """A row scheduled for the future must not be picked up - the
    ``next_attempt_at <= now()`` filter is what makes the backoff
    effective."""
    monkeypatch.setattr(
        email_outbox,
        "send_email_notification",
        lambda *_a, **_kw: pytest.fail("worker shouldn't fire on future row"),
    )

    async with SessionLocal() as db:
        row = EmailOutbox(
            to_email="future@example.com",
            subject="x",
            html_body="x",
            status="pending",
            attempts=0,
            max_attempts=3,
            next_attempt_at=utcnow() + timedelta(minutes=5),
            created_at=utcnow(),
        )
        db.add(row)
        await db.commit()

    processed = await email_outbox._run_one_tick()
    assert processed == 0


async def test_dead_letters_after_max_attempts(monkeypatch):
    """After ``max_attempts`` failures the row moves to ``failed``
    (terminal dead-letter) so the worker stops picking it up forever."""

    async def boom(*_a, **_kw):
        raise RuntimeError("nope")

    monkeypatch.setattr(email_outbox, "send_email_notification", boom)

    row_id = await _insert(to_email="dead@example.com", max_attempts=3)

    for _ in range(3):
        # Pretend the backoff window has passed before each retry so
        # the worker re-picks the same row. Real time advances on its
        # own; tests can't wait several minutes.
        async with SessionLocal() as db:
            row = (await db.execute(
                select(EmailOutbox).where(EmailOutbox.id == row_id)
            )).scalar_one()
            row.next_attempt_at = utcnow() - timedelta(seconds=1)
            await db.commit()
        await email_outbox._run_one_tick()

    row = await _get_row(row_id)
    assert row.status == "failed"
    assert row.attempts == 3


async def test_concurrent_ticks_skip_locked_each_other(monkeypatch):
    """``SELECT ... FOR UPDATE SKIP LOCKED`` lets two workers run
    without double-sending: each tick claims the rows it sees and
    leaves the rest for the next iteration."""
    import asyncio

    seen: list[int] = []

    async def fake_send(_to, _subject, _html):
        # Hold the row briefly to widen the window where the other
        # tick could (incorrectly) double-claim it.
        await asyncio.sleep(0.05)

    monkeypatch.setattr(email_outbox, "send_email_notification", fake_send)

    ids = [await _insert(to_email=f"u{i}@example.com") for i in range(4)]

    # Hook _process_one so we can observe which tick processed which row.
    original = email_outbox._process_one

    async def tracking(row, db):
        seen.append(row.id)
        await original(row, db)

    monkeypatch.setattr(email_outbox, "_process_one", tracking)

    await asyncio.gather(email_outbox._run_one_tick(), email_outbox._run_one_tick())

    # Each row processed exactly once, regardless of which tick got it.
    assert sorted(seen) == sorted(ids)
    async with SessionLocal() as db:
        rows = (
            await db.execute(
                select(EmailOutbox).where(EmailOutbox.id.in_(ids))
            )
        ).scalars().all()
    assert all(r.status == "sent" for r in rows)


def test_backoff_schedule_is_monotonic():
    """The backoff table must not regress: a later attempt always
    waits at least as long as the previous one. Otherwise dead-
    letter timing would be non-monotonic and operators couldn't
    estimate worst-case delay."""
    prev = timedelta(0)
    for attempt in range(1, 10):
        delay = email_outbox.backoff_for_attempt(attempt)
        assert delay >= prev
        prev = delay


async def test_register_flow_persists_through_outbox(client, monkeypatch):
    """End-to-end smoke: an HTTP /register call enqueues a real
    outbox row. Confirms the conftest no-op fixture can be lifted
    on demand and the producer-to-row path holds together."""
    # Lift the conftest's default no-op so /register actually routes
    # through enqueue_email.
    from app.services import email_outbox as ob_mod
    from app.services import notifications as notif_mod

    async def _route_to_outbox(to, subj, html, *, db=None):
        await ob_mod.enqueue_email(to, subj, html, db=db)

    monkeypatch.setattr(notif_mod, "_fire_and_forget_email", _route_to_outbox)

    r = await client.post("/api/register", json={
        "username": "outboxer",
        "email": "outboxer@example.com",
        "password": "password123",
    })
    assert r.status_code == 200, r.text

    # enqueue_email now awaits the INSERT inline, so the row is on
    # disk by the time /register returned its 200 - no draining of
    # in-flight tasks needed.
    async with SessionLocal() as db:
        rows = (
            await db.execute(
                select(EmailOutbox).where(
                    EmailOutbox.to_email == "outboxer@example.com"
                )
            )
        ).scalars().all()
    assert len(rows) == 1
    assert rows[0].status == "pending"
    assert "verify-email.html?token=" in rows[0].html_body
