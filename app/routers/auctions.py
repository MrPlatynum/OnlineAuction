from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

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
from app.schemas import AuctionCreate, AuctionResponse, PaginatedAuctionsResponse
from app.services.auctions import get_image_urls
from app.services.notifications import create_notification, notify_user
from app.services.transactions import add_transaction
from app.services.websocket_manager import manager
from app.utils.security import get_current_user
from app.utils.time import utcnow

router = APIRouter(prefix="/api", tags=["auctions"])


@router.post("/auctions", response_model=AuctionResponse)
def create_auction(
    auction: AuctionCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    start_time = utcnow()
    end_time = start_time + timedelta(minutes=auction.duration_minutes)

    db_auction = Auction(
        title=auction.title,
        description=auction.description,
        starting_price=auction.starting_price,
        current_price=auction.starting_price,
        image_url=auction.image_url,
        start_time=start_time,
        end_time=end_time,
        created_by=current_user.id,
        category_id=auction.category_id,
        auction_type=auction.auction_type or "bid",
        bin_price=auction.bin_price,
    )
    db.add(db_auction)
    db.commit()
    db.refresh(db_auction)

    all_urls = auction.image_urls or ([auction.image_url] if auction.image_url else [])
    for i, url in enumerate(all_urls):
        db.add(AuctionImage(auction_id=db_auction.id, url=url, order=i))
    if all_urls:
        db.commit()

    subscribers = (
        db.query(Subscription)
        .filter(Subscription.seller_id == current_user.id)
        .all()
    )
    for sub in subscribers:
        create_notification(
            db=db,
            user_id=sub.subscriber_id,
            notification_type=NotificationType.NEW_LOT,
            title="Новый лот",
            message=f"@{current_user.username} выставил новый лот: «{db_auction.title}»",
            auction_id=db_auction.id,
            auction_title=db_auction.title,
        )

    cat = (
        db.query(Category).filter(Category.id == db_auction.category_id).first()
        if db_auction.category_id
        else None
    )
    auction_dict = {
        "id": db_auction.id,
        "title": db_auction.title,
        "description": db_auction.description,
        "starting_price": db_auction.starting_price,
        "current_price": db_auction.current_price,
        "image_url": db_auction.image_url,
        "image_urls": all_urls,
        "start_time": db_auction.start_time,
        "end_time": db_auction.end_time,
        "is_active": db_auction.is_active,
        "is_completed": db_auction.is_completed,
        "winner_id": db_auction.winner_id,
        "created_by": db_auction.created_by,
        "creator_username": current_user.username,
        "creator_avatar_url": current_user.avatar_url,
        "time_remaining": max(0, int((db_auction.end_time - utcnow()).total_seconds())),
        "category_id": db_auction.category_id,
        "category_name": cat.name if cat else None,
        "category_icon": cat.icon if cat else None,
        "auction_type": auction.auction_type or "bid",
        "bin_price": auction.bin_price,
    }
    return AuctionResponse(**auction_dict)


@router.post("/auctions/{auction_id}/buy-now")
async def buy_now(
    auction_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    auction = db.query(Auction).filter(Auction.id == auction_id).first()
    if not auction:
        raise HTTPException(404, "Аукцион не найден")
    if not auction.is_active:
        raise HTTPException(400, "Аукцион завершён")
    if utcnow() > auction.end_time:
        auction.is_active = False
        db.commit()
        raise HTTPException(400, "Аукцион завершён")
    if auction.auction_type not in ("bin", "bid_bin"):
        raise HTTPException(400, "Этот аукцион не поддерживает покупку сразу")
    if not auction.bin_price:
        raise HTTPException(400, "Цена BIN не установлена")
    if auction.created_by == current_user.id:
        raise HTTPException(400, "Нельзя купить собственный лот")
    if current_user.balance < auction.bin_price:
        raise HTTPException(
            400,
            f"Недостаточно средств. Нужно ${auction.bin_price:.2f}, у вас ${current_user.balance:.2f}",
        )

    current_user.balance -= auction.bin_price
    add_transaction(
        db, current_user, "bin_purchase", auction.bin_price,
        f"Покупка «{auction.title}» по цене BIN", auction_id=auction.id,
    )
    auction.current_price = auction.bin_price
    auction.is_active = False
    auction.is_completed = True
    auction.winner_id = current_user.id
    auction.end_time = utcnow()

    creator_bin = db.query(User).filter(User.id == auction.created_by).first()
    if creator_bin:
        creator_bin.balance += auction.bin_price
        add_transaction(
            db, creator_bin, "auction_sale", auction.bin_price,
            f"Продажа «{auction.title}» по цене BIN", auction_id=auction.id,
        )
    db.commit()

    creator = db.query(User).filter(User.id == auction.created_by).first()
    if creator:
        await notify_user(
            db, creator, NotificationType.AUCTION_SOLD,
            "✅ Лот куплен по цене BIN",
            f"{current_user.username} купил «{auction.title}» за ${auction.bin_price:.2f}",
            auction.id, auction.title, manager,
        )

    return {"message": "Покупка совершена", "price": auction.bin_price}


@router.get("/auctions", response_model=PaginatedAuctionsResponse)
def get_auctions(
    page: int = Query(1, ge=1),
    page_size: int = Query(12, ge=1, le=50),
    status: str = Query("active", regex="^(active|completed|all)$"),
    search: Optional[str] = Query(None),
    min_price: Optional[float] = Query(None, ge=0),
    max_price: Optional[float] = Query(None, ge=0),
    sort_by: str = Query("time", regex="^(time|price_asc|price_desc)$"),
    created_by: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    auction_type: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    query = db.query(Auction)

    if status == "active":
        query = query.filter(Auction.is_active == True)
    elif status == "completed":
        query = query.filter(Auction.is_completed == True)

    if search:
        search_pattern = f"%{search}%"
        query = query.filter(
            (Auction.title.ilike(search_pattern))
            | (Auction.description.ilike(search_pattern))
        )

    if min_price is not None:
        query = query.filter(Auction.current_price >= min_price)

    if max_price is not None:
        query = query.filter(Auction.current_price <= max_price)

    if created_by:
        creator_user = db.query(User).filter(User.username == created_by).first()
        if creator_user:
            query = query.filter(Auction.created_by == creator_user.id)
        else:
            query = query.filter(Auction.id == -1)

    if category:
        cat_obj = db.query(Category).filter(Category.slug == category).first()
        if cat_obj:
            cat_ids = [cat_obj.id]
            children = db.query(Category).filter(Category.parent_id == cat_obj.id).all()
            cat_ids += [c.id for c in children]
            query = query.filter(Auction.category_id.in_(cat_ids))
        else:
            query = query.filter(Auction.id == -1)

    if auction_type == "bid":
        query = query.filter(Auction.auction_type == "bid")
    elif auction_type == "bin":
        query = query.filter(Auction.auction_type == "bin")

    total = query.count()
    total_pages = (total + page_size - 1) // page_size

    if sort_by == "time":
        query = query.order_by(Auction.end_time.asc())
    elif sort_by == "price_asc":
        query = query.order_by(Auction.current_price.asc())
    elif sort_by == "price_desc":
        query = query.order_by(Auction.current_price.desc())

    offset = (page - 1) * page_size
    auctions = query.offset(offset).limit(page_size).all()

    result = []
    for auction in auctions:
        bids_count = db.query(Bid).filter(Bid.auction_id == auction.id).count()
        creator = db.query(User).filter(User.id == auction.created_by).first()
        cat = (
            db.query(Category).filter(Category.id == auction.category_id).first()
            if auction.category_id
            else None
        )
        image_urls = get_image_urls(auction, db)
        auction_dict = {
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
        result.append(AuctionResponse(**auction_dict))

    return PaginatedAuctionsResponse(
        items=result,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get("/auctions/{auction_id}", response_model=AuctionResponse)
def get_auction(auction_id: int, db: Session = Depends(get_db)):
    auction = db.query(Auction).filter(Auction.id == auction_id).first()
    if not auction:
        raise HTTPException(status_code=404, detail="Auction not found")

    bids_count = db.query(Bid).filter(Bid.auction_id == auction_id).count()
    creator = db.query(User).filter(User.id == auction.created_by).first()
    cat = (
        db.query(Category).filter(Category.id == auction.category_id).first()
        if auction.category_id
        else None
    )
    image_urls = get_image_urls(auction, db)
    auction_dict = {
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
    return AuctionResponse(**auction_dict)


@router.patch("/auctions/{auction_id}")
async def update_auction(
    auction_id: int,
    data: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    auction = db.query(Auction).filter(Auction.id == auction_id).first()
    if not auction:
        raise HTTPException(404, "Аукцион не найден")
    if auction.created_by != current_user.id:
        raise HTTPException(403, "Это не ваш лот")

    has_bids = db.query(Bid).filter(Bid.auction_id == auction_id).count() > 0
    if has_bids:
        raise HTTPException(400, "Нельзя редактировать лот — на него уже есть ставки")

    if "title" in data and data["title"]:
        auction.title = data["title"].strip()
    if "description" in data:
        auction.description = data["description"].strip()
    if "category_id" in data:
        auction.category_id = data["category_id"]
    if "starting_price" in data and data["starting_price"]:
        auction.starting_price = float(data["starting_price"])
        auction.current_price = float(data["starting_price"])
    if "bin_price" in data:
        auction.bin_price = float(data["bin_price"]) if data["bin_price"] else None
    if "auction_type" in data:
        auction.auction_type = data["auction_type"]
    if "extend_minutes" in data and data["extend_minutes"] and auction.is_active:
        mins = int(data["extend_minutes"])
        if 1 <= mins <= 10080:
            auction.end_time = auction.end_time + timedelta(minutes=mins)
    if "image_urls" in data and isinstance(data["image_urls"], list):
        db.query(AuctionImage).filter(AuctionImage.auction_id == auction_id).delete()
        for i, url in enumerate(data["image_urls"]):
            db.add(AuctionImage(auction_id=auction_id, url=url, order=i))
        auction.image_url = data["image_urls"][0] if data["image_urls"] else None

    db.commit()
    db.refresh(auction)
    return {"message": "Лот обновлён", "id": auction.id}


@router.delete("/auctions/{auction_id}")
def delete_auction(
    auction_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    auction = db.query(Auction).filter(Auction.id == auction_id).first()
    if not auction:
        raise HTTPException(status_code=404, detail="Auction not found")
    if auction.created_by != current_user.id:
        raise HTTPException(status_code=403, detail="Нельзя удалить чужой лот")

    bids_count = db.query(Bid).filter(Bid.auction_id == auction_id).count()

    if auction.is_active and bids_count > 0:
        raise HTTPException(status_code=400, detail="Нельзя удалить активный лот со ставками")

    if auction.is_completed and auction.winner_id:
        raise HTTPException(status_code=400, detail="Нельзя удалить лот с победителем")

    db.delete(auction)
    db.commit()
    return {"message": "Лот удалён"}


@router.get("/my/participation")
def get_my_participation(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    my_bids = db.query(Bid).filter(Bid.user_id == current_user.id).all()
    auction_ids = list(set([bid.auction_id for bid in my_bids]))

    participating_auctions = (
        db.query(Auction)
        .filter(Auction.id.in_(auction_ids))
        .order_by(Auction.end_time.desc())
        .all()
        if auction_ids
        else []
    )

    active_bids = []
    won_auctions = []
    lost_auctions = []

    for auction in participating_auctions:
        my_last_bid = (
            db.query(Bid)
            .filter(Bid.auction_id == auction.id, Bid.user_id == current_user.id)
            .order_by(Bid.timestamp.desc())
            .first()
        )

        auction_data = {
            "auction_id": auction.id,
            "title": auction.title,
            "image_url": auction.image_url,
            "current_price": auction.current_price,
            "my_bid": my_last_bid.amount if my_last_bid else 0,
            "is_winning": auction.current_price == my_last_bid.amount if my_last_bid else False,
            "end_time": auction.end_time.isoformat(),
            "time_remaining": max(0, int((auction.end_time - utcnow()).total_seconds())),
            "is_active": auction.is_active,
            "auction_type": auction.auction_type or "bid",
        }

        if auction.is_active:
            active_bids.append(auction_data)
        elif auction.winner_id == current_user.id:
            won_auctions.append(auction_data)
        else:
            lost_auctions.append(auction_data)

    my_auctions = (
        db.query(Auction)
        .filter(Auction.created_by == current_user.id)
        .order_by(Auction.is_active.desc(), Auction.start_time.desc())
        .all()
    )
    created_auctions = []
    for auction in my_auctions:
        bids_count = db.query(Bid).filter(Bid.auction_id == auction.id).count()
        created_auctions.append({
            "auction_id": auction.id,
            "title": auction.title,
            "current_price": auction.current_price,
            "starting_price": auction.starting_price,
            "is_active": auction.is_active,
            "winner_id": auction.winner_id,
            "bids_count": bids_count,
            "image_url": auction.image_url,
            "end_time": auction.end_time.isoformat() if auction.end_time else None,
            "time_remaining": max(
                0, int((auction.end_time - utcnow()).total_seconds())
            ) if auction.end_time and auction.is_active else 0,
        })

    active_bids.sort(key=lambda x: x["time_remaining"])
    won_auctions.sort(key=lambda x: x["end_time"], reverse=True)
    lost_auctions.sort(key=lambda x: x["end_time"], reverse=True)

    return {
        "active_bids": active_bids,
        "won_auctions": won_auctions,
        "lost_auctions": lost_auctions,
        "created_auctions": created_auctions,
        "stats": {
            "total_bids": len(my_bids),
            "won_count": len(won_auctions),
            "active_count": len(active_bids),
            "created_count": len(my_auctions),
        },
    }
