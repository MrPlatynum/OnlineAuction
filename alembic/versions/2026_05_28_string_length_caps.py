"""Cap unbounded String columns at sane lengths

PostgreSQL accepts unbounded ``VARCHAR`` and ``TEXT``, but the
absence of any cap means the only ceiling on a column populated by
server-side code is whatever the Pydantic input schema enforces -
and several columns are written from server-generated code paths
that have no Pydantic gate at all (Notification.title /
auction_title snapshot, Transaction.description, EmailOutbox.subject
built from email templates). A buggy template or admin SQL could
silently write multi-MB rows.

This migration adds explicit length caps to every server-touchable
String column. Sizes were chosen to comfortably exceed any value the
current code paths can produce while still bounding the worst case:

- username 64, email 320 (RFC 5321), hashed_password 255, avatar_url 500
- auction.title 300 (matches AuctionCreate Pydantic cap), image_url 2000
- auction.auction_type 10, auction_images.url 2000
- category.name 100, category.slug 100, category.icon 20
- email_outbox.to_email 320, subject 500, status 20
- notification.type 50, title 500, auction_title 500
- transaction.type 50, description 500

All values already in production data fit easily under these caps,
so the ALTER COLUMN TYPE statements run without truncation. The
downgrade reverts to unbounded String.

Revision ID: b9c0d1e2f3a4
Revises: a8b9c0d1e2f3
Create Date: 2026-05-28 20:30:00.000000

"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "b9c0d1e2f3a4"
down_revision: Union[str, Sequence[str], None] = "a8b9c0d1e2f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (table, column, length) - explicit so the up/down stay symmetric
# and a reviewer can read off every change in one place.
_CAPS = [
    ("users", "username", 64),
    ("users", "email", 320),
    ("users", "hashed_password", 255),
    ("users", "avatar_url", 500),
    ("auctions", "title", 300),
    ("auctions", "image_url", 2000),
    ("auctions", "auction_type", 10),
    ("auction_images", "url", 2000),
    ("categories", "name", 100),
    ("categories", "slug", 100),
    ("categories", "icon", 20),
    ("email_outbox", "to_email", 320),
    ("email_outbox", "subject", 500),
    ("email_outbox", "status", 20),
    ("notifications", "type", 50),
    ("notifications", "title", 500),
    ("notifications", "auction_title", 500),
    ("transactions", "type", 50),
    ("transactions", "description", 500),
]


def upgrade() -> None:
    for table, column, length in _CAPS:
        op.alter_column(
            table,
            column,
            existing_type=sa.String(),
            type_=sa.String(length=length),
            existing_nullable=None,
        )


def downgrade() -> None:
    for table, column, _length in _CAPS:
        op.alter_column(
            table,
            column,
            existing_type=sa.String(),
            type_=sa.String(),
            existing_nullable=None,
        )
