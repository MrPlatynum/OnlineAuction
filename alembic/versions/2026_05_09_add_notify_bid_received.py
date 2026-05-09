"""Add notify_bid_received

Splits the BID_PLACED email gate off ``notify_sold``, which it was
sharing with AUCTION_SOLD by copy-paste. Defaults to true so existing
users keep their current behaviour (BID_PLACED emails enabled).

Revision ID: a8b5c1f0d2e9
Revises: 97c0d0386a72
Create Date: 2026-05-09 15:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a8b5c1f0d2e9'
down_revision: Union[str, Sequence[str], None] = '97c0d0386a72'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # server_default=true backfills existing rows; alter_column then
    # drops the default so future inserts go through the model's
    # ``default=True`` (matches the rest of the notify_* columns).
    op.add_column(
        'users',
        sa.Column(
            'notify_bid_received',
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.alter_column('users', 'notify_bid_received', server_default=None)


def downgrade() -> None:
    op.drop_column('users', 'notify_bid_received')
