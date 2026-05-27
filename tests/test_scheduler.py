"""Event-driven auction scheduler.

Direct tests against ``app.services.auction_scheduler`` - bypass the
HTTP layer so we can craft auctions with sub-minute ``end_time`` (the
public API enforces ``duration_minutes >= 1``).
"""

import asyncio
import time
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Union

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
    raced with this tick) it must exit without settling - otherwise an
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


async def test_complete_auction_isolates_notification_failures(
    client, registered_user, second_user, monkeypatch
):
    """Per-channel dispatch failures inside ``notify_many`` are best-effort
    once the financial state has been committed. A raise from any single
    recipient (WS send error, outbox enqueue failure) must not abort the
    rest of the fan-out and must not propagate up to _wait_and_complete -
    the money has already moved, retrying complete_auction would not undo
    it and would re-emit ``auction_ended`` to subscribers."""
    from datetime import timedelta

    from app.models import Bid, User
    from app.services import notifications as notifications_service
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

    boom_calls = {"n": 0}

    async def boom(*args, **kwargs):
        boom_calls["n"] += 1
        raise RuntimeError("email enqueue failed")

    # Patch the email seam reachable from notify_many's per-recipient
    # dispatcher. Every pending notification routes through this helper
    # when the recipient hasn't muted the channel; a raise simulates a
    # transient outbox/SMTP outage mid fan-out.
    monkeypatch.setattr(notifications_service, "_fire_and_forget_email", boom)

    # Must NOT raise. notify_many isolates per-recipient failures and
    # logs them; the financial commit is already durable on disk.
    async with _db_module.SessionLocal() as db:
        await complete_auction(auction.id, db)

    # Every channel dispatch attempt that hit the email branch raised -
    # both the bidder (AUCTION_LOST loser body) and the seller
    # (AUCTION_SOLD) have email channels enabled by default.
    assert boom_calls["n"] >= 1

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
        # Seller is credited gross (+250) then debited 7% commission
        # (-17.50) in the same transaction - both moves committed
        # before the notification raise, so the net is the post-fee
        # 1000 + 250 - 17.50 = 1232.50.
        assert seller.balance == 1232.50


def test_build_completion_notifications_handles_missing_winner(
    registered_user, second_user
):
    """The settle path's lock_users_by_id may return no entry for
    ``last_bid.user_id`` if FK behaviour ever permits a deleted winner
    (or if a deploy reshuffles ON DELETE semantics). The type signature
    declares ``winner: User | None`` and the loser-body must render
    cleanly without raising AttributeError - otherwise the whole loop
    aborts mid-iteration and rolls back the financial commit, stranding
    the lot."""
    from app.models import Bid, NotificationType, User
    from app.services.auctions import _build_completion_notifications

    bidder = User(id=second_user["user"]["id"], username="loser")
    last_bid = Bid(user_id=999, amount=250, auction_id=1)
    seller = User(id=registered_user["user"]["id"], username="seller")

    pending = _build_completion_notifications(
        auction=Auction(id=1, title="lot"),
        last_bid=last_bid,
        winner=None,
        creator=seller,
        bidders=[bidder],
    )

    # Loser body still rendered with a fallback label - the exact crash
    # condition (winner.username on None) no longer fires.
    loser_entry = next(p for p in pending if p[1] is NotificationType.AUCTION_LOST)
    assert "Победитель" in loser_entry[3]
    # Sanity: the AUCTION_SOLD entry for the seller still goes through.
    assert any(p[1] is NotificationType.AUCTION_SOLD for p in pending)


async def test_extended_during_tick_keeps_new_task_tracked(registered_user):
    """When _wait_and_complete wakes and sees the lot was extended, it
    calls schedule_auction itself to re-arm the tick. The original task
    then exits via its finally clause - which must NOT pop the dict
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
