"""Add users.notify_lost

Lets a user mute the AUCTION_LOST email channel — every other event
type already had its own toggle, AUCTION_LOST was the only one that
silently followed the master ``email_notifications`` flag. Defaults
to true so existing users keep their current behaviour.

Revision ID: d9e2f3b4a5c6
Revises: c7d1e2a3f4b5
Create Date: 2026-05-11 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd9e2f3b4a5c6'
down_revision: Union[str, Sequence[str], None] = 'c7d1e2a3f4b5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column(
            'notify_lost',
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.alter_column('users', 'notify_lost', server_default=None)


def downgrade() -> None:
    op.drop_column('users', 'notify_lost')
