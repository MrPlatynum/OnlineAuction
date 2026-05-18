from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete as sql_delete
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models import (
    Auction,
    AuctionImage,
    Bid,
    Category,
    NotificationType,
    Subscription,
    User,
)
from app.schemas import (
    AuctionCreate,
    AuctionResponse,
    AuctionUpdate,
    PaginatedAuctionsResponse,
)
from app.services.auction_scheduler import cancel_auction, schedule_auction
from app.config import PLATFORM_COMMISSION_PERCENT
from app.services.auctions import (
    _seller_commission,
    fetch_auction_bidders,
    settle_bin_purchase,
)
from app.services.balance import lock_users_by_id
from app.services.notifications import create_notification, notify_user
from app.services.websocket_manager import manager
from app.utils.security import get_current_user, require_verified_user
from app.utils.time import utcnow

router = APIRouter(prefix="/api", tags=["auctions"])


def _time_remaining(auction: Auction) -> int:
    """Seconds left until ``end_time`` — single source of truth used by
    every dict-builder in this module. Returns 0 for completed lots or
    when ``end_time`` is somehow None (defensive: the column is NOT NULL
    but a freshly-built ORM instance can briefly be unset)."""
    if not auction.end_time or not auction.is_active:
        return 0
    return max(0, int((auction.end_time - utcnow()).total_seconds()))


def _participation_row(auction: Auction, my_amount) -> dict:
    """Row shape for the /my/participation active/won/lost buckets.
    ``my_amount`` is the caller's latest bid on this auction (may be
    None for the never-bid-but-won-via-buy-now corner case, which
    doesn't currently happen but the column tolerates it)."""
    return {
        "auction_id": auction.id,
        "title": auction.title,
        "image_url": auction.image_url,
        "current_price": float(auction.current_price),
        "my_bid": float(my_amount) if my_amount is not None else 0,
        "is_winning": auction.current_price == my_amount,
        "end_time": auction.end_time.isoformat(),
        "time_remaining": _time_remaining(auction),
        "is_active": auction.is_active,
        "auction_type": auction.auction_type or "bid",
    }


def _created_lot_row(auction: Auction, bids_count: int) -> dict:
    """Row shape for the /my/participation created_auctions bucket."""
    return {
        "auction_id": auction.id,
        "title": auction.title,
        "current_price": float(auction.current_price),
        "starting_price": float(auction.starting_price),
        "is_active": auction.is_active,
        "winner_id": auction.winner_id,
        "bids_count": bids_count,
        "image_url": auction.image_url,
        "end_time": auction.end_time.isoformat() if auction.end_time else None,
        "time_remaining": _time_remaining(auction),
    }


def _auction_to_dict(auction: Auction, bids_count: int) -> dict:
    """Build the listing-row dict from an ``Auction`` whose ``creator``,
    ``category`` and ``images`` were eager-loaded via ``selectinload``.
    Touches no DB, so the listing handler stays O(1) per row."""
    creator = auction.creator
    cat = auction.category
    image_urls = [i.url for i in auction.images] if auction.images else []
    if not image_urls and auction.image_url:
        image_urls = [auction.image_url]
    return {
        "id": auction.id,
        "title": auction.title,
        "description": auction.description,
        "starting_price": auction.starting_price,
        "current_price": auction.current_price,
        "image_url": auction.image_url,
        "image_urls": image_urls,
        "start_time": auction.start_time,
        "end_time": auction.end_time,
        "is_active": auction.is_active,
        "is_completed": auction.is_completed,
        "winner_id": auction.winner_id,
        "created_by": auction.created_by,
        "creator_username": creator.username if creator else None,
        "creator_avatar_url": creator.avatar_url if creator else None,
        "bids_count": bids_count,
        "time_remaining": max(0, int((auction.end_time - utcnow()).total_seconds())),
        "category_id": auction.category_id,
        "category_name": cat.name if cat else None,
        "category_icon": cat.icon if cat else None,
        "auction_type": auction.auction_type or "bid",
        "bin_price": auction.bin_price,
    }


