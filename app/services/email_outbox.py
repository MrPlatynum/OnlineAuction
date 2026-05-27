"""Durable email queue with retry/backoff.

Replaces the previous fire-and-forget ``asyncio.create_task`` path.
Every transactional message (verification, password reset, change
notice, notification bell-pushes) is persisted to the ``email_outbox``
table; a background worker drains the table and sends via SMTP.

Why this exists: a dropped /password-reset email locks a user out of
their account, so "best effort" delivery via in-memory tasks isn't
good enough. The outbox persists the message before the HTTP handler
returns, so an SMTP outage / app crash / restart no longer loses
mail - the worker picks it up on the next tick.

Single-worker isn't required, but a background loop *per process*
is fine: ``SELECT ... FOR UPDATE SKIP LOCKED`` makes multi-worker
safe by design. The auction scheduler has the opposite property -
multi-worker there would need an advisory lock.
"""

import asyncio
import logging
import os
from datetime import timedelta

from sqlalchemy import select

from app import database as _db_module
from app.models import EmailOutbox
from app.services.email import send_email_notification
from app.utils.time import utcnow

logger = logging.getLogger(__name__)


def _worker_enabled() -> bool:
    """Allow the test suite (and ad-hoc dev runs) to skip the
    background ticker. Tests drive the worker function directly via
    ``_run_one_tick`` so they don't need (and don't want) a periodic
    ticker hitting SMTP."""
    return os.getenv("AUCTION_OUTBOX_WORKER_ENABLED", "true").lower() not in {
        "false", "0", "no", "off",
    }

# Worker polls this often. Short enough that a transactional email
# feels close to instant in dev; long enough that an idle table
# doesn't hammer Postgres.
WORKER_TICK_SECONDS = 30

# Per-tick batch ceiling. Keeps a single backlog burst from holding
# one tick open for minutes - the next tick will pick up the rest.
WORKER_BATCH_SIZE = 10

# Retry budget for new rows. Five attempts spread by the schedule
# below give us roughly seven hours of recovery before dead-letter.
DEFAULT_MAX_ATTEMPTS = 5

# Backoff schedule by attempt number. attempts=0 means "never tried,
# scheduled for now"; the worker increments before computing the
# next wait, so this table indexes by post-failure attempt count.
_BACKOFF_BY_ATTEMPT: dict[int, timedelta] = {
    1: timedelta(minutes=1),
    2: timedelta(minutes=5),
    3: timedelta(minutes=15),
    4: timedelta(hours=1),
    5: timedelta(hours=6),
}
_BACKOFF_MAX = timedelta(hours=6)

_worker_task: asyncio.Task | None = None
_stop_event: asyncio.Event | None = None


def backoff_for_attempt(attempts: int) -> timedelta:
    """Wait before the *next* SMTP try after ``attempts`` failures.
    Returns the largest entry for anything beyond the table so a
    bigger max_attempts won't crash the worker - it just plateaus."""
    return _BACKOFF_BY_ATTEMPT.get(attempts, _BACKOFF_MAX)


