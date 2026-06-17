"""Synchronous Flask + gunicorn baseline of GET /api/auctions.

Mirrors the SQL workload of app/routers/auctions.py::get_auctions: same
SQLAlchemy ORM model, same per-page query, same eager loads, same
aggregate bid-count query. Only difference - sync engine on psycopg2
and a Flask handler instead of FastAPI.

Used to put a measured number against the async stack instead of the
inferred «10 gunicorn workers» of раздела 5.6.

Run::

    DATABASE_URL=postgresql+asyncpg://... \\
        .venv/bin/gunicorn -w 1 -b 127.0.0.1:8001 \\
        benchmarks.sync_baseline:app
"""
from __future__ import annotations

import os

from flask import Flask, jsonify
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import scoped_session, selectinload, sessionmaker

from app.models import Auction, Bid

_RAW_URL = os.environ["DATABASE_URL"]
SYNC_URL = (
    _RAW_URL.replace("+asyncpg", "+psycopg2")
    if "+asyncpg" in _RAW_URL
    else _RAW_URL.replace("postgresql://", "postgresql+psycopg2://")
)

# One engine per gunicorn worker - pool size matches the FastAPI default
# (10 + 20 overflow). The benchmark uses 100 concurrent clients across
# N workers, so per-worker effective concurrency stays well inside the
# pool envelope.
engine = create_engine(SYNC_URL, pool_size=10, max_overflow=20, future=True)
SessionLocal = scoped_session(sessionmaker(bind=engine, autoflush=False, future=True))

app = Flask(__name__)


@app.teardown_appcontext
def _remove_session(exception=None):  # noqa: ARG001
    SessionLocal.remove()


@app.get("/api/auctions")
def list_auctions():
    db = SessionLocal()
    query = select(Auction).where(Auction.is_active.is_(True))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    auctions = (
        db.execute(
            query
            .order_by(Auction.end_time.asc())
            .options(
                selectinload(Auction.creator),
                selectinload(Auction.category),
                selectinload(Auction.images),
            )
            .limit(12)
        )
        .scalars()
        .all()
    )
    auction_ids = [a.id for a in auctions]
    bid_counts: dict[int, int] = {}
    if auction_ids:
        rows = (
            db.execute(
                select(Bid.auction_id, func.count(Bid.id))
                .where(Bid.auction_id.in_(auction_ids))
                .group_by(Bid.auction_id)
            )
        ).all()
        bid_counts = {aid: cnt for aid, cnt in rows}

    items = []
    for a in auctions:
        items.append({
            "id": a.id,
            "title": a.title,
            "current_price": str(a.current_price),
            "starting_price": str(a.starting_price),
            "image_url": a.image_url,
            "start_time": a.start_time.isoformat() if a.start_time else None,
            "end_time": a.end_time.isoformat() if a.end_time else None,
            "is_active": a.is_active,
            "is_completed": a.is_completed,
            "auction_type": a.auction_type,
            "bin_price": str(a.bin_price) if a.bin_price is not None else None,
            "bid_count": bid_counts.get(a.id, 0),
            "creator": {"id": a.creator.id, "username": a.creator.username} if a.creator else None,
            "category": {"id": a.category.id, "slug": a.category.slug,
                         "name": a.category.name} if a.category else None,
            "images": [{"url": img.url} for img in a.images],
        })
    return jsonify({
        "items": items,
        "total": total,
        "page": 1,
        "page_size": 12,
        "total_pages": (total + 11) // 12,
    })


@app.get("/healthz")
def healthz():
    return "ok"
