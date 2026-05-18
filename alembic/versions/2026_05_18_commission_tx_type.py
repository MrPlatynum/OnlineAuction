"""Allow 'commission' as a valid transactions.type value

Adding seller commission means a new transaction row per settled sale
that reads ``type='commission'``. The original whitelist constraint
(``ck_transactions_type_valid``) was restrictive, so the insert now
fails with CheckViolationError. This migration drops and re-creates
the constraint with the new value.

Revision ID: b3c4d5e6f7a8
Revises: a1b2c3d4e5f6
Create Date: 2026-05-18 14:30:00.000000

"""
from collections.abc import Sequence
from typing import Union

from alembic import op

revision: str = "b3c4d5e6f7a8"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("ck_transactions_type_valid", "transactions", type_="check")
    op.create_check_constraint(
        "ck_transactions_type_valid",
        "transactions",
        "type IN ('deposit', 'withdrawal', 'bid_win', 'auction_sale', "
        "'bin_purchase', 'commission')",
    )


def downgrade() -> None:
    # Best-effort revert. A row inserted under the new whitelist with
    # type='commission' would prevent the constraint from being re-
    # added — wipe those first so downgrade doesn't 500. In practice
    # downgrade is only used in dev, but be explicit.
    op.execute("DELETE FROM transactions WHERE type = 'commission'")
    op.drop_constraint("ck_transactions_type_valid", "transactions", type_="check")
    op.create_check_constraint(
        "ck_transactions_type_valid",
        "transactions",
        "type IN ('deposit', 'withdrawal', 'bid_win', 'auction_sale', 'bin_purchase')",
    )