async def enqueue_email(
    to_email: str,
    subject: str,
    html_body: str,
    *,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> None:
    """Persist one outbox row. Caller awaits the INSERT before
    returning its HTTP response, so the row is durable on disk
    before the user sees a 200 / 202 - an SIGKILL between the
    response and a deferred INSERT (the previous create_task design)
    no longer loses transactional mail.

    Failures are logged and swallowed: a register / password-reset
    handler should not 500 just because the outbox table is briefly
    unreachable. The user can retry; the bigger durability win was
    making the *successful* path actually durable."""
    try:
        async with _db_module.SessionLocal() as db:
            db.add(
                EmailOutbox(
                    to_email=to_email,
                    subject=subject,
                    html_body=html_body,
                    status="pending",
                    attempts=0,
                    max_attempts=max_attempts,
                    next_attempt_at=utcnow(),
                    created_at=utcnow(),
                )
            )
            await db.commit()
    except Exception:
        logger.exception("Failed to enqueue email to %s", to_email)


async def _process_one(row: EmailOutbox, db) -> None:
    """Attempt one SMTP send for ``row``. On success mark sent; on
    failure increment attempts and either schedule a retry or move
    to the dead-letter ``failed`` state."""
    try:
        await send_email_notification(row.to_email, row.subject, row.html_body)
    except Exception as exc:
        row.attempts += 1
        row.last_error = repr(exc)
        if row.attempts >= row.max_attempts:
            row.status = "failed"
            # Structured ``extra`` payload so the JSON logger
            # (LOG_FORMAT=json, see app_factory) emits a parseable event
            # for ops alerts - `event=outbox_dead_letter` is the single
            # filter to grep.
            logger.error(
                "Outbox row %s dead-lettered after %d attempts: %s",
                row.id, row.attempts, exc,
                extra={
                    "event": "outbox_dead_letter",
                    "outbox_id": row.id,
                    "to_email": row.to_email,
                    "subject": row.subject,
                    "attempts": row.attempts,
                    "last_error": repr(exc),
                },
            )
        else:
            row.next_attempt_at = utcnow() + backoff_for_attempt(row.attempts)
            logger.warning(
                "Outbox row %s retry %d/%d after %s",
                row.id, row.attempts, row.max_attempts, exc,
            )
        return
    row.status = "sent"
    row.sent_at = utcnow()


async def _run_one_tick() -> int:
    """Process a single batch. Returns the number of rows processed
    (sent + scheduled + dead-lettered); used by tests to assert
    progress without sleeping."""
    processed = 0
    async with _db_module.SessionLocal() as db:
        # FOR UPDATE SKIP LOCKED makes this loop safe under any
        # number of concurrent workers - each tick claims rows it
        # processes and others skip them. ORDER BY created_at gives
        # FIFO delivery, which matches user expectations (the
        # verification email should arrive before the change-notice
        # if both were enqueued in the same second).
        rows = (
            await db.execute(
                select(EmailOutbox)
                .where(EmailOutbox.status == "pending")
                .where(EmailOutbox.next_attempt_at <= utcnow())
                .order_by(EmailOutbox.created_at)
                .limit(WORKER_BATCH_SIZE)
                .with_for_update(skip_locked=True)
            )
        ).scalars().all()
        for row in rows:
            # Commit per row. A batch commit at the end of the loop
            # used to roll back every row's state change if any later
            # _process_one raised: row 1 marked sent + row 2 marked
            # failed + row 3 raises = all three reset to pending and
            # on the next tick row 1's email is sent again.
            try:
                await _process_one(row, db)
                await db.commit()
                processed += 1
            except Exception:
                logger.exception(
                    "Outbox row %s tick crashed; rolling back its state",
                    row.id,
                )
                await db.rollback()
    return processed


async def _worker_loop(stop_event: asyncio.Event) -> None:
    """Run ``_run_one_tick`` on a fixed cadence until ``stop_event``
    fires. Errors inside one tick don't kill the loop - they're
    logged and the next tick still runs.

    ``asyncio.wait`` is preferred over a bare ``asyncio.sleep`` so
    shutdown can interrupt mid-wait instead of having to wait out
    the full tick interval.
    """
    logger.info("Email outbox worker started")
    try:
        while not stop_event.is_set():
            try:
                await _run_one_tick()
            except Exception:
                logger.exception("Outbox worker tick failed")
            try:
                await asyncio.wait_for(stop_event.wait(), WORKER_TICK_SECONDS)
            except TimeoutError:
                pass
    finally:
        logger.info("Email outbox worker stopped")


def start_outbox_worker() -> None:
    """Start the background worker. No-op if it's already running -
    avoids duplicate workers when ``create_app`` is called more than
    once in a test process. Also no-op when the worker is disabled
    via ``AUCTION_OUTBOX_WORKER_ENABLED=false`` (tests)."""
    global _worker_task, _stop_event
    if not _worker_enabled():
        logger.info("Email outbox worker disabled by env flag")
        return
    if _worker_task and not _worker_task.done():
        return
    _stop_event = asyncio.Event()
    _worker_task = asyncio.create_task(
        _worker_loop(_stop_event), name="email-outbox-worker"
    )


async def stop_outbox_worker() -> None:
    """Signal the worker to stop and await its exit. Called from the
    FastAPI lifespan ``finally`` so a SIGTERM lets the worker
    finish its current tick (with COMMIT) instead of being killed
    mid-transaction."""
    global _worker_task, _stop_event
    if _stop_event is not None:
        _stop_event.set()
    if _worker_task is not None:
        try:
            await asyncio.wait_for(_worker_task, timeout=10)
        except (TimeoutError, asyncio.CancelledError):
            _worker_task.cancel()
    _worker_task = None
    _stop_event = None
