import logging
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import PLATFORM_COMMISSION_PERCENT
from app.models import Auction, Bid, NotificationType, User
from app.services import auction_scheduler
from app.services.balance import lock_users_by_id
from app.services.notifications import notify_user
from app.services.transactions import add_transaction
from app.services.websocket_manager import manager
from app.utils.time import utcnow

logger = logging.getLogger(__name__)


def _seller_commission(gross_price: Decimal) -> Decimal:
    """Platform fee withheld from the seller's payout on every settled
    sale. Rounded to two decimal places with HALF_UP so the two seller
    transaction rows (auction_sale gross + commission deduction) sum
    cleanly to the net payout — banker's rounding would leave 0.005 ₽
    drifts at scale."""
    raw = gross_price * PLATFORM_COMMISSION_PERCENT / Decimal(100)
    return raw.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def settle_bin_purchase(
    db: AsyncSession,
    auction: Auction,
    buyer: User,
    seller: User | None,
) -> None:
    """Apply the money side of a BIN purchase: debit the buyer, credit
    the seller (if present), flip the lot to settled state, log both
    transactions. Caller still owns the commit so it can sequence it
    with row locks and notifications.

    ``seller is None`` is the "creator account was deleted while their
    listing was up" edge case — buyer still gets the goods, the lot
    just doesn't credit anyone."""
    price = auction.bin_price
    buyer.balance -= price
    add_transaction(
        db, buyer, "bin_purchase", price,
        f"Покупка «{auction.title}» по цене BIN", auction_id=auction.id,
    )
    auction.current_price = price
    auction.is_active = False
    auction.is_completed = True
    auction.winner_id = buyer.id
    auction.end_time = utcnow()
    if seller:
        # Gross credit first so the audit row shows the headline sale
        # price the user expects to see — then deduct the platform fee
        # as its own row. Net effect on balance is price − commission;
        # splitting the rows keeps each transaction readable on its own.
        seller.balance += price
        add_transaction(
            db, seller, "auction_sale", price,
            f"Продажа «{auction.title}» по цене BIN", auction_id=auction.id,
        )
        commission = _seller_commission(price)
        if commission > 0:
            seller.balance -= commission
            add_transaction(
                db, seller, "commission", commission,
                f"Комиссия платформы {PLATFORM_COMMISSION_PERCENT}%",
                auction_id=auction.id,
            )


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
    # FOR UPDATE so a duplicate scheduler tick (post-restart) or a race
    # with /buy-now can't double-settle — second caller sees is_active=False.
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
        auction_scheduler.schedule_auction(auction)
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
            # See settle_bin_purchase: gross sale credit, then a
            # separate commission deduction so the audit history reads
            # naturally for both the seller and any future support tool.
            creator.balance += last_bid.amount
            add_transaction(
                db, creator, "auction_sale", last_bid.amount,
                f"Продажа лота «{auction.title}»", auction_id=auction.id,
            )
            commission = _seller_commission(last_bid.amount)
            if commission > 0:
                creator.balance -= commission
                add_transaction(
                    db, creator, "commission", commission,
                    f"Комиссия платформы {PLATFORM_COMMISSION_PERCENT}%",
                    auction_id=auction.id,
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
            commission = _seller_commission(last_bid.amount)
            net = last_bid.amount - commission
            pending_notifications.append((
                creator, NotificationType.AUCTION_SOLD,
                "💰 Ваш лот продан!",
                (
                    f"Лот продан за {last_bid.amount:.2f} ₽. "
                    f"На баланс зачислено {net:.2f} ₽ "
                    f"(комиссия платформы {PLATFORM_COMMISSION_PERCENT}% — {commission:.2f} ₽)."
                ),
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


# Wire the scheduler's "settle this id" / "ending-soon" hooks to our
# implementations. Done at module-import time so scheduler tasks armed
# from anywhere (request handlers, schedule_active_auctions on startup,
# tests) see registered handlers. See auction_scheduler.register_handlers.
auction_scheduler.register_handlers(complete_auction, notify_auction_ending_soon)
