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
from datetime import datetime, timedelta

from sqlalchemy import select

from app import database as _db_module
from app.models import Auction
from app.utils.time import utcnow

logger = logging.getLogger(__name__)

ENDING_SOON_LEAD = timedelta(minutes=5)

_completion_tasks: dict[int, asyncio.Task] = {}
_ending_soon_tasks: dict[int, asyncio.Task] = {}


def _sleep_seconds(until: datetime) -> float:
    return max(0.0, (until - utcnow()).total_seconds())


async def _wait_and_complete(auction_id: int, expected_end: datetime) -> None:
    """Sleep until ``expected_end``, then complete the auction.

    Re-loads the auction before acting: if its ``end_time`` moved (PATCH
    extension) we re-schedule instead of completing early; if it was
    already settled (buy-now race) we exit silently.
    """
    from app.services.auctions import complete_auction

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
                    schedule_auction(auction)
                    return
                await complete_auction(auction_id, db)
            except Exception:
                logger.exception("Error completing auction %s", auction_id)
                await db.rollback()
    except asyncio.CancelledError:
        raise
    finally:
        # Only clear the slot if it still references *this* task. After a
        # reschedule (PATCH extend), schedule_auction has already replaced
        # the dict entry with the new task — popping unconditionally would
        # orphan that new task from cancel_auction / shutdown.
        if _completion_tasks.get(auction_id) is current:
            _completion_tasks.pop(auction_id, None)


async def _wait_and_notify_ending_soon(auction_id: int, fire_at: datetime) -> None:
    from app.services.auctions import notify_auction_ending_soon

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
                await notify_auction_ending_soon(auction, db)
                auction.ending_soon_notified = True
                await db.commit()
            except Exception:
                logger.exception(
                    "Error sending ending-soon for auction %s", auction_id
                )
                await db.rollback()
    except asyncio.CancelledError:
        raise
    finally:
        if _ending_soon_tasks.get(auction_id) is current:
            _ending_soon_tasks.pop(auction_id, None)


def schedule_auction(auction: Auction) -> None:
    """Schedule (or re-schedule) completion + ending-soon for ``auction``.

    Safe to call multiple times — any pre-existing tasks for the same id
    are cancelled first. No-op for inactive auctions.
    """
    cancel_auction(auction.id)
    if not auction.is_active:
        return

    _completion_tasks[auction.id] = asyncio.create_task(
        _wait_and_complete(auction.id, auction.end_time),
        name=f"auction-complete-{auction.id}",
    )
    if not auction.ending_soon_notified:
        fire_at = auction.end_time - ENDING_SOON_LEAD
        if fire_at > utcnow():
            _ending_soon_tasks[auction.id] = asyncio.create_task(
                _wait_and_notify_ending_soon(auction.id, fire_at),
                name=f"auction-ending-soon-{auction.id}",
            )


def cancel_auction(auction_id: int) -> None:
    """Cancel pending tasks for an auction (buy-now, delete)."""
    for store in (_completion_tasks, _ending_soon_tasks):
        task = store.pop(auction_id, None)
        if task and not task.done():
            task.cancel()


async def schedule_active_auctions() -> None:
    """Startup hook — walks the table and schedules every active row.

    Auctions whose ``end_time`` is already in the past (server was down)
    have ``_sleep_seconds`` return 0 and complete on the next loop tick.
    """
    async with _db_module.SessionLocal() as db:
        active = (
            await db.execute(
                select(Auction).where(Auction.is_active == True)
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
