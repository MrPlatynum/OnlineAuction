"""Postgres-advisory-lock based leader election for the auction scheduler.

The auction scheduler (`app/services/auction_scheduler.py`) keeps a
pair of ``asyncio.Task`` per active lot and is single-process by
design — state lives in module dicts. Running it under
``uvicorn --workers N`` would arm N copies of every timer; the
existing row-lock + ``is_active`` guard in ``complete_auction`` keeps
that *correct* (only one worker actually settles each lot), but it's
wasteful and leaks resources.

This module makes the scheduler **at most once per cluster**. On
startup every worker calls ``try_become_scheduler_leader``; whoever
grabs ``pg_try_advisory_lock`` on a dedicated connection becomes the
leader and runs the scheduler. The other workers skip
``schedule_active_auctions`` entirely and serve HTTP/WS traffic only.

Why advisory locks instead of:
- a separate scheduler process: doubles operational surface for a
  single-machine deployment and re-introduces the "what if it dies"
  question we're trying to solve.
- ZooKeeper / etcd: heavy dependency for one lock; Postgres is
  already in the dependency graph and natively offers the primitive.
- Row-level lock on a sentinel row: works too but advisory locks
  don't require an actual table and live for the connection's
  lifetime without any transaction discipline.

Lifecycle:
- Leader connection is opened explicitly via ``engine.connect()``
  (not pooled), the lock is taken, and the connection sits idle
  for the lifetime of the worker. Postgres releases the lock when
  the backend disconnects, so a SIGKILL'd leader frees the lock
  automatically — the next worker restart can claim it.
- Graceful shutdown closes the connection explicitly.

Heartbeat (#M3):
- Every worker runs a background task (``_heartbeat_loop``) that
  pings the leader connection with ``SELECT 1`` so managed Postgres
  doesn't idle-disconnect under us (the lock is connection-scoped;
  a dropped backend silently releases it).
- If the leader process loses its connection / lock, the heartbeat
  also acts as a step-down detector for that worker.
- Follower workers use the same loop to retry ``pg_try_advisory_lock``;
  when the previous leader dies, the next-fastest follower promotes
  itself and arms ``schedule_active_auctions``. Without this, a dead
  leader would silently freeze the scheduler until manual restart.
"""

import asyncio
import logging
import os
from collections.abc import Awaitable, Callable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app import database as _db_module

logger = logging.getLogger(__name__)

# Hand-picked 64-bit integer — picked once, hard-coded forever so
# every replica probes the same slot. ``pg_advisory_lock`` takes
# ``bigint``; this fits.
SCHEDULER_LOCK_KEY: int = 0x4C_4F_54_55_53_53_43_48  # "LOTUSSCH"

_leader_connection: AsyncConnection | None = None


def _election_enabled() -> bool:
    """Tests and single-worker dev set this to ``false`` so every
    process just acts as the leader without touching the lock. The
    election code paths themselves still have to be tested — those
    tests flip the env var back on around the call."""
    return os.getenv("AUCTION_SCHEDULER_ELECTION_ENABLED", "true").lower() not in {
        "false", "0", "no", "off",
    }


def is_leader() -> bool:
    """``True`` when the current worker holds the lock (or when the
    election is bypassed via env)."""
    return not _election_enabled() or _leader_connection is not None


async def try_become_scheduler_leader() -> bool:
    """Try to claim the scheduler leader lock.

    Behaviour:
    - ``AUCTION_SCHEDULER_ELECTION_ENABLED=false`` → return True
      without touching the DB (tests and single-worker dev).
    - Already a leader in this process → return True idempotently.
    - Otherwise open a dedicated ``AsyncConnection``, call
      ``pg_try_advisory_lock``. On success keep the connection
      alive in module state so the lock persists; on failure close
      the connection cleanly and return False.

    A True return means the caller should run scheduler-only
    bootstrap (``schedule_active_auctions``); a False return means
    this worker is a follower and must skip it.
    """
    global _leader_connection
    if not _election_enabled():
        return True
    if _leader_connection is not None:
        return True

    conn = await _db_module.engine.connect()
    try:
        result = await conn.execute(
            text("SELECT pg_try_advisory_lock(:key)"),
            {"key": SCHEDULER_LOCK_KEY},
        )
        got = bool(result.scalar_one())
    except Exception:
        logger.exception("scheduler leader election: query failed")
        await conn.close()
        return False

    if not got:
        await conn.close()
        logger.info(
            "scheduler leader is held by another worker — "
            "this process will serve traffic only"
        )
        return False

    _leader_connection = conn
    logger.info(
        "scheduler leader acquired (lock key 0x%x)", SCHEDULER_LOCK_KEY
    )
    return True


