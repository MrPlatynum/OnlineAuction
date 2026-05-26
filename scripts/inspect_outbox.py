"""Inspect and recover dead-lettered email outbox rows.

Run from project root:

    # list failed rows (most recent first, default 50)
    python -m scripts.inspect_outbox list

    # reset one row back to pending so the worker tries it again
    python -m scripts.inspect_outbox retry <outbox_id>

    # reset every failed row to pending (use after fixing the SMTP outage)
    python -m scripts.inspect_outbox retry --all

Without an admin UI this is how ops gets visibility into outbox
dead-letters: ``logger.error(event=outbox_dead_letter, ...)`` fires
when a row hits ``status='failed'`` (#47 max_attempts), and this
script is the corresponding recovery handle.
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy import select, update

from app.database import SessionLocal
from app.models import EmailOutbox
from app.utils.time import utcnow


async def _list(limit: int) -> int:
    async with SessionLocal() as db:
        rows = (
            await db.execute(
                select(EmailOutbox)
                .where(EmailOutbox.status == "failed")
                .order_by(EmailOutbox.created_at.desc())
                .limit(limit)
            )
        ).scalars().all()
    if not rows:
        print("No dead-lettered rows.")
        return 0
    print(f"{'ID':>6}  {'CREATED':<19}  {'ATTEMPTS':>3}  {'TO':<30}  SUBJECT")
    for r in rows:
        ts = r.created_at.strftime("%Y-%m-%d %H:%M:%S") if r.created_at else "-"
        print(f"{r.id:>6}  {ts:<19}  {r.attempts:>3}  {r.to_email:<30}  {r.subject[:60]}")
        if r.last_error:
            print(f"        last error: {r.last_error[:120]}")
    return 0


async def _retry_one(outbox_id: int) -> int:
    async with SessionLocal() as db:
        row = (
            await db.execute(
                select(EmailOutbox).where(EmailOutbox.id == outbox_id)
            )
        ).scalar_one_or_none()
        if row is None:
            print(f"No row with id={outbox_id}", file=sys.stderr)
            return 1
        if row.status != "failed":
            print(
                f"Row {outbox_id} status is {row.status!r}, not 'failed' - "
                f"not retrying (already done or in flight).",
                file=sys.stderr,
            )
            return 1
        row.status = "pending"
        row.attempts = 0
        row.last_error = None
        row.next_attempt_at = utcnow()
        await db.commit()
    print(f"Row {outbox_id} reset to pending.")
    return 0


async def _retry_all() -> int:
    async with SessionLocal() as db:
        # ORM-level UPDATE so we don't load every row into memory just to
        # change four columns. Same semantics as _retry_one applied to all.
        result = await db.execute(
            update(EmailOutbox)
            .where(EmailOutbox.status == "failed")
            .values(
                status="pending",
                attempts=0,
                last_error=None,
                next_attempt_at=utcnow(),
            )
        )
        await db.commit()
    print(f"Reset {result.rowcount} failed rows to pending.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="List dead-lettered rows.")
    p_list.add_argument("--limit", type=int, default=50)

    p_retry = sub.add_parser("retry", help="Reset failed row(s) to pending.")
    g = p_retry.add_mutually_exclusive_group(required=True)
    g.add_argument("outbox_id", nargs="?", type=int)
    g.add_argument("--all", action="store_true", help="Retry every failed row.")

    args = parser.parse_args()

    if args.cmd == "list":
        return asyncio.run(_list(args.limit))
    if args.cmd == "retry":
        if args.all:
            return asyncio.run(_retry_all())
        return asyncio.run(_retry_one(args.outbox_id))
    return 1


if __name__ == "__main__":
    sys.exit(main())
