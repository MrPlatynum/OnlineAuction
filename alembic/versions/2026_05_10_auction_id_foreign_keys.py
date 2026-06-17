"""Make Notification.auction_id and Transaction.auction_id real FKs

Adds ``FOREIGN KEY (...) REFERENCES auctions(id) ON DELETE SET NULL``
on both columns so deleting an auction clears the references instead
of leaving dangling ids. The pre-upgrade UPDATEs NULL out any already-
broken rows so the constraint applies cleanly.

Revision ID: f1a4e2c8b9d0
Revises: a8b5c1f0d2e9
Create Date: 2026-05-10 11:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = 'f1a4e2c8b9d0'
down_revision: Union[str, Sequence[str], None] = 'a8b5c1f0d2e9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "UPDATE notifications SET auction_id = NULL "
        "WHERE auction_id IS NOT NULL "
        "AND auction_id NOT IN (SELECT id FROM auctions)"
    )
    op.execute(
        "UPDATE transactions SET auction_id = NULL "
        "WHERE auction_id IS NOT NULL "
        "AND auction_id NOT IN (SELECT id FROM auctions)"
    )
    op.create_foreign_key(
        "fk_notifications_auction_id",
        "notifications", "auctions",
        ["auction_id"], ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_transactions_auction_id",
        "transactions", "auctions",
        ["auction_id"], ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_transactions_auction_id", "transactions", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_notifications_auction_id", "notifications", type_="foreignkey"
    )
