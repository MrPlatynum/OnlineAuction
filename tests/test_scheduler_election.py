"""Scheduler leader election via Postgres advisory lock.

Conftest disables election by default (`AUCTION_SCHEDULER_ELECTION_ENABLED=false`)
so the rest of the suite gets the scheduler unconditionally. This
file flips the flag on around the calls that actually exercise the
election, then releases the lock at teardown so subsequent tests
don't inherit a held lock.
"""

import pytest_asyncio
from sqlalchemy import text

from app import database as _db_module
from app.services import scheduler_election


@pytest_asyncio.fixture(autouse=True)
async def _enable_election_and_release(monkeypatch):
    """Turn the election on for the duration of one test and ensure
    the lock is released afterwards regardless of how the test exits."""
    monkeypatch.setenv("AUCTION_SCHEDULER_ELECTION_ENABLED", "true")
    yield
    await scheduler_election._force_release_for_tests()


async def test_first_caller_becomes_leader():
    got = await scheduler_election.try_become_scheduler_leader()
    assert got is True
    assert scheduler_election.is_leader() is True


async def test_second_caller_from_same_process_is_idempotent():
    """A worker calling ``try_become_scheduler_leader`` twice keeps
    returning True without re-acquiring — the lock is already held."""
    first = await scheduler_election.try_become_scheduler_leader()
    second = await scheduler_election.try_become_scheduler_leader()
    assert first is True
    assert second is True


async def test_second_concurrent_connection_cannot_acquire():
    """The real multi-worker case: one process holds the lock; a
    second one trying to take the same advisory-lock key gets
    ``false`` from ``pg_try_advisory_lock``. We simulate "second
    process" with a direct DB connection that opens its own
    asyncpg session — the advisory lock is session-scoped so it
    doesn't see the first holder's lock as its own."""
    leader_acquired = await scheduler_election.try_become_scheduler_leader()
    assert leader_acquired is True

    async with _db_module.engine.connect() as rival:
        got = (
            await rival.execute(
                text("SELECT pg_try_advisory_lock(:key)"),
                {"key": scheduler_election.SCHEDULER_LOCK_KEY},
            )
        ).scalar_one()
    assert got is False


async def test_release_frees_lock_for_next_caller():
    """After the leader releases, a rival connection can claim the
    lock — that's how a restarted worker takes over."""
    assert await scheduler_election.try_become_scheduler_leader() is True
    await scheduler_election.release_scheduler_lock()
    assert scheduler_election.is_leader() is False

    async with _db_module.engine.connect() as rival:
        got = (
            await rival.execute(
                text("SELECT pg_try_advisory_lock(:key)"),
                {"key": scheduler_election.SCHEDULER_LOCK_KEY},
            )
        ).scalar_one()
        # Hand it back so the autouse fixture's release is a no-op
        # rather than colliding with the rival's hold.
        await rival.execute(
            text("SELECT pg_advisory_unlock(:key)"),
            {"key": scheduler_election.SCHEDULER_LOCK_KEY},
        )
    assert got is True


async def test_heartbeat_ping_keeps_leader_alive():
    """``_ping_leader_connection`` returns True for a healthy leader,
    keeping the connection alive against managed-PG idle-disconnect."""
    assert await scheduler_election.try_become_scheduler_leader() is True
    assert await scheduler_election._ping_leader_connection() is True
    # Still leader after the ping — connection not torn down.
    assert scheduler_election.is_leader() is True


async def test_heartbeat_steps_down_when_ping_fails():
    """If the leader's connection breaks (e.g., managed PG dropped
    it), the heartbeat ping raises; the worker steps down so the
    next tick can try to claim the lock fresh. We simulate the
    drop by closing the connection out from under the ping."""
    assert await scheduler_election.try_become_scheduler_leader() is True
    # Force-close the underlying connection without going through
    # release_scheduler_lock so _leader_connection stays set —
    # exactly what a server-side disconnect looks like.
    await scheduler_election._leader_connection.close()

    ok = await scheduler_election._ping_leader_connection()
    assert ok is False
    assert scheduler_election._leader_connection is None
    assert scheduler_election.is_leader() is False