async def release_scheduler_lock() -> None:
    """Close the leader connection on graceful shutdown — Postgres
    releases the advisory lock when the backend disconnects, so the
    next worker can claim it. Safe to call on a follower (no-op)."""
    global _leader_connection
    conn = _leader_connection
    _leader_connection = None
    if conn is None:
        return
    try:
        await conn.close()
        logger.info("scheduler leader released")
    except Exception:
        logger.exception("scheduler leader: error closing leader connection")


async def _force_release_for_tests() -> None:
    """Tests that exercise the election repeatedly need a way to
    drop the lock without depending on the env override. Kept under
    a name that flags it as test-only."""
    await release_scheduler_lock()


# --- Heartbeat: keep leader connection alive + retry-to-promote followers ---

# Tick interval. Short enough that a dead leader is replaced within a minute;
# long enough that idle workers don't hammer Postgres. The SELECT 1 ping is
# cheap (no transaction, no lock contention).
HEARTBEAT_INTERVAL_SECONDS = 30

_heartbeat_task: asyncio.Task | None = None
_heartbeat_stop: asyncio.Event | None = None


async def _ping_leader_connection() -> bool:
    """Run ``SELECT 1`` on the leader connection. Returns True if it
    succeeds (connection alive, lock still held implicitly), False if
    it errors — in which case we step down by closing the connection
    and clearing module state."""
    global _leader_connection
    if _leader_connection is None:
        return False
    try:
        await _leader_connection.execute(text("SELECT 1"))
        return True
    except Exception:
        logger.exception(
            "scheduler leader: heartbeat ping failed; stepping down"
        )
        conn = _leader_connection
        _leader_connection = None
        try:
            await conn.close()
        except Exception:
            pass
        return False


async def _heartbeat_tick(
    on_promote: Callable[[], Awaitable[None]] | None,
) -> bool:
    """One tick of the heartbeat. If we're leader, ping. If we're
    not (or ping just failed), try to become leader. On a fresh
    promotion call ``on_promote`` so the caller can arm the
    scheduler. Returns whether we ended this tick as leader."""
    was_leader = _leader_connection is not None
    if was_leader:
        if await _ping_leader_connection():
            return True
        # Lost the lock — fall through to try-claim path.
    became_leader = await try_become_scheduler_leader()
    if became_leader and not was_leader and on_promote is not None:
        try:
            await on_promote()
            logger.info("scheduler leader: promoted, on_promote ran")
        except Exception:
            logger.exception("scheduler leader: on_promote failed")
    return became_leader


async def _heartbeat_loop(
    stop_event: asyncio.Event,
    on_promote: Callable[[], Awaitable[None]] | None,
) -> None:
    """Run ``_heartbeat_tick`` on a fixed cadence until ``stop_event``
    fires. Errors are logged but don't kill the loop."""
    logger.info("scheduler heartbeat started")
    try:
        while not stop_event.is_set():
            try:
                await _heartbeat_tick(on_promote)
            except Exception:
                logger.exception("scheduler heartbeat: tick failed")
            try:
                await asyncio.wait_for(
                    stop_event.wait(), HEARTBEAT_INTERVAL_SECONDS
                )
            except TimeoutError:
                pass
    finally:
        logger.info("scheduler heartbeat stopped")


def start_scheduler_heartbeat(
    on_promote: Callable[[], Awaitable[None]] | None = None,
) -> None:
    """Start the heartbeat task. No-op if election is disabled (tests)
    or if a task is already running. ``on_promote`` is called once
    per fresh promotion — typically ``schedule_active_auctions``."""
    global _heartbeat_task, _heartbeat_stop
    if not _election_enabled():
        return
    if _heartbeat_task is not None and not _heartbeat_task.done():
        return
    _heartbeat_stop = asyncio.Event()
    _heartbeat_task = asyncio.create_task(
        _heartbeat_loop(_heartbeat_stop, on_promote),
        name="scheduler-heartbeat",
    )


async def stop_scheduler_heartbeat() -> None:
    """Signal the heartbeat to stop and await its exit. Called from
    the FastAPI lifespan ``finally`` before ``release_scheduler_lock``
    so the ping loop doesn't see a half-closed connection."""
    global _heartbeat_task, _heartbeat_stop
    if _heartbeat_stop is not None:
        _heartbeat_stop.set()
    if _heartbeat_task is not None:
        try:
            await asyncio.wait_for(_heartbeat_task, timeout=5)
        except (TimeoutError, asyncio.CancelledError):
            _heartbeat_task.cancel()
    _heartbeat_task = None
    _heartbeat_stop = None
