import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Auction, AuctionImage, Bid, NotificationType, User
from app.services.notifications import notify_user
from app.services.transactions import add_transaction
from app.services.websocket_manager import manager

logger = logging.getLogger(__name__)


async def get_image_urls(auction: Auction, db: AsyncSession):
    imgs = (
        await db.execute(
            select(AuctionImage)
            .where(AuctionImage.auction_id == auction.id)
            .order_by(AuctionImage.order)
        )
    ).scalars().all()
    if imgs:
        return [i.url for i in imgs]
    return [auction.image_url] if auction.image_url else []


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
    auction = (
        await db.execute(select(Auction).where(Auction.id == auction_id))
    ).scalar_one_or_none()
    if not auction or not auction.is_active:
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
        winner = (
            await db.execute(select(User).where(User.id == last_bid.user_id))
        ).scalar_one_or_none()

        if winner:
            winner.balance -= last_bid.amount
            add_transaction(
                db, winner, "bid_win", last_bid.amount,
                f"Победа в аукционе «{auction.title}»", auction_id=auction.id,
            )

        creator = (
            await db.execute(select(User).where(User.id == auction.created_by))
        ).scalar_one_or_none()
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
