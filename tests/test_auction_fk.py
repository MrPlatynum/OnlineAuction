"""Referential integrity for ``auction_id`` on notifications/transactions.

Both columns used to be plain ``Integer NULL``: a deleted auction left
dangling references that the frontend then 404'd on. The migration
adds ``FOREIGN KEY ... ON DELETE SET NULL``; this test pins that
behaviour.
"""

from sqlalchemy import select

from app import database as _db_module
from app.models import Auction, Notification, Transaction, User
from app.utils.time import utcnow


async def test_delete_auction_nulls_referencing_rows(registered_user):
    user_id = registered_user["user"]["id"]

    async with _db_module.SessionLocal() as db:
        auction = Auction(
            title="FK test lot",
            description="...",
            starting_price=100,
            current_price=100,
            start_time=utcnow(),
            end_time=utcnow(),
            created_by=user_id,
            auction_type="bid",
        )
        db.add(auction)
        await db.flush()
        auction_id = auction.id

        notification = Notification(
            user_id=user_id,
            type="bid_placed",
            title="Test",
            message="Test",
            auction_id=auction_id,
            auction_title="FK test lot",
        )
        user = (
            await db.execute(select(User).where(User.id == user_id))
        ).scalar_one()
        transaction = Transaction(
            user_id=user_id,
            type="deposit",
            amount=10,
            balance_after=user.balance + 10,
            auction_id=auction_id,
        )
        db.add_all([notification, transaction])
        await db.commit()
        notif_id, tx_id = notification.id, transaction.id

        await db.delete(auction)
        await db.commit()

    async with _db_module.SessionLocal() as db:
        n = (
            await db.execute(select(Notification).where(Notification.id == notif_id))
        ).scalar_one()
        t = (
            await db.execute(select(Transaction).where(Transaction.id == tx_id))
        ).scalar_one()
        assert n.auction_id is None
        assert t.auction_id is None
