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


async def fetch_auction_bidders(
    db: AsyncSession,
    auction_id: int,
    *,
    exclude_user_ids: tuple[int, ...] = (),
) -> list[User]:
    """Return distinct bidders on ``auction_id`` minus ``exclude_user_ids``,
    in a single SELECT. Shared between ``complete_auction`` (which then
    splits the list into winner + losers) and ``/buy-now`` (which notifies
    everyone but the buyer that the lot ended without them)."""
    user_ids = {
        uid for uid in (
            await db.execute(
                select(Bid.user_id)
                .where(Bid.auction_id == auction_id)
                .distinct()
            )
        ).scalars()
    } - set(exclude_user_ids)
    if not user_ids:
        return []
    return (
        await db.execute(select(User).where(User.id.in_(user_ids)))
    ).scalars().all()


async def notify_auction_ending_soon(auction: Auction, db: AsyncSession):
    """Уведомление участникам, что аукцион скоро завершится."""
    last_bid = (
        await db.execute(
            select(Bid)
            .where(Bid.auction_id == auction.id)
            .order_by(Bid.timestamp.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    users = await fetch_auction_bidders(db, auction.id)
    if not users:
        return
    leader_id = last_bid.user_id if last_bid else None

    for user in users:
        is_winning = user.id == leader_id
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

    # Buffer notification work. notify_user → create_notification commits
    # the session, so dispatching mid-completion would prematurely commit
    # the financial state and then a later raise (SMTP failure, network
    # blip on the second WS push) would leave only a partial set of
    # notifications behind.
    pending_notifications: list[tuple[User, NotificationType, str, str]] = []

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

        users = await fetch_auction_bidders(db, auction_id)
        for user in users:
            if user.id == last_bid.user_id:
                pending_notifications.append((
                    user, NotificationType.AUCTION_WON,
                    "🎉 Поздравляем! Вы выиграли аукцион!",
                    f"Вы выиграли лот за {last_bid.amount:.2f} ₽. Средства списаны с вашего баланса.",
                ))
            else:
                pending_notifications.append((
                    user, NotificationType.AUCTION_LOST,
                    "Аукцион завершён",
                    f"К сожалению, вы не выиграли этот аукцион. Победитель: {winner.username}.",
                ))

        if creator and creator.id != last_bid.user_id:
            pending_notifications.append((
                creator, NotificationType.AUCTION_SOLD,
                "💰 Ваш лот продан!",
                f"Лот продан за {last_bid.amount:.2f} ₽. Средства зачислены на ваш баланс.",
            ))

    await db.commit()

    for user, notif_type, title, message in pending_notifications:
        await notify_user(
            db, user, notif_type, title, message,
            auction.id, auction.title, manager,
        )

    await manager.broadcast({
        "type": "auction_ended",
        "auction_id": auction_id,
        "winner_id": auction.winner_id,
        "final_price": float(auction.current_price),
    }, auction_id)
