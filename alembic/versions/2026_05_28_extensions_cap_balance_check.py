"""Add Auction.extensions_count and User.balance non-negative CHECK

Two small DB-level invariants for the settle and bid paths.

``Auction.extensions_count`` (default 0, NOT NULL) backs the
MAX_ANTISNIPING_EXTENSIONS cap in routers/bids.py. Existing rows are
backfilled to 0; the column is incremented from the application layer
on every successful anti-sniping extension.

``ck_users_balance_nonneg`` (``CHECK (balance >= 0)``) is a safety
net for the money paths. Every code path that mutates balance already
pre-checks at the application layer (deposit caps at MAX_USER_BALANCE,
withdraw validates available >= amount, complete_auction debits the
locked row only after the bid passed availability checks), but a bug
or admin SQL that somehow leaks a negative debit would silently
corrupt the audit trail. The CHECK catches that at INSERT/UPDATE.

Revision ID: a8b9c0d1e2f3
Revises: f7a8b9c0d1e2
Create Date: 2026-05-28 19:00:00.000000

"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "a8b9c0d1e2f3"
down_revision: Union[str, Sequence[str], None] = "f7a8b9c0d1e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "auctions",
        sa.Column(
            "extensions_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.create_check_constraint(
        "ck_users_balance_nonneg", "users", "balance >= 0"
    )


def downgrade() -> None:
    op.drop_constraint("ck_users_balance_nonneg", "users", type_="check")
    op.drop_column("auctions", "extensions_count")
