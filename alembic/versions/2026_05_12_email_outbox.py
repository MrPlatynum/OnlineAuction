"""Add email_outbox

Persistent queue for transactional email. The previous fire-and-forget
``asyncio.create_task`` model dropped any email the SMTP server
refused - fine for "you've been outbid" pushes, fatal for the
password-reset link (lost link == account lockout). A background
worker drains this table with exponential backoff and dead-letters
rows that exhaust their retry budget.

Revision ID: a1b2c3d4e5f6
Revises: f2b3c4d5e6f7
Create Date: 2026-05-12 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'f2b3c4d5e6f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'email_outbox',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('to_email', sa.String(), nullable=False),
        sa.Column('subject', sa.String(), nullable=False),
        sa.Column('html_body', sa.Text(), nullable=False),
        # 'pending' rows are claimed by the worker; 'sent' is terminal
        # success; 'failed' is terminal dead-letter after the retry
        # budget is exhausted. Kept as a free-form String rather than
        # an Enum so adding new states doesn't need a migration.
        sa.Column('status', sa.String(), nullable=False, server_default='pending'),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('max_attempts', sa.Integer(), nullable=False, server_default='5'),
        sa.Column('last_error', sa.Text(), nullable=True),
        # Worker query is essentially:
        #   WHERE status='pending' AND next_attempt_at <= now()
        # so an index on (status, next_attempt_at) keeps the scan
        # cheap as the table grows.
        sa.Column('next_attempt_at', sa.DateTime(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('sent_at', sa.DateTime(), nullable=True),
    )
    op.create_index(
        'ix_email_outbox_status_next_attempt_at',
        'email_outbox',
        ['status', 'next_attempt_at'],
    )


def downgrade() -> None:
    op.drop_index('ix_email_outbox_status_next_attempt_at', table_name='email_outbox')
    op.drop_table('email_outbox')
