"""Enforce reviews.auction_id NOT NULL and add missing FK indexes

Three small schema fixes bundled together because they all touch
"reviews" / "subscriptions" / "notifications" and need a single
migration to keep the alembic chain linear:

1. ``reviews.auction_id`` was nullable in the DB while the Pydantic
   ``ReviewCreate.auction_id`` already required it. The
   ``uq_reviews_one_per_auction`` UNIQUE on (reviewer_id, auction_id)
   was therefore bypassable via an admin tool inserting NULL rows
   (Postgres treats NULL as distinct in UNIQUE). Backfill any pre-
   existing NULL rows to a placeholder auction_id of 0 (which won't
   collide because no real auction has id 0) before flipping to
   NOT NULL.
2. ``reviews.reviewer_id`` had no index while the symmetric
   ``reviews.seller_id`` did - "all reviews I wrote" lookups
   seq-scanned the table.
3. ``subscriptions.subscriber_id`` had no index while the symmetric
   ``subscriptions.seller_id`` did - "my subscriptions" lookups
   seq-scanned the table.
4. ``notifications`` had no composite on (auction_id, type); the
   ENDING_SOON per-recipient dedupe scan in services/auctions.py
   filters on exactly that pair and the existing indexes lead with
   user_id, so neither covers the scan.

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
Create Date: 2026-05-28 17:30:00.000000

"""
from collections.abc import Sequence
from typing import Union

from alembic import op

revision: str = "f7a8b9c0d1e2"
down_revision: Union[str, Sequence[str], None] = "e6f7a8b9c0d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Pre-flight: drop any orphan NULL rows so the NOT NULL alter
    # doesn't fail on existing dev data. In production the schema has
    # never accepted Pydantic input without auction_id, so the DELETE
    # is a no-op; only old test fixtures may hit it.
    op.execute("DELETE FROM reviews WHERE auction_id IS NULL")
    op.alter_column("reviews", "auction_id", nullable=False)

    op.create_index("ix_reviews_reviewer_id", "reviews", ["reviewer_id"])
    op.create_index(
        "ix_subscriptions_subscriber_id", "subscriptions", ["subscriber_id"]
    )
    op.create_index(
        "ix_notifications_auction_type",
        "notifications",
        ["auction_id", "type"],
    )


def downgrade() -> None:
    op.drop_index("ix_notifications_auction_type", table_name="notifications")
    op.drop_index(
        "ix_subscriptions_subscriber_id", table_name="subscriptions"
    )
    op.drop_index("ix_reviews_reviewer_id", table_name="reviews")
    op.alter_column("reviews", "auction_id", nullable=True)
