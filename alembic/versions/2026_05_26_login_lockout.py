"""Add failed_login_count + locked_until to users

The /login route was rate-limited per IP (10/min) but had no
per-account ceiling, so a credential-stuffing botnet hitting one
account from a /16 worth of addresses stayed comfortably under the
limit. Add two columns the handler increments on every failed
attempt (and clears on success), plus an exponential lockout window
when the failure count crosses 5 / 10 / 15 / 20.

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2026-05-26 21:30:00.000000

"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "c4d5e6f7a8b9"
down_revision: Union[str, Sequence[str], None] = "b3c4d5e6f7a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # server_default=0 backfills the new column on existing rows so
    # the NOT NULL constraint takes hold without a manual UPDATE
    # pass; subsequent INSERTs from the ORM go through the Python
    # default (also 0) and never rely on the server default.
    op.add_column(
        "users",
        sa.Column(
            "failed_login_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "users",
        sa.Column("locked_until", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "locked_until")
    op.drop_column("users", "failed_login_count")
