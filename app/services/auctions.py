"""Money-and-state side of an auction's lifecycle.

``settle_bin_purchase`` and ``complete_auction`` are the two sinks
that flip a lot to its terminal state and move funds between the
buyer, the seller, and the platform commission ledger row. Both run
inside a row-locked transaction so a duplicate scheduler tick or a
buy-now / settle race can't double-settle.

The scheduler-side hooks (settle handler, ending-soon handler) are
wired into ``auction_scheduler`` at import time so the scheduler
module stays a one-way upstream dependency.
"""

import logging
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
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


def seller_commission(gross_price: Decimal) -> Decimal:
    """Platform fee withheld from the seller's payout on every settled
    sale. Rounded to two decimal places with HALF_UP so the two seller
    transaction rows (auction_sale gross + commission deduction) sum
    cleanly to the net payout - banker's rounding would leave 0.005 ₽
    drifts at scale."""
    raw = gross_price * PLATFORM_COMMISSION_PERCENT / Decimal(100)
    return raw.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _credit_seller(
    db: AsyncSession,
    seller: User,
    gross: Decimal,
    auction: Auction,
    *,
    sale_description: str,
) -> None:
    """Apply the seller side of a settled sale: a gross sale credit
    followed by a separate commission debit. Two transaction rows
    instead of one net row so the audit history reads naturally - the
    seller sees the headline sale price and the platform fee as
    distinct lines. Used by both the BIN and the bid settlement paths,
    which differ only in ``sale_description`` (BIN says "по цене BIN",
    bid says "лота")."""
    # Quantize gross to 2 decimals before mutating the in-memory ORM
    # balance. The DB column is Numeric(12, 2) - any caller passing a
    # Decimal with >2 decimal places (in practice the per-row stored
    # value already matches, but a future caller computing gross at
    # higher precision could drift) would leave seller.balance and
    # the audit row both un-quantized while Postgres rounds on store.
    gross = gross.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    seller.balance += gross
    add_transaction(
        db, seller, "auction_sale", gross,
        sale_description, auction_id=auction.id,
    )
    commission = seller_commission(gross)
    if commission > 0:
        seller.balance -= commission
        add_transaction(
            db, seller, "commission", commission,
            f"Комиссия платформы {PLATFORM_COMMISSION_PERCENT}%",
            auction_id=auction.id,
        )


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
    listing was up" edge case - buyer still gets the goods, the lot
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
        _credit_seller(
            db, seller, price, auction,
            sale_description=f"Продажа «{auction.title}» по цене BIN",
        )


def _build_completion_notifications(
    *,
    auction: Auction,
    last_bid: Bid,
    winner: User | None,
    creator: User | None,
    bidders: list[User],
) -> list[tuple[User, NotificationType, str, str]]:
    """Build the (recipient, type, title, body) tuples for every
    notification fired off the end-of-auction settle path. Pure: no DB
    work, no commits - caller is responsible for the actual dispatch
    after the financial commit has gone through. Pulled out of
    ``complete_auction`` to keep that function's flow readable; the
    same shape is also easier to unit-test in isolation."""
    pending: list[tuple[User, NotificationType, str, str]] = []
    for user in bidders:
        if user.id == last_bid.user_id:
            pending.append((
                user, NotificationType.AUCTION_WON,
                "🎉 Поздравляем! Вы выиграли аукцион!",
                f"Вы выиграли лот за {last_bid.amount:.2f} ₽. Средства списаны с вашего баланса.",
            ))
        else:
            pending.append((
                user, NotificationType.AUCTION_LOST,
                "Аукцион завершён",
                f"К сожалению, вы не выиграли этот аукцион. Победитель: {winner.username}.",
            ))
    if creator and creator.id != last_bid.user_id:
        commission = seller_commission(last_bid.amount)
        net = last_bid.amount - commission
        pending.append((
            creator, NotificationType.AUCTION_SOLD,
            "💰 Ваш лот продан!",
            (
                f"Лот продан за {last_bid.amount:.2f} ₽. "
                f"На баланс зачислено {net:.2f} ₽ "
                f"(комиссия платформы {PLATFORM_COMMISSION_PERCENT}% - {commission:.2f} ₽)."
            ),
        ))
    return pending


