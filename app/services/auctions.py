import asyncio
import logging
from datetime import timedelta

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import Auction, AuctionImage, Bid, NotificationType, User
from app.services.notifications import notify_user
from app.services.transactions import add_transaction
from app.services.websocket_manager import manager
from app.utils.time import utcnow

logger = logging.getLogger(__name__)


def get_image_urls(auction: Auction, db: Session):
    imgs = (
        db.query(AuctionImage)
        .filter(AuctionImage.auction_id == auction.id)
        .order_by(AuctionImage.order)
        .all()
    )
    if imgs:
        return [i.url for i in imgs]
    return [auction.image_url] if auction.image_url else []


async def notify_auction_ending_soon(auction: Auction, db: Session):
    """Уведомление участникам, что аукцион скоро завершится."""
    bids = db.query(Bid).filter(Bid.auction_id == auction.id).all()
    user_ids = set([bid.user_id for bid in bids])

    for user_id in user_ids:
        user = db.query(User).filter(User.id == user_id).first()
        if user:
            last_bid = (
                db.query(Bid)
                .filter(Bid.auction_id == auction.id)
                .order_by(Bid.timestamp.desc())
                .first()
            )
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


async def complete_auction(auction_id: int, db: Session):
    """Завершение аукциона и уведомление участников."""
    auction = db.query(Auction).filter(Auction.id == auction_id).first()
    if not auction or not auction.is_active:
        return

    auction.is_active = False
    auction.is_completed = True

    last_bid = (
        db.query(Bid)
        .filter(Bid.auction_id == auction_id)
        .order_by(Bid.timestamp.desc())
        .first()
    )

    if last_bid:
        auction.winner_id = last_bid.user_id
        winner = db.query(User).filter(User.id == last_bid.user_id).first()

        if winner:
            winner.balance -= last_bid.amount
            add_transaction(
                db, winner, "bid_win", last_bid.amount,
                f"Победа в аукционе «{auction.title}»", auction_id=auction.id,
            )

        creator = db.query(User).filter(User.id == auction.created_by).first()
        if creator:
            creator.balance += last_bid.amount
            add_transaction(
                db, creator, "auction_sale", last_bid.amount,
                f"Продажа лота «{auction.title}»", auction_id=auction.id,
            )

        bids = db.query(Bid).filter(Bid.auction_id == auction_id).all()
        user_ids = set([bid.user_id for bid in bids])

        for user_id in user_ids:
            user = db.query(User).filter(User.id == user_id).first()
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

    db.commit()

    await manager.broadcast({
        "type": "auction_ended",
        "auction_id": auction_id,
        "winner_id": auction.winner_id,
        "final_price": auction.current_price,
    }, auction_id)


async def check_expired_auctions():
    """Фоновая задача для завершения аукционов."""
    while True:
        await asyncio.sleep(5)
        db = SessionLocal()
        try:
            now = utcnow()

            expired = (
                db.query(Auction)
                .filter(Auction.is_active == True, Auction.end_time <= now)
                .all()
            )

            for auction in expired:
                await complete_auction(auction.id, db)

            ending_soon = (
                db.query(Auction)
                .filter(
                    Auction.is_active == True,
                    Auction.ending_soon_notified == False,
                    Auction.end_time <= now + timedelta(minutes=5),
                    Auction.end_time > now,
                )
                .all()
            )

            for auction in ending_soon:
                await notify_auction_ending_soon(auction, db)
                auction.ending_soon_notified = True

            db.commit()
        except Exception:
            logger.exception("Error in check_expired_auctions")
            db.rollback()
        finally:
            db.close()
