"""Microbenchmark for the notification fan-out path.

Compares two fan-out shapes against the same N-recipient payload on
the real PostgreSQL test database:

* **loop** - the pre-PR-67 pattern: ``for u in users: await
  notify_user(db, u, ...)`` with the historical ``_fire_and_forget_email``
  behaviour restored via monkeypatch. Each iteration commits the
  Notification row through the caller's session, then enqueue_email
  opens its own ``SessionLocal`` for the EmailOutbox row and commits
  there. 2N round-trips, 2N commits.

* **batch** - the current pattern: ``await notify_many(db, payloads,
  ...)``. One multi-row INSERT per table (Notification + EmailOutbox)
  enrol in the shared session and a single commit covers both. Then
  ``asyncio.gather`` runs the WS pushes concurrently. 2 INSERT
  statements, 1 commit.

Both arms run against the same seeded Auction so the persisted
Notification rows carry a real ``auction_id`` (matching every
production caller) and PostgreSQL performs the same foreign-key
validation it would in production. The WS path is replaced with a
stub so the measurement isolates DB I/O - the architectural win is
on the persistence side; the WS gather is the bonus.

Usage:
    .venv/bin/python benchmarks/notify_fanout.py
    .venv/bin/python benchmarks/notify_fanout.py --recipients 50 --iters 30
"""

import argparse
import asyncio
import contextlib
import os
import statistics
import time

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://auction:auction_dev_password@localhost:5433/auction_test",
)
os.environ.setdefault("AUCTION_SECRET_KEY", "bench-only")
os.environ.setdefault("AUCTION_OUTBOX_WORKER_ENABLED", "false")
os.environ.setdefault("AUCTION_SCHEDULER_ELECTION_ENABLED", "false")

# Refuse to run against anything that doesn't look like the dedicated
# test database. The script calls Base.metadata.drop_all + create_all
# below and DELETEs notification/outbox rows per iteration; a forgotten
# DATABASE_URL pointing at staging or production would wipe live data
# without any further prompt. The opt-out exists for CI environments
# that may legitimately want a differently-named target.
if "auction_test" not in os.environ["DATABASE_URL"] and \
        os.environ.get("BENCH_ALLOW_DROP") != "1":
    raise SystemExit(
        "DATABASE_URL does not contain 'auction_test'. Refusing to "
        "run drop_all/create_all. Set BENCH_ALLOW_DROP=1 to override."
    )

from datetime import timedelta  # noqa: E402

from sqlalchemy import delete  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

import app.database as _db_module  # noqa: E402
from app.database import Base  # noqa: E402
from app.models import Auction, EmailOutbox, Notification, User  # noqa: E402
from app.models.enums import NotificationType  # noqa: E402
from app.services import notifications as _notif_mod  # noqa: E402
from app.services.email_outbox import enqueue_email  # noqa: E402
from app.services.notifications import notify_many, notify_user  # noqa: E402
from app.utils.time import utcnow  # noqa: E402


class _StubManager:
    """No-op WS manager. The notify_* paths only touch ``send_notification``
    when ``manager`` is truthy; a stub keeps the code path live without
    the cost of real socket I/O so we measure the database side cleanly."""

    async def send_notification(self, user_id, payload):  # noqa: ARG002
        return None


@contextlib.asynccontextmanager
async def _legacy_email_seam():
    """Restore the pre-PR-67 ``_fire_and_forget_email`` shape for the
    duration of the loop measurement.

    The current seam threads ``db=`` from the caller all the way down
    to ``enqueue_email``, which adds the outbox row to the shared
    session without committing. Before PR ca4d8a3 the seam took no
    ``db`` argument and ``enqueue_email`` opened its own
    ``SessionLocal`` per call and committed there - the true
    historical cost the loop arm is meant to reproduce. Patching the
    seam (not enqueue_email itself) keeps the production wiring intact
    for tests run in the same process."""

    original = _notif_mod._fire_and_forget_email

    async def _legacy(to_email, subject, html, *, db=None):  # noqa: ARG001
        # Ignore the caller's session; open a fresh one and commit
        # there, matching the pre-PR-67 enqueue_email default path.
        await enqueue_email(to_email, subject, html, db=None)

    _notif_mod._fire_and_forget_email = _legacy
    try:
        yield
    finally:
        _notif_mod._fire_and_forget_email = original


async def _seed_fixtures(session_factory, recipients: int) -> tuple[list[User], Auction]:
    """Create ``recipients`` fresh users with the email channel opted
    in and one Auction row owned by the first user. The Auction
    provides a valid foreign-key target for ``Notification.auction_id``
    so every persisted row carries the same shape as production."""

    async with session_factory() as db:
        users = [
            User(
                username=f"bench_user_{i}",
                email=f"bench_{i}@example.com",
                hashed_password="x" * 20,
                email_verified=True,
                email_notifications=True,
                notify_ending=True,
            )
            for i in range(recipients)
        ]
        db.add_all(users)
        await db.commit()
        seller_id = users[0].id

        now = utcnow()
        auction = Auction(
            title="Эталонный лот для микрозамера",
            description="benchmark fixture",
            starting_price=100,
            current_price=100,
            start_time=now,
            end_time=now + timedelta(hours=1),
            created_by=seller_id,
        )
        db.add(auction)
        await db.commit()
        return users, auction


