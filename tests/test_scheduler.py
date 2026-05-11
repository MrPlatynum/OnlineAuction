"""Event-driven auction scheduler.

Direct tests against ``app.services.auction_scheduler`` — bypass the
HTTP layer so we can craft auctions with sub-minute ``end_time`` (the
public API enforces ``duration_minutes >= 1``).
"""

import asyncio
import time
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Union

import pytest
from sqlalchemy import select

from app import database as _db_module
from app.models import Auction
from app.services.auction_scheduler import (
    _completion_tasks,
    cancel_auction,
    schedule_auction,
)
from app.utils.time import utcnow


async def _wait_until(
    predicate: Callable[[], Union[bool, Awaitable[bool]]],
    *,
    timeout: float = 5.0,
    interval: float = 0.05,
) -> None:
    """Poll ``predicate`` until it returns truthy or timeout elapses.

    Replaces hand-tuned ``asyncio.sleep(N)`` calls that gambled the
    test against the scheduler's tick latency. Under CI load N was
    often too small and the test flaked; under-loaded local runs
    wasted time.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = predicate()
        if asyncio.iscoroutine(result):
            result = await result
        if result:
            return
        await asyncio.sleep(interval)
    raise AssertionError(f"condition not met within {timeout}s")


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
    """End-to-end: schedule an auction ending in ~0.3s, poll until the
    scheduler tick settles the DB row."""
    auction = await _seed_auction(registered_user["user"]["id"], end_in_seconds=0.3)
    schedule_auction(auction)

    async def settled() -> bool:
        async with _db_module.SessionLocal() as db:
            row = (
                await db.execute(select(Auction).where(Auction.id == auction.id))
            ).scalar_one()
            return not row.is_active and row.is_completed

    await _wait_until(settled, timeout=5.0)


async def test_complete_auction_skips_when_end_time_extended(registered_user):
    """complete_auction must re-check end_time after acquiring the row
    lock. If end_time is now in the future (PATCH /auctions extend
    raced with this tick) it must exit without settling — otherwise an
    extended lot would close at the OLD deadline."""
    from app.services.auctions import complete_auction

    auction = await _seed_auction(registered_user["user"]["id"], end_in_seconds=300)
    try:
        async with _db_module.SessionLocal() as db:
            await complete_auction(auction.id, db)
            refreshed = (
                await db.execute(select(Auction).where(Auction.id == auction.id))
            ).scalar_one()
            assert refreshed.is_active is True
            assert refreshed.is_completed is False
    finally:
        cancel_auction(auction.id)


async def test_complete_auction_commits_money_before_notifying(
    client, registered_user, second_user, monkeypatch
):
    """notify_user → create_notification used to commit the session
    mid-completion, so a raise during the second notify left only a
    partial set of notifications. Worse, if the *first* notify raised
    before its own commit the entire financial state (balances,
    transactions, is_completed) was rolled back. After the refactor
    notifications run only after a single final commit — even if every
    one of them blows up, the money has already moved."""
    from datetime import timedelta

    from app.models import Bid, User
    from app.services import auctions as auctions_service
    from app.services.auctions import complete_auction

    auction = await _seed_auction(
        registered_user["user"]["id"], end_in_seconds=300
    )
    async with _db_module.SessionLocal() as db:
        db.add(Bid(amount=250, user_id=second_user["user"]["id"], auction_id=auction.id))
        auc = (await db.execute(select(Auction).where(Auction.id == auction.id))).scalar_one()
        auc.current_price = 250
        auc.end_time = utcnow() - timedelta(seconds=10)
        await db.commit()

    async def boom(*args, **kwargs):
        raise RuntimeError("notification dispatch failed")

    monkeypatch.setattr(auctions_service, "notify_user", boom)

    with pytest.raises(RuntimeError):
        async with _db_module.SessionLocal() as db:
            await complete_auction(auction.id, db)

    async with _db_module.SessionLocal() as db:
        settled = (
            await db.execute(select(Auction).where(Auction.id == auction.id))
        ).scalar_one()
        assert settled.is_active is False
        assert settled.is_completed is True
        assert settled.winner_id == second_user["user"]["id"]

        bidder = (
            await db.execute(select(User).where(User.id == second_user["user"]["id"]))
        ).scalar_one()
        seller = (
            await db.execute(select(User).where(User.id == registered_user["user"]["id"]))
        ).scalar_one()
        assert bidder.balance == 1000 - 250
        assert seller.balance == 1000 + 250


async def test_extended_during_tick_keeps_new_task_tracked(registered_user):
    """When _wait_and_complete wakes and sees the lot was extended, it
    calls schedule_auction itself to re-arm the tick. The original task
    then exits via its finally clause — which must NOT pop the dict
    entry, because schedule_auction has already replaced it with the new
    task. Without the identity check the new task would be orphaned from
    cancel_auction / shutdown."""
    # Short fuse so the original task fires soon after we commit the
    # extension. The DB roundtrip takes single-digit ms, well under the
    # tick deadline.
    auction = await _seed_auction(registered_user["user"]["id"], end_in_seconds=0.5)
    schedule_auction(auction)
    first_task = _completion_tasks[auction.id]

    async with _db_module.SessionLocal() as db:
        auc = (
            await db.execute(select(Auction).where(Auction.id == auction.id))
        ).scalar_one()
        auc.end_time = auc.end_time + timedelta(seconds=300)
        await db.commit()

    def replaced() -> bool:
        current = _completion_tasks.get(auction.id)
        return current is not None and current is not first_task

    await _wait_until(replaced, timeout=5.0)

    new_task = _completion_tasks[auction.id]
    assert new_task is not first_task
    assert not new_task.done()

    cancel_auction(auction.id)
