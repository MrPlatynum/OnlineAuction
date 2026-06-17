"""Switch every DateTime column to TIMESTAMP WITH TIME ZONE

Every model used to declare ``Column(DateTime, ...)`` (naive), and
``utcnow()`` returned ``datetime.now(UTC).replace(tzinfo=None)`` to
match. The stored value was correct UTC, but Pydantic serialised the
naive datetime to an ISO string without a ``+00:00`` (or ``Z``)
suffix. A JS client in MSK doing ``new Date(isoString)`` then
interpreted the string as MSK-local time and rendered every
countdown three hours off.

This migration is the long fix: every DateTime column becomes
``DateTime(timezone=True)``, ``utcnow()`` returns a tz-aware UTC
datetime, and Pydantic serialises tz-aware datetimes with the
``+00:00`` suffix by default - the JS client now parses them as
UTC and the countdown matches the server's wall clock regardless
of the browser's time zone.

The ALTER COLUMN TYPE statements use ``USING <col> AT TIME ZONE
'UTC'`` so existing naive timestamps are reinterpreted as UTC
(which is what they always were) instead of as the server's local
zone. No data is moved or lost; the in-storage instant stays the
same.

Revision ID: d1e2f3a4b5c6
Revises: c0d1e2f3a4b5
Create Date: 2026-05-28 21:45:00.000000

"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "d1e2f3a4b5c6"
down_revision: Union[str, Sequence[str], None] = "c0d1e2f3a4b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (table, column) - every datetime in the schema
_DT_COLUMNS = [
    ("auctions", "start_time"),
    ("auctions", "end_time"),
    ("bids", "timestamp"),
    ("email_outbox", "next_attempt_at"),
    ("email_outbox", "created_at"),
    ("email_outbox", "sent_at"),
    ("notifications", "created_at"),
    ("subscriptions", "created_at"),
    ("users", "password_reset_sent_at"),
    ("users", "locked_until"),
    ("users", "upload_window_start"),
    ("users", "created_at"),
    ("reviews", "created_at"),
    ("transactions", "created_at"),
]


def upgrade() -> None:
    for table, column in _DT_COLUMNS:
        # ``USING ... AT TIME ZONE 'UTC'`` reinterprets the existing
        # naive timestamp as UTC (which is what it always was - utcnow()
        # only ever wrote UTC values) without shifting the stored
        # instant.
        op.execute(
            f'ALTER TABLE {table} ALTER COLUMN {column} '
            f'TYPE TIMESTAMP WITH TIME ZONE '
            f'USING {column} AT TIME ZONE \'UTC\''
        )


def downgrade() -> None:
    for table, column in _DT_COLUMNS:
        op.execute(
            f'ALTER TABLE {table} ALTER COLUMN {column} '
            f'TYPE TIMESTAMP WITHOUT TIME ZONE '
            f'USING ({column} AT TIME ZONE \'UTC\')'
        )
