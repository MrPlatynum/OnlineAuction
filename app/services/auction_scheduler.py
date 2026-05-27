"""Event-driven auction completion.

Replaces the older ``check_expired_auctions`` polling loop. Each active
auction owns two ``asyncio.Task`` instances: one that fires at
``end_time - 5min`` to send the "ending soon" notification, one that
fires at ``end_time`` to settle the auction.

Tasks are tracked per auction id so they can be cancelled (buy-now,
delete) or re-scheduled (auction extension). On startup we walk the
table once and schedule everything still active.

Single-process only: each uvicorn worker would schedule its own copy.
That's fine for the development setup; for multi-worker, completion
would need to be moved behind a DB-level advisory lock.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import database as _db_module
from app.models import Auction
from app.utils.time import utcnow

logger = logging.getLogger(__name__)

ENDING_SOON_LEAD = timedelta(minutes=5)

# Anti-sniping. A bid arriving within ANTISNIPING_WINDOW of the deadline
# extends the auction so the new end_time = now + ANTISNIPING_EXTEND. The
# whole window is granted from "now" rather than added to the old end_time -
# a bid at +1s would otherwise leave only 2:01 instead of a clean 2 minutes.
ANTISNIPING_WINDOW = timedelta(seconds=120)
ANTISNIPING_EXTEND = timedelta(seconds=120)

_completion_tasks: dict[int, asyncio.Task] = {}
_ending_soon_tasks: dict[int, asyncio.Task] = {}

# Handlers are injected by ``services/auctions.py`` at module import so this
# module doesn't have to ``from app.services.auctions import ...`` itself -
# that direction would close the loop with auctions.py's import of
# ``schedule_auction``. With injection the dependency is one-way: scheduler
# is the upstream module, auctions registers into it.
SettleHandler = Callable[[int, AsyncSession], Awaitable[None]]
EndingSoonHandler = Callable[[Auction, AsyncSession], Awaitable[None]]
_settle_handler: SettleHandler | None = None
_ending_soon_handler: EndingSoonHandler | None = None


def register_handlers(
    settle: SettleHandler, ending_soon: EndingSoonHandler
) -> None:
    global _settle_handler, _ending_soon_handler
    _settle_handler = settle
    _ending_soon_handler = ending_soon


def _sleep_seconds(until: datetime) -> float:
    return max(0.0, (until - utcnow()).total_seconds())


async def _wait_and_complete(auction_id: int, expected_end: datetime) -> None:
    """Sleep until ``expected_end``, then complete the auction.

    Re-loads the auction before acting: if its ``end_time`` moved (PATCH
    extension) we re-schedule instead of completing early; if it was
    already settled (buy-now race) we exit silently.
    """
    current = asyncio.current_task()
    try:
        await asyncio.sleep(_sleep_seconds(expected_end))
        async with _db_module.SessionLocal() as db:
            try:
                auction = (
                    await db.execute(
                        select(Auction).where(Auction.id == auction_id)
                    )
                ).scalar_one_or_none()
                if not auction or not auction.is_active:
                    return
                if auction.end_time > utcnow():
                    # Anti-sniping / PATCH extend moved the deadline
                    # while we slept. Re-arm via the no-cancel helpers
                    # instead of schedule_auction - the latter would
                    # call cancel_auction which finds *this* task in
                    # _completion_tasks and task.cancel()s it. Once
                    # cancelled, the next ``await`` (the ``async with``
                    # exit's session.close()) raises CancelledError
                    # mid-shutdown and the FOR-UPDATE-held connection
                    # is returned to the pool in undefined state. The
                    # finally clause below leaves the new task in the
                    # dict because ``is current`` is False for it.
                    _arm_completion_task(auction_id, auction.end_time)
                    _arm_ending_soon_task(auction)
                    return
                if _settle_handler is None:
                    logger.error(
                        "scheduler: no settle handler registered, lot %s stranded",
                        auction_id,
                    )
                    return
                await _settle_handler(auction_id, db)
            except Exception:
                logger.exception("Error completing auction %s", auction_id)
                # Shield the rollback so a shutdown cancel arriving mid-
                # await doesn't leave the session in a half-rolled state
                # (open tx still held on the connection, returned to the
                # pool in undefined state).
                await asyncio.shield(db.rollback())
    except asyncio.CancelledError:
        raise
    finally:
        # Only clear the slot if it still references *this* task. After a
        # reschedule (PATCH extend), schedule_auction has already replaced
        # the dict entry with the new task - popping unconditionally would
        # orphan that new task from cancel_auction / shutdown.
        if _completion_tasks.get(auction_id) is current:
            _completion_tasks.pop(auction_id, None)


async def _wait_and_notify_ending_soon(auction_id: int, fire_at: datetime) -> None:
    current = asyncio.current_task()
    try:
        await asyncio.sleep(_sleep_seconds(fire_at))
        async with _db_module.SessionLocal() as db:
            try:
                auction = (
                    await db.execute(
                        select(Auction).where(Auction.id == auction_id)
                    )
                ).scalar_one_or_none()
                if (
                    not auction
                    or not auction.is_active
                    or auction.ending_soon_notified
                ):
                    return
                if _ending_soon_handler is None:
                    logger.error(
                        "scheduler: no ending-soon handler registered, lot %s",
                        auction_id,
                    )
                    return
                # Mark the flag and commit *before* dispatching notifications.
                # The handler calls notify_user per recipient and each one
                # commits its own row, so a mid-fan-out failure (e.g. bidder
                # 4 of 7 raises) used to leave the flag False while bidders
                # 1-3 had already received their emails - on the next worker
                # restart the task fires again and re-notifies them. Setting
                # the flag first means a partial failure at worst drops the
                # remaining notifications instead of duplicating the early
                # ones; the anti-sniping path in /bids resets the flag if
                # the deadline is extended, so a legitimate re-arm still
                # fires a fresh warning ahead of the new end_time.
                auction.ending_soon_notified = True
                await db.commit()
                await _ending_soon_handler(auction, db)
            except Exception:
                logger.exception(
                    "Error sending ending-soon for auction %s", auction_id
                )
                # Same shield rationale as _wait_and_complete above:
                # don't let a shutdown cancel interrupt the rollback and
                # leave the session half-torn-down.
                await asyncio.shield(db.rollback())
    except asyncio.CancelledError:
        raise
    finally:
        if _ending_soon_tasks.get(auction_id) is current:
            _ending_soon_tasks.pop(auction_id, None)


def _arm_completion_task(auction_id: int, end_time: datetime) -> None:
    """Create the completion task and place it in the dict, cancelling
    whoever already sits in the slot **unless that occupant is the
    current task** - cancelling self would propagate CancelledError into
    the surrounding ``session.close()`` and leak a FOR-UPDATE-held
    connection back to the pool in undefined state.

    Used both by ``schedule_auction`` (where cancel_auction has already
    cleared the slot, so the cancel-existing branch is a no-op) and by
    the internal re-arm inside ``_wait_and_complete``. In the re-arm
    path the slot can hold either ``current`` (no cancel) or a sibling
    task armed by a concurrent external ``schedule_auction`` whose
    cancel raced past the previous occupant - that sibling MUST be
    cancelled before we overwrite, otherwise it stays pending,
    unreachable from ``cancel_auction`` / ``shutdown_scheduler``, and
    fires at its original deadline on stale state.
    """
    current = asyncio.current_task()
    existing = _completion_tasks.get(auction_id)
    if existing is not None and existing is not current and not existing.done():
        existing.cancel()
    _completion_tasks[auction_id] = asyncio.create_task(
        _wait_and_complete(auction_id, end_time),
        name=f"auction-complete-{auction_id}",
    )


def _arm_ending_soon_task(auction: Auction) -> None:
    """Same as ``_arm_completion_task`` for the five-minute warning
    side. No-op when the flag is already set or the lead-time has
    already passed. Cancels any prior occupant of the slot (it is
    never the current task on this code path, so the self-cancel
    pitfall doesn't apply)."""
    if auction.ending_soon_notified:
        return
    fire_at = auction.end_time - ENDING_SOON_LEAD
    if fire_at <= utcnow():
        return
    existing = _ending_soon_tasks.get(auction.id)
    if existing is not None and not existing.done():
        existing.cancel()
    _ending_soon_tasks[auction.id] = asyncio.create_task(
        _wait_and_notify_ending_soon(auction.id, fire_at),
        name=f"auction-ending-soon-{auction.id}",
    )


def schedule_auction(auction: Auction) -> None:
    """Schedule (or re-schedule) completion + ending-soon for ``auction``.

    Safe to call multiple times - any pre-existing tasks for the same id
    are cancelled first. No-op for inactive auctions.

    Intentionally synchronous (no ``await``). The dict mutations below
    rely on asyncio's run-to-completion semantics: with no yield point
    inside the function body, two concurrent callers cannot interleave
    a cancel from one with a create_task from the other. Adding an
    ``await`` here breaks that invariant - either restructure to keep
    it sync, or wrap the body in an ``asyncio.Lock`` to restore
    serialisation.
    """
    cancel_auction(auction.id)
    if not auction.is_active:
        return
    _arm_completion_task(auction.id, auction.end_time)
    _arm_ending_soon_task(auction)


def cancel_auction(auction_id: int) -> None:
    """Cancel pending tasks for an auction (buy-now, delete)."""
    for store in (_completion_tasks, _ending_soon_tasks):
        task = store.pop(auction_id, None)
        if task and not task.done():
            task.cancel()


async def schedule_active_auctions() -> None:
    """Startup hook - walks the table and schedules every active row.

    Auctions whose ``end_time`` is already in the past (server was down)
    have ``_sleep_seconds`` return 0 and complete on the next loop tick.
    """
    async with _db_module.SessionLocal() as db:
        active = (
            await db.execute(
                select(Auction).where(Auction.is_active.is_(True))
            )
        ).scalars().all()
        for auction in active:
            schedule_auction(auction)
    logger.info("Scheduled %d active auctions", len(active))


async def shutdown_scheduler() -> None:
    """Cancel every pending task on shutdown and await them."""
    tasks = list(_completion_tasks.values()) + list(_ending_soon_tasks.values())
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    _completion_tasks.clear()
    _ending_soon_tasks.clear()