@router.post("/auctions", response_model=AuctionResponse)
async def create_auction(
    auction: AuctionCreate,
    current_user: User = Depends(require_verified_user),
    db: AsyncSession = Depends(get_db),
):
    start_time = utcnow()
    end_time = start_time + timedelta(minutes=auction.duration_minutes)

    auction_type = auction.auction_type or "bid"
    # BIN is a fixed-price listing — starting_price is meaningless there
    # and would let the UI show "$10" on a lot the buyer actually pays
    # $bin_price for. Coerce both seed prices to bin_price so what the
    # listing card shows is what /buy-now charges.
    if auction_type == "bin" and auction.bin_price is not None:
        seed_price = auction.bin_price
    else:
        seed_price = auction.starting_price

    db_auction = Auction(
        title=auction.title,
        description=auction.description,
        starting_price=seed_price,
        current_price=seed_price,
        image_url=auction.image_url,
        start_time=start_time,
        end_time=end_time,
        created_by=current_user.id,
        category_id=auction.category_id,
        auction_type=auction_type,
        bin_price=auction.bin_price,
    )
    db.add(db_auction)
    await db.commit()
    await db.refresh(db_auction)

    schedule_auction(db_auction)

    all_urls = auction.image_urls or ([auction.image_url] if auction.image_url else [])
    for i, url in enumerate(all_urls):
        db.add(AuctionImage(auction_id=db_auction.id, url=url, order=i))
    if all_urls:
        await db.commit()

    subscribers = (
        await db.execute(
            select(Subscription).where(Subscription.seller_id == current_user.id)
        )
    ).scalars().all()
    for sub in subscribers:
        await create_notification(
            db=db,
            user_id=sub.subscriber_id,
            notification_type=NotificationType.NEW_LOT,
            title="Новый лот",
            message=f"@{current_user.username} выставил новый лот: «{db_auction.title}»",
            auction_id=db_auction.id,
            auction_title=db_auction.title,
        )

    # Re-fetch with relationships eager-loaded so the response goes through
    # the same shape as the listing — kept these dicts drifting apart before
    # (missing fields, divergent time_remaining math). bids_count is 0 by
    # construction: a freshly-created auction has no bids yet.
    loaded = (
        await db.execute(
            select(Auction)
            .where(Auction.id == db_auction.id)
            .options(
                selectinload(Auction.creator),
                selectinload(Auction.category),
                selectinload(Auction.images),
            )
        )
    ).scalar_one()
    return AuctionResponse(**_auction_to_dict(loaded, bids_count=0))


@router.post("/auctions/{auction_id}/buy-now")
async def buy_now(
    auction_id: int,
    current_user: User = Depends(require_verified_user),
    db: AsyncSession = Depends(get_db),
):
    # FOR UPDATE so two /buy-now (or /buy-now racing complete_auction)
    # don't double-charge — the second caller sees is_active=False.
    auction = (
        await db.execute(
            select(Auction).where(Auction.id == auction_id).with_for_update()
        )
    ).scalar_one_or_none()
    if not auction:
        raise HTTPException(status_code=404, detail="Аукцион не найден")
    if not auction.is_active:
        raise HTTPException(status_code=400, detail="Аукцион завершён")
    if utcnow() > auction.end_time:
        # Don't flip is_active / is_completed here. complete_auction is the
        # single path that finalises a lot (winner_id + balance transfer +
        # notifications); writing terminal flags from a request handler
        # short-circuits the scheduler's later tick and strands the lot
        # with no payout for any bidders already on it.
        raise HTTPException(status_code=400, detail="Аукцион завершён")
    if auction.auction_type != "bin":
        raise HTTPException(status_code=400, detail="Этот аукцион не поддерживает покупку сразу")
    if not auction.bin_price:
        raise HTTPException(status_code=400, detail="Цена BIN не установлена")
    if auction.created_by == current_user.id:
        raise HTTPException(status_code=400, detail="Нельзя купить собственный лот")

    locked_users = await lock_users_by_id(db, current_user.id, auction.created_by)
    creator = locked_users.get(auction.created_by)
    if current_user.balance < auction.bin_price:
        raise HTTPException(
            status_code=400,
            detail=f"Недостаточно средств. Нужно {auction.bin_price:.2f} ₽, у вас {current_user.balance:.2f} ₽",
        )

    settle_bin_purchase(db, auction, current_user, creator)
    await db.commit()

    cancel_auction(auction_id)

    if creator:
        commission = _seller_commission(auction.bin_price)
        net = auction.bin_price - commission
        await notify_user(
            db, creator, NotificationType.AUCTION_SOLD,
            "✅ Лот куплен по цене BIN",
            (
                f"{current_user.username} купил «{auction.title}» за {auction.bin_price:.2f} ₽. "
                f"На баланс зачислено {net:.2f} ₽ "
                f"(комиссия платформы {PLATFORM_COMMISSION_PERCENT}% — {commission:.2f} ₽)."
            ),
            auction.id, auction.title, manager,
        )

    # Notify everyone who placed a real bid before the BIN-purchase that
    # the auction ended without them. complete_auction does this on the
    # timer path; /buy-now used to silently leave them in the dark.
    losers = await fetch_auction_bidders(
        db, auction_id, exclude_user_ids=(current_user.id,)
    )
    for loser in losers:
        await notify_user(
            db, loser, NotificationType.AUCTION_LOST,
            "Аукцион завершён",
            f"Лот «{auction.title}» куплен по цене BIN другим участником.",
            auction.id, auction.title, manager,
        )

    return {"message": "Покупка совершена", "price": float(auction.bin_price)}


