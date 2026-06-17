"""Add CHECK (bin_price IS NULL OR bin_price >= starting_price)

A BIN price below the starting_price is a degenerate business state:
``/buy-now`` would charge less than what the listing card advertises
as the floor. The API enforces this at the input layer (the BIN
syncing logic in routers/auctions.py drags ``starting_price`` along
with ``bin_price`` so they stay equal on a BIN lot), but an admin
tool or data import could otherwise slip past that gate and corrupt
the listing. This migration adds the constraint at the schema layer
so the invariant lives in one place.

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-05-28 22:30:00.000000

"""
from collections.abc import Sequence
from typing import Union

from alembic import op

revision: str = "e2f3a4b5c6d7"
down_revision: Union[str, Sequence[str], None] = "d1e2f3a4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_auctions_bin_ge_start",
        "auctions",
        "bin_price IS NULL OR bin_price >= starting_price",
    )


def downgrade() -> None:
    op.drop_constraint("ck_auctions_bin_ge_start", "auctions", type_="check")
