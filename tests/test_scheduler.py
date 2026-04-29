"""Event-driven auction scheduler.

Direct tests against ``app.services.auction_scheduler`` — bypass the
HTTP layer so we can craft auctions with sub-minute ``end_time`` (the
public API enforces ``duration_minutes >= 1``).
"""

import asyncio
from datetime import timedelta

from sqlalchemy import select

from app import database as _db_module
from app.models import Auction
from app.services.auction_scheduler import (
    _completion_tasks,
    cancel_auction,
    schedule_auction,
)
from app.utils.time import utcnow


async def _seed_auction(creator_id: int, end_in_seconds: float) -> Auction:
    async with _db_module.SessionLocal() as db:
        now = utcnow()
        auction = Auction(
            title="Scheduler test lot",
            description="...",
            starting_price=100,
            current_price=100,
            start_time=now,
            end_time=now + timedelta(seconds=end_in_seconds),
            created_by=creator_id,
            auction_type="bid",
        )
        db.add(auction)
        await db.commit()
        await db.refresh(auction)
        return auction


async def test_schedule_registers_task(registered_user):
    auction = await _seed_auction(registered_user["user"]["id"], end_in_seconds=300)
    try:
        schedule_auction(auction)
        assert auction.id in _completion_tasks
    finally:
        cancel_auction(auction.id)


async def test_cancel_removes_task(registered_user):
    auction = await _seed_auction(registered_user["user"]["id"], end_in_seconds=300)
    schedule_auction(auction)
    cancel_auction(auction.id)
    assert auction.id not in _completion_tasks


async def test_reschedule_replaces_existing_task(registered_user):
    auction = await _seed_auction(registered_user["user"]["id"], end_in_seconds=300)
    try:
        schedule_auction(auction)
        first = _completion_tasks[auction.id]
        schedule_auction(auction)
        second = _completion_tasks[auction.id]
        # Yield once so the cancellation requested by the second
        # ``schedule_auction`` actually propagates into ``first``.
        await asyncio.sleep(0)
        assert first is not second
        assert first.cancelled() or first.done()
    finally:
        cancel_auction(auction.id)


async def test_auction_completes_when_end_time_passes(registered_user):
    """End-to-end: schedule an auction ending in ~0.3s, wait, verify the
    DB row was settled by the scheduler with no polling involved."""
    auction = await _seed_auction(registered_user["user"]["id"], end_in_seconds=0.3)
    schedule_auction(auction)
    await asyncio.sleep(0.8)

    async with _db_module.SessionLocal() as db:
        refreshed = (
            await db.execute(select(Auction).where(Auction.id == auction.id))
        ).scalar_one()
        assert refreshed.is_active is False
        assert refreshed.is_completed is True
