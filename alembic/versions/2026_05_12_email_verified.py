"""Add users.email_verified

Gates write actions (place bid, buy now, create auction) on a confirmed
email. server_default=true backfills every existing row (grandfather
clause); alter_column then drops the default so new registrations go
through the model's ``default=False`` and start as unverified.

Revision ID: e1a2b3c4d5e6
Revises: d9e2f3b4a5c6
Create Date: 2026-05-12 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e1a2b3c4d5e6'
down_revision: Union[str, Sequence[str], None] = 'd9e2f3b4a5c6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column(
            'email_verified',
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.alter_column('users', 'email_verified', server_default=None)


def downgrade() -> None:
    op.drop_column('users', 'email_verified')
