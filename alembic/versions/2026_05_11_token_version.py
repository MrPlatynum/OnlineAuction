"""Add users.token_version

Lets /change-password invalidate existing JWTs by bumping the column;
get_current_user compares the token's ``tv`` claim against the row's
value and rejects mismatches as 401. server_default=0 backfills
existing rows; alter_column then drops the default so future inserts
go through the model's ``default=0``.

Revision ID: c7d1e2a3f4b5
Revises: f1a4e2c8b9d0
Create Date: 2026-05-11 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c7d1e2a3f4b5'
down_revision: Union[str, Sequence[str], None] = 'f1a4e2c8b9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column(
            'token_version',
            sa.Integer(),
            nullable=False,
            server_default='0',
        ),
    )
    op.alter_column('users', 'token_version', server_default=None)


def downgrade() -> None:
    op.drop_column('users', 'token_version')
