"""Add users.password_reset_sent_at

Backs the per-email 60-second throttle on /api/password-reset/request:
record the last send time and reject another /request from the same
account inside that window even if it comes from a different IP. The
column is nullable — accounts that never requested a reset stay NULL
and pass the throttle on first request.

Revision ID: f2b3c4d5e6f7
Revises: e1a2b3c4d5e6
Create Date: 2026-05-12 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f2b3c4d5e6f7'
down_revision: Union[str, Sequence[str], None] = 'e1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column('password_reset_sent_at', sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('users', 'password_reset_sent_at')