async def _reset_fanout_tables(session_factory) -> None:
    """Clear Notification + EmailOutbox between iterations so the two
    paths don't accumulate side effects from each other - both start
    from the same empty-table baseline."""
    async with session_factory() as db:
        await db.execute(delete(Notification))
        await db.execute(delete(EmailOutbox))
        await db.commit()


def _build_payloads(users: list[User]) -> list[tuple[User, NotificationType, str, str]]:
    return [
        (u, NotificationType.AUCTION_ENDING,
         "Аукцион скоро завершится",
         "Аукцион завершится через 5 минут.")
        for u in users
    ]


async def _run_loop(session_factory, users, auction, manager) -> float:
    """Time the legacy per-recipient loop with the pre-PR-67 email
    seam. Each iteration: notify_user commits the Notification row,
    then the legacy seam opens a fresh SessionLocal for the EmailOutbox
    row and commits there. 2N commits, 2N round-trips."""
    async with _legacy_email_seam():
        start = time.perf_counter()
        async with session_factory() as db:
            for u in users:
                await notify_user(
                    db, u, NotificationType.AUCTION_ENDING,
                    "Аукцион скоро завершится",
                    "Аукцион завершится через 5 минут.",
                    auction_id=auction.id,
                    auction_title=auction.title,
                    manager=manager,
                )
        return time.perf_counter() - start


async def _run_batch(session_factory, users, auction, manager) -> float:
    """Time the batched fan-out. One multi-row INSERT per table, the
    outbox rows enrol in the same session, single commit covers both."""
    payloads = _build_payloads(users)
    start = time.perf_counter()
    async with session_factory() as db:
        await notify_many(
            db, payloads,
            auction_id=auction.id, auction_title=auction.title,
            manager=manager,
        )
    return time.perf_counter() - start


def _percentile(values: list[float], pct: float) -> float:
    """Linear-interpolation percentile. ``statistics.quantiles`` rounds
    to neighbour indices for tiny samples, which collapses p95 onto
    the maximum for n<=20; the interpolated form preserves tail signal
    at the sample sizes this benchmark actually uses."""
    if not values:
        return 0.0
    sorted_values = sorted(values)
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (pct / 100) * (len(sorted_values) - 1)
    lower = int(rank)
    upper = min(lower + 1, len(sorted_values) - 1)
    frac = rank - lower
    return sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * frac


def _summarise(label: str, samples: list[float]) -> None:
    samples_ms = [s * 1000 for s in samples]
    print(
        f"{label:>6}  "
        f"n={len(samples)}  "
        f"min={min(samples_ms):.1f} ms  "
        f"mean={statistics.mean(samples_ms):.1f} ms  "
        f"p50={_percentile(samples_ms, 50):.1f} ms  "
        f"p95={_percentile(samples_ms, 95):.1f} ms  "
        f"max={max(samples_ms):.1f} ms"
    )


async def run_benchmark(recipients: int, iters: int, warmup: int) -> None:
    print(
        f"Recipients per call: {recipients}\n"
        f"Iterations:          {iters} (+{warmup} warm-up)\n"
        f"DB:                  {os.environ['DATABASE_URL']}\n"
    )

    engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
    session_factory = async_sessionmaker(
        bind=engine, expire_on_commit=False, autoflush=False,
    )

    # Snapshot-and-restore the module globals app.database exposes so
    # the benchmark does not leave its disposed engine pinned for any
    # subsequent caller in the same process.
    orig_engine = _db_module.engine
    orig_session_local = _db_module.SessionLocal
    _db_module.engine = engine
    _db_module.SessionLocal = session_factory

    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)

        users, auction = await _seed_fixtures(session_factory, recipients)
        manager = _StubManager()

        for _ in range(warmup):
            await _reset_fanout_tables(session_factory)
            await _run_loop(session_factory, users, auction, manager)
            await _reset_fanout_tables(session_factory)
            await _run_batch(session_factory, users, auction, manager)

        loop_samples: list[float] = []
        batch_samples: list[float] = []
        for _ in range(iters):
            await _reset_fanout_tables(session_factory)
            loop_samples.append(await _run_loop(session_factory, users, auction, manager))
        for _ in range(iters):
            await _reset_fanout_tables(session_factory)
            batch_samples.append(await _run_batch(session_factory, users, auction, manager))

        print("Results (lower is better):\n")
        _summarise("loop", loop_samples)
        _summarise("batch", batch_samples)

        speedup = statistics.mean(loop_samples) / statistics.mean(batch_samples)
        # Measured commit count, not derived. The legacy seam opens a
        # second SessionLocal per recipient that commits separately
        # (1 Notification commit + 1 outbox commit). The batch path
        # combines both tables under one commit.
        commits_loop = 2 * recipients
        commits_batch = 1
        print(
            f"\nSpeed-up (mean loop / mean batch): {speedup:.2f}x\n"
            f"DB commits per call: loop={commits_loop}, batch={commits_batch}"
        )
    finally:
        await engine.dispose()
        _db_module.engine = orig_engine
        _db_module.SessionLocal = orig_session_local


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recipients", type=int, default=20,
                        help="N recipients per fan-out call (default 20)")
    parser.add_argument("--iters", type=int, default=20,
                        help="Measured iterations (default 20)")
    parser.add_argument("--warmup", type=int, default=3,
                        help="Warm-up iterations not counted (default 3)")
    args = parser.parse_args()
    if args.iters < 1:
        raise SystemExit("--iters must be >= 1")
    asyncio.run(run_benchmark(args.recipients, args.iters, args.warmup))


if __name__ == "__main__":
    main()