async def test_heartbeat_tick_promotes_follower_and_runs_callback():
    """A follower whose tick fires after the previous leader has
    released the lock should promote itself and run ``on_promote``
    exactly once for that transition."""
    # Start as follower — another connection holds the lock.
    async with _db_module.engine.connect() as rival:
        await rival.execute(
            text("SELECT pg_advisory_lock(:key)"),
            {"key": scheduler_election.SCHEDULER_LOCK_KEY},
        )
        follower_attempt = await scheduler_election.try_become_scheduler_leader()
        assert follower_attempt is False

        promote_calls = []

        async def on_promote():
            promote_calls.append(1)

        # While rival still holds the lock the tick stays as follower.
        was_leader = await scheduler_election._heartbeat_tick(on_promote)
        assert was_leader is False
        assert promote_calls == []

        # Drop the rival's lock so the next tick can claim it.
        await rival.execute(
            text("SELECT pg_advisory_unlock(:key)"),
            {"key": scheduler_election.SCHEDULER_LOCK_KEY},
        )

    was_leader = await scheduler_election._heartbeat_tick(on_promote)
    assert was_leader is True
    assert promote_calls == [1]

    # Re-tick: still leader, but no second on_promote call.
    was_leader = await scheduler_election._heartbeat_tick(on_promote)
    assert was_leader is True
    assert promote_calls == [1]


async def test_env_override_skips_election(monkeypatch):
    """Single-worker dev / pytest set ``AUCTION_SCHEDULER_ELECTION_ENABLED=false``;
    the function returns True without touching the DB so the
    caller's scheduler still arms. We assert this by swapping the
    module's engine for a stub that raises on any usage — the call
    must not even try to open a connection."""
    monkeypatch.setenv("AUCTION_SCHEDULER_ELECTION_ENABLED", "false")

    class _ExplodingEngine:
        async def connect(self):
            raise RuntimeError("engine should not be touched when election is off")

    monkeypatch.setattr(_db_module, "engine", _ExplodingEngine())
    got = await scheduler_election.try_become_scheduler_leader()
    assert got is True
    assert scheduler_election.is_leader() is True


async def test_concurrent_election_only_one_wins():
    """Two workers starting at the same time — exactly one wins,
    the other gets False. ``pg_try_advisory_lock`` is atomic so
    the race is decided at the DB; we just want to assert the
    expected outcome from the application's side."""
    # First worker (this process via the module).
    leader_first = await scheduler_election.try_become_scheduler_leader()
    assert leader_first is True

    # Second worker — open a fresh connection, run the same query
    # path the module does. This mirrors what a sibling
    # ``uvicorn --workers 2`` process would observe.
    async def second_worker_attempt() -> bool:
        async with _db_module.engine.connect() as conn:
            got = (
                await conn.execute(
                    text("SELECT pg_try_advisory_lock(:key)"),
                    {"key": scheduler_election.SCHEDULER_LOCK_KEY},
                )
            ).scalar_one()
            return bool(got)

    second = await second_worker_attempt()
    assert second is False

    # Sanity: a third inspection through the module still sees us
    # as leader.
    third = await scheduler_election.try_become_scheduler_leader()
    assert third is True


async def test_query_failure_returns_false_and_closes_connection(monkeypatch):
    """If the lock query raises (network blip, DB down), the
    function must return False *and* close the connection — leaking
    it would burn through the pool."""

    class _BrokenConnection:
        closed = False

        async def execute(self, *_a, **_kw):
            raise RuntimeError("simulated DB outage")

        async def close(self):
            self.closed = True

    broken = _BrokenConnection()

    class _FakeEngine:
        async def connect(self):
            return broken

    monkeypatch.setattr(_db_module, "engine", _FakeEngine())

    got = await scheduler_election.try_become_scheduler_leader()
    assert got is False
    assert broken.closed is True
    assert scheduler_election.is_leader() is False
