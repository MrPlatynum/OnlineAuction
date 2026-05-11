import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Auction, Bid, NotificationType, User
from app.services.balance import lock_users_by_id
from app.services.notifications import notify_user
from app.services.transactions import add_transaction
from app.services.websocket_manager import manager
from app.utils.time import utcnow

logger = logging.getLogger(__name__)


async def notify_auction_ending_soon(auction: Auction, db: AsyncSession):
    """Уведомление участникам, что аукцион скоро завершится."""
    bids = (
        await db.execute(select(Bid).where(Bid.auction_id == auction.id))
    ).scalars().all()
    user_ids = set([bid.user_id for bid in bids])

    for user_id in user_ids:
        user = (
            await db.execute(select(User).where(User.id == user_id))
        ).scalar_one_or_none()
        if user:
            last_bid = (
                await db.execute(
                    select(Bid)
                    .where(Bid.auction_id == auction.id)
                    .order_by(Bid.timestamp.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            is_winning = last_bid and last_bid.user_id == user_id

            message = "Аукцион завершится через 5 минут! " + (
                "Вы лидируете! 🎉" if is_winning else "Сделайте ставку, чтобы выиграть!"
            )

            await notify_user(
                db, user, NotificationType.AUCTION_ENDING,
                "⏰ Аукцион скоро завершится",
                message,
                auction.id, auction.title, manager,
            )


async def complete_auction(auction_id: int, db: AsyncSession):
    """Завершение аукциона и уведомление участников."""
    # Row-lock the auction first. Guards against a duplicate scheduler
    # tick after server restart (or multi-worker race with /buy-now)
    # double-settling the same lot — the second caller sees is_active=False
    # and exits.
    auction = (
        await db.execute(
            select(Auction).where(Auction.id == auction_id).with_for_update()
        )
    ).scalar_one_or_none()
    if not auction or not auction.is_active:
        return

    # PATCH /auctions/{id} may have extended end_time after the scheduler
    # tick fired but before we acquired the row lock. Re-arm the tick at
    # the new deadline and exit without settling.
    if auction.end_time > utcnow():
        from app.services.auction_scheduler import schedule_auction
        schedule_auction(auction)
        return

    auction.is_active = False
    auction.is_completed = True

    last_bid = (
        await db.execute(
            select(Bid)
            .where(Bid.auction_id == auction_id)
            .order_by(Bid.timestamp.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    if last_bid:
        auction.winner_id = last_bid.user_id
        locked_users = await lock_users_by_id(
            db, last_bid.user_id, auction.created_by
        )
        winner = locked_users.get(last_bid.user_id)
        creator = locked_users.get(auction.created_by)

        if winner:
            winner.balance -= last_bid.amount
            add_transaction(
                db, winner, "bid_win", last_bid.amount,
                f"Победа в аукционе «{auction.title}»", auction_id=auction.id,
            )

        if creator:
            creator.balance += last_bid.amount
            add_transaction(
                db, creator, "auction_sale", last_bid.amount,
                f"Продажа лота «{auction.title}»", auction_id=auction.id,
            )

        bids = (
            await db.execute(select(Bid).where(Bid.auction_id == auction_id))
        ).scalars().all()
        user_ids = set([bid.user_id for bid in bids])

        for user_id in user_ids:
            user = (
                await db.execute(select(User).where(User.id == user_id))
            ).scalar_one_or_none()
            if not user:
                continue

            if user_id == last_bid.user_id:
                await notify_user(
                    db, user, NotificationType.AUCTION_WON,
                    "🎉 Поздравляем! Вы выиграли аукцион!",
                    f"Вы выиграли лот за ${last_bid.amount:.2f}. Средства списаны с вашего баланса.",
                    auction.id, auction.title, manager,
                )
            else:
                await notify_user(
                    db, user, NotificationType.AUCTION_LOST,
                    "Аукцион завершён",
                    f"К сожалению, вы не выиграли этот аукцион. Победитель: {winner.username}.",
                    auction.id, auction.title, manager,
                )

        if creator and creator.id != last_bid.user_id:
            await notify_user(
                db, creator, NotificationType.AUCTION_SOLD,
                "💰 Ваш лот продан!",
                f"Лот продан за ${last_bid.amount:.2f}. Средства зачислены на ваш баланс.",
                auction.id, auction.title, manager,
            )

    await db.commit()

    await manager.broadcast({
        "type": "auction_ended",
        "auction_id": auction_id,
        "winner_id": auction.winner_id,
        "final_price": float(auction.current_price),
    }, auction_id)