async def count_bids_by_auction(
    db: AsyncSession, auction_ids: list[int]
) -> dict[int, int]:
    """Single grouped COUNT per page of auctions. Turns the listing
    handler from O(page_size) round-trips (one COUNT per lot) into O(1).
    Used by both the public ``/auctions`` listing and the
    ``/my/participation`` created_auctions bucket - they both pull a
    page of Auction rows and need ``bids_count`` for each."""
    if not auction_ids:
        return {}
    rows = (
        await db.execute(
            select(Bid.auction_id, func.count(Bid.id))
            .where(Bid.auction_id.in_(auction_ids))
            .group_by(Bid.auction_id)
        )
    ).all()
    # ``func.count`` returns ``int`` on asyncpg but ``Decimal`` on
    # other drivers. Coerce at the boundary so downstream callers and
    # response schemas don't have to.
    return {aid: int(cnt) for aid, cnt in rows}


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
    """Fire the five-minute warning to every bidder on this lot.

    Registered into auction_scheduler as the ENDING_SOON handler at module
    import time. The "winning / not winning" copy is tailored per recipient
    against the most recent bid - the current leader gets a "Вы лидируете"
    message, everyone else gets a "сделайте ставку" nudge.
    """
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
    """Settle the lot and notify every participant.

    Registered into auction_scheduler as the SETTLE handler at module
    import time. Takes ``SELECT ... FOR UPDATE`` on the auction so a
    duplicate scheduler tick (post-restart) or a /buy-now race ends up
    serialised; the second caller sees ``is_active=False`` and bails.
    If the deadline moved (PATCH extension) the tick re-arms itself
    via ``schedule_auction`` instead of settling early.
    """
    # FOR UPDATE so a duplicate scheduler tick (post-restart) or a race
    # with /buy-now can't double-settle - second caller sees is_active=False.
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
            _credit_seller(
                db, creator, last_bid.amount, auction,
                sale_description=f"Продажа лота «{auction.title}»",
            )

        bidders = await fetch_auction_bidders(db, auction_id)
        pending_notifications = _build_completion_notifications(
            auction=auction,
            last_bid=last_bid,
            winner=winner,
            creator=creator,
            bidders=bidders,
        )

    await db.commit()

    # Broadcast the "auction ended" frame before the per-recipient fan-out:
    # it doesn't touch the DB and benefits every subscribed client (whether
    # they bid or not). If a later notify_user raises, the broadcast has
    # already gone out, so the listing card stops counting down even if
    # individual notifications drop.
    await manager.broadcast({
        "type": "auction_ended",
        "auction_id": auction_id,
        "winner_id": auction.winner_id,
        "final_price": float(auction.current_price),
    }, auction_id)

    # Notifications are best-effort once the financial side is committed.
    # A single failed recipient (deleted user, transient DB drop on the
    # commit inside create_notification, WS send error) used to abort the
    # whole loop and leave later bidders un-notified - and propagate up
    # to _wait_and_complete's except Exception, which rolled back the
    # already-committed money side's session for no benefit.
    for user, notif_type, title, message in pending_notifications:
        try:
            await notify_user(
                db, user, notif_type, title, message,
                auction.id, auction.title, manager,
            )
        except Exception:
            logger.exception(
                "Notification dispatch failed for user %s on auction %s",
                user.id, auction_id,
            )


# Wire the scheduler's "settle this id" / "ending-soon" hooks to our
# implementations. Done at module-import time so scheduler tasks armed
# from anywhere (request handlers, schedule_active_auctions on startup,
# tests) see registered handlers. See auction_scheduler.register_handlers.
auction_scheduler.register_handlers(complete_auction, notify_auction_ending_soon)