@router.get("/auctions", response_model=PaginatedAuctionsResponse)
async def get_auctions(
    page: int = Query(1, ge=1),
    page_size: int = Query(12, ge=1, le=50),
    status: str = Query("active", pattern="^(active|completed|all)$"),
    search: str | None = Query(None),
    min_price: float | None = Query(None, ge=0),
    max_price: float | None = Query(None, ge=0),
    sort_by: str = Query("time", pattern="^(time|price_asc|price_desc)$"),
    created_by: str | None = Query(None),
    category: str | None = Query(None),
    auction_type: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    query = select(Auction)

    if status == "active":
        query = query.where(Auction.is_active.is_(True))
    elif status == "completed":
        query = query.where(Auction.is_completed.is_(True))

    if search:
        search_pattern = f"%{search}%"
        query = query.where(
            (Auction.title.ilike(search_pattern))
            | (Auction.description.ilike(search_pattern))
        )

    if min_price is not None:
        query = query.where(Auction.current_price >= min_price)
    if max_price is not None:
        query = query.where(Auction.current_price <= max_price)

    if created_by:
        creator_user = (
            await db.execute(select(User).where(User.username == created_by))
        ).scalar_one_or_none()
        if creator_user:
            query = query.where(Auction.created_by == creator_user.id)
        else:
            query = query.where(Auction.id == -1)

    if category:
        cat_obj = (
            await db.execute(select(Category).where(Category.slug == category))
        ).scalar_one_or_none()
        if cat_obj:
            cat_ids = [cat_obj.id]
            children = (
                await db.execute(
                    select(Category).where(Category.parent_id == cat_obj.id)
                )
            ).scalars().all()
            cat_ids += [c.id for c in children]
            query = query.where(Auction.category_id.in_(cat_ids))
        else:
            query = query.where(Auction.id == -1)

    if auction_type == "bid":
        query = query.where(Auction.auction_type == "bid")
    elif auction_type == "bin":
        query = query.where(Auction.auction_type == "bin")

    total = await db.scalar(
        select(func.count()).select_from(query.subquery())
    )
    total_pages = (total + page_size - 1) // page_size

    if sort_by == "time":
        query = query.order_by(Auction.end_time.asc())
    elif sort_by == "price_asc":
        query = query.order_by(Auction.current_price.asc())
    elif sort_by == "price_desc":
        query = query.order_by(Auction.current_price.desc())

    offset = (page - 1) * page_size
    auctions = (
        await db.execute(
            query
            .options(
                selectinload(Auction.creator),
                selectinload(Auction.category),
                selectinload(Auction.images),
            )
            .offset(offset)
            .limit(page_size)
        )
    ).scalars().all()

    # One aggregate query for the whole page instead of one COUNT per
    # row — turns the listing from O(page_size) round-trips into O(1).
    auction_ids = [a.id for a in auctions]
    bid_counts: dict[int, int] = {}
    if auction_ids:
        rows = (
            await db.execute(
                select(Bid.auction_id, func.count(Bid.id))
                .where(Bid.auction_id.in_(auction_ids))
                .group_by(Bid.auction_id)
            )
        ).all()
        bid_counts = {aid: cnt for aid, cnt in rows}

    result = [
        AuctionResponse(**_auction_to_dict(a, bid_counts.get(a.id, 0)))
        for a in auctions
    ]

    return PaginatedAuctionsResponse(
        items=result,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get("/auctions/{auction_id}", response_model=AuctionResponse)
async def get_auction(auction_id: int, db: AsyncSession = Depends(get_db)):
    auction = (
        await db.execute(
            select(Auction)
            .options(
                selectinload(Auction.creator),
                selectinload(Auction.category),
                selectinload(Auction.images),
            )
            .where(Auction.id == auction_id)
        )
    ).scalar_one_or_none()
    if not auction:
        raise HTTPException(status_code=404, detail="Аукцион не найден")

    bids_count = await db.scalar(
        select(func.count()).select_from(Bid).where(Bid.auction_id == auction_id)
    )
    return AuctionResponse(**_auction_to_dict(auction, bids_count))


@router.patch("/auctions/{auction_id}")
async def update_auction(
    auction_id: int,
    data: AuctionUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # FOR UPDATE so concurrent place_bid / complete_auction can't mutate
    # state between our checks and the commit.
    auction = (
        await db.execute(
            select(Auction).where(Auction.id == auction_id).with_for_update()
        )
    ).scalar_one_or_none()
    if not auction:
        raise HTTPException(status_code=404, detail="Аукцион не найден")
    if auction.created_by != current_user.id:
        raise HTTPException(status_code=403, detail="Это не ваш лот")
    if not auction.is_active:
        raise HTTPException(status_code=400, detail="Лот уже завершён — редактирование недоступно")

    fields = data.model_fields_set
    has_bids = await db.scalar(
        select(func.count()).select_from(Bid).where(Bid.auction_id == auction_id)
    )
    # Once there are bids, the only safe edit is extending the deadline:
    # changing title/price/category after a bidder has committed money is
    # bait-and-switch.
    if has_bids and fields - {"extend_minutes"}:
        raise HTTPException(
            status_code=400,
            detail="На лоте уже есть ставки — можно только продлить срок (extend_minutes)",
        )

    if "title" in fields and data.title:
        auction.title = data.title.strip()
    if "description" in fields and data.description is not None:
        auction.description = data.description.strip()
    if "category_id" in fields:
        auction.category_id = data.category_id
    if "starting_price" in fields and data.starting_price is not None:
        auction.starting_price = data.starting_price
        auction.current_price = data.starting_price
    if "bin_price" in fields:
        auction.bin_price = data.bin_price
    if "auction_type" in fields and data.auction_type is not None:
        auction.auction_type = data.auction_type
    extended = False
    if "extend_minutes" in fields and data.extend_minutes is not None:
        auction.end_time = auction.end_time + timedelta(minutes=data.extend_minutes)
        extended = True
    if "image_urls" in fields and data.image_urls is not None:
        await db.execute(
            sql_delete(AuctionImage).where(AuctionImage.auction_id == auction_id)
        )
        for i, url in enumerate(data.image_urls):
            db.add(AuctionImage(auction_id=auction_id, url=url, order=i))
        auction.image_url = data.image_urls[0] if data.image_urls else None

    # BIN is a fixed-price listing — bin_price IS the displayed/charged
    # price. If the seller edits it (or switches the lot to BIN), drag
    # starting_price / current_price along so the listing card and
    # /buy-now stay in sync.
    if auction.auction_type == "bin" and auction.bin_price is not None and (
        "bin_price" in fields or "auction_type" in fields
    ):
        auction.starting_price = auction.bin_price
        auction.current_price = auction.bin_price

    await db.commit()
    await db.refresh(auction)

    if extended:
        schedule_auction(auction)

    return {"message": "Лот обновлён", "id": auction.id}


@router.delete("/auctions/{auction_id}")
async def delete_auction(
    auction_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # FOR UPDATE so scheduler._wait_and_complete can't settle the lot
    # between our checks and the commit.
    auction = (
        await db.execute(
            select(Auction).where(Auction.id == auction_id).with_for_update()
        )
    ).scalar_one_or_none()
    if not auction:
        raise HTTPException(status_code=404, detail="Аукцион не найден")
    if auction.created_by != current_user.id:
        raise HTTPException(status_code=403, detail="Нельзя удалить чужой лот")

    bids_count = await db.scalar(
        select(func.count()).select_from(Bid).where(Bid.auction_id == auction_id)
    )

    if auction.is_active and bids_count > 0:
        raise HTTPException(status_code=400, detail="Нельзя удалить активный лот со ставками")

    if auction.is_completed and auction.winner_id:
        raise HTTPException(status_code=400, detail="Нельзя удалить лот с победителем")

    await db.delete(auction)
    await db.commit()
    # Cancel the in-memory scheduler tasks *after* the row is gone for
    # good. If the commit fails (FK violation, lost connection) we still
    # want the scheduler to settle the lot — popping its task before the
    # commit would leave the row alive without anyone armed to complete it.
    cancel_auction(auction_id)
    return {"message": "Лот удалён"}


@router.get("/my/participation")
async def get_my_participation(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    total_bids = await db.scalar(
        select(func.count()).select_from(Bid).where(Bid.user_id == current_user.id)
    )

    # My latest bid per auction in one query (Postgres DISTINCT ON).
    # Replaces the per-auction LIMIT-1 lookup that turned this endpoint
    # into N+1 for any active bidder.
    my_last_bids_sub = (
        select(
            Bid.auction_id.label("auction_id"),
            Bid.amount.label("my_amount"),
        )
        .where(Bid.user_id == current_user.id)
        .order_by(Bid.auction_id, Bid.timestamp.desc())
        .distinct(Bid.auction_id)
        .subquery()
    )
    participating_rows = (
        await db.execute(
            select(Auction, my_last_bids_sub.c.my_amount)
            .join(my_last_bids_sub, my_last_bids_sub.c.auction_id == Auction.id)
            .order_by(Auction.end_time.desc())
        )
    ).all()

    active_bids: list[dict] = []
    won_auctions: list[dict] = []
    lost_auctions: list[dict] = []
    for auction, my_amount in participating_rows:
        row = _participation_row(auction, my_amount)
        if auction.is_active:
            active_bids.append(row)
        elif auction.winner_id == current_user.id:
            won_auctions.append(row)
        else:
            lost_auctions.append(row)

    my_auctions = (
        await db.execute(
            select(Auction)
            .where(Auction.created_by == current_user.id)
            .order_by(Auction.is_active.desc(), Auction.start_time.desc())
        )
    ).scalars().all()

    # One aggregate for bid counts across all of my auctions.
    bid_counts: dict[int, int] = {}
    if my_auctions:
        bid_counts = dict(
            (await db.execute(
                select(Bid.auction_id, func.count(Bid.id))
                .where(Bid.auction_id.in_([a.id for a in my_auctions]))
                .group_by(Bid.auction_id)
            )).all()
        )

    created_auctions = [
        _created_lot_row(a, bid_counts.get(a.id, 0)) for a in my_auctions
    ]

    active_bids.sort(key=lambda x: x["time_remaining"])
    won_auctions.sort(key=lambda x: x["end_time"], reverse=True)
    lost_auctions.sort(key=lambda x: x["end_time"], reverse=True)

    return {
        "active_bids": active_bids,
        "won_auctions": won_auctions,
        "lost_auctions": lost_auctions,
        "created_auctions": created_auctions,
        "stats": {
            "total_bids": total_bids,
            "won_count": len(won_auctions),
            "active_count": len(active_bids),
            "created_count": len(my_auctions),
        },
    }
