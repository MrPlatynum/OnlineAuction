"""Add upload byte-budget columns to users

Rolling 24h cap on bytes per user accepted by /upload-image and
/upload-avatar. The two new columns track the current window's
running total and its opening; the handler resets both whenever a
fresh upload lands more than 24h after the recorded start.

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-05-26 21:45:00.000000

"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "d5e6f7a8b9c0"
down_revision: Union[str, Sequence[str], None] = "c4d5e6f7a8b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "upload_bytes_window",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "users",
        sa.Column("upload_window_start", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "upload_window_start")
    op.drop_column("users", "upload_bytes_window")
