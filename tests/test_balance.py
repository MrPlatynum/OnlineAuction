import asyncio

from sqlalchemy import select

from app import database as _db_module
from app.models import Auction
from app.utils.time import utcnow


async def test_deposit_increases_balance(client, registered_user):
    response = await client.post(
        "/api/deposit",
        json={"amount": 250.0},
        headers=registered_user["headers"],
    )
    assert response.status_code == 200
    assert response.json()["balance"] == 1250.0


async def test_withdraw_decreases_balance(client, registered_user):
    response = await client.post(
        "/api/withdraw",
        json={"amount": 300.0},
        headers=registered_user["headers"],
    )
    assert response.status_code == 200
    assert response.json()["balance"] == 700.0


async def test_withdraw_more_than_balance_rejected(client, registered_user):
    response = await client.post(
        "/api/withdraw",
        json={"amount": 10000.0},
        headers=registered_user["headers"],
    )
    assert response.status_code == 400


async def test_buy_now_completes_auction_and_transfers_funds(
    client, registered_user, second_user
):
    auction = (await client.post(
        "/api/auctions",
        json={
            "title": "Instant buy lot",
            "description": "...",
            "starting_price": 100.0,
            "duration_minutes": 60,
            "auction_type": "bin",
            "bin_price": 400.0,
        },
        headers=registered_user["headers"],
    )).json()

    response = await client.post(
        f"/api/auctions/{auction['id']}/buy-now",
        headers=second_user["headers"],
    )
    assert response.status_code == 200
    assert response.json()["price"] == 400.0

    refreshed = (await client.get(f"/api/auctions/{auction['id']}")).json()
    assert refreshed["is_active"] is False
    assert refreshed["is_completed"] is True
    assert refreshed["winner_id"] == second_user["user"]["id"]

    buyer = (await client.get("/api/me", headers=second_user["headers"])).json()
    seller = (await client.get("/api/me", headers=registered_user["headers"])).json()
    # Buyer pays the full BIN price (400 ₽). Seller receives the gross
    # 400 ₽ minus 7% platform commission = 372 ₽ net. Starting balance
    # is 1000 ₽ on both sides.
    assert buyer["balance"] == 600.0
    assert seller["balance"] == 1372.0


async def test_buy_now_own_lot_rejected(client, registered_user):
    auction = (await client.post(
        "/api/auctions",
        json={
            "title": "Self-buy",
            "description": "...",
            "starting_price": 100.0,
            "duration_minutes": 60,
            "auction_type": "bin",
            "bin_price": 200.0,
        },
        headers=registered_user["headers"],
    )).json()

    response = await client.post(
        f"/api/auctions/{auction['id']}/buy-now",
        headers=registered_user["headers"],
    )
    assert response.status_code == 400


async def test_withdraw_respects_committed_balance(client, registered_user, second_user):
    """A user leading on an auction has those funds locked. /withdraw
    used to ignore that and let the balance go effectively negative once
    the auction settled — now it subtracts committed-balance up-front."""
    auction = (await client.post(
        "/api/auctions",
        json={
            "title": "Lot",
            "description": "...",
            "starting_price": 100.0,
            "duration_minutes": 60,
            "auction_type": "bid",
        },
        headers=registered_user["headers"],
    )).json()

    # bob has $1000, bids $700 — committed = $700, available = $300.
    bid = await client.post(
        "/api/bids",
        json={"auction_id": auction["id"], "amount": 700.0},
        headers=second_user["headers"],
    )
    assert bid.status_code == 200

    # Try to withdraw $500 — only $300 is actually free. Used to succeed.
    r_blocked = await client.post(
        "/api/withdraw",
        json={"amount": 500.0},
        headers=second_user["headers"],
    )
    assert r_blocked.status_code == 400
    assert "удерж" in r_blocked.json()["detail"].lower()

    # Withdrawing $300 (all that's free) succeeds.
    r_ok = await client.post(
        "/api/withdraw",
        json={"amount": 300.0},
        headers=second_user["headers"],
    )
    assert r_ok.status_code == 200, r_ok.text
    assert r_ok.json()["balance"] == 700.0


async def test_concurrent_deposits_all_apply(client, registered_user):
    """Two parallel /deposit calls on the same account must both apply.
    The row lock serialises the read-add-write so neither update is
    lost to a 'last writer wins' race."""
    headers = registered_user["headers"]
    starting = (await client.get("/api/me", headers=headers)).json()["balance"]

    r_a, r_b = await asyncio.gather(
        client.post("/api/deposit", json={"amount": 100.0}, headers=headers),
        client.post("/api/deposit", json={"amount": 50.0}, headers=headers),
    )
    assert r_a.status_code == 200, r_a.text
    assert r_b.status_code == 200, r_b.text

    me = (await client.get("/api/me", headers=headers)).json()
    assert me["balance"] == starting + 150.0


async def test_concurrent_buy_now_only_one_succeeds(
    client, registered_user, second_user, third_user
):
    """Two simultaneous /buy-now on the same BIN lot must serialise via
    SELECT FOR UPDATE — only one buyer is debited and the seller is
    credited exactly once."""
    third_headers = third_user["headers"]

    auction = (await client.post(
        "/api/auctions",
        json={
            "title": "Race lot",
            "description": "...",
            "starting_price": 100.0,
            "duration_minutes": 60,
            "auction_type": "bin",
            "bin_price": 400.0,
        },
        headers=registered_user["headers"],
    )).json()

    r_a, r_b = await asyncio.gather(
        client.post(
            f"/api/auctions/{auction['id']}/buy-now",
            headers=second_user["headers"],
        ),
        client.post(
            f"/api/auctions/{auction['id']}/buy-now",
            headers=third_headers,
        ),
    )
    statuses = sorted([r_a.status_code, r_b.status_code])
    assert statuses == [200, 400], (r_a.text, r_b.text)

    seller = (await client.get("/api/me", headers=registered_user["headers"])).json()
    # Seller starts at 1000, credited exactly once (+400 gross, −28
    # commission at 7% = +372 net), not twice.
    assert seller["balance"] == 1372.0


async def test_deposit_beyond_max_balance_rejected(client, registered_user):
    """A user firing /deposit at rate-limit ceiling could push their
    balance past Numeric(12, 2)'s 9_999_999_999.99 max — the column
    would overflow with an opaque DataError. Cap the visible balance
    instead so the failure is a clean 400."""
    from sqlalchemy import update

    from app.database import SessionLocal
    from app.models import User
    from app.routers.balance import MAX_USER_BALANCE

    # Force the account near the cap so a single deposit puts it over.
    async with SessionLocal() as db:
        await db.execute(
            update(User)
            .where(User.id == registered_user["user"]["id"])
            .values(balance=MAX_USER_BALANCE - 100)
        )
        await db.commit()

    r = await client.post(
        "/api/deposit",
        json={"amount": 200.0},
        headers=registered_user["headers"],
    )
    assert r.status_code == 400
    assert "Максимальный" in r.json()["detail"] or "макс" in r.json()["detail"].lower()


# -- GET /api/transactions -- ------------------------------------------------

async def test_transactions_returns_deposit_record(client, registered_user):
    # Registration grants a starting balance; capture it so assertions
    # hold whether or not that grant writes a sibling Transaction row.
    starting_balance = registered_user["user"]["balance"]
    await client.post(
        "/api/deposit", json={"amount": 100.0}, headers=registered_user["headers"]
    )
    r = await client.get("/api/transactions", headers=registered_user["headers"])
    assert r.status_code == 200
    body = r.json()
    assert body["balance"] == starting_balance + 100.0
    assert body["page"] == 1
    # Newest first — the deposit we just made is item 0 regardless of
    # any starting-balance grant.
    deposit_txn = body["items"][0]
    assert deposit_txn["type"] == "deposit"
    assert deposit_txn["amount"] == 100.0
    assert deposit_txn["balance_after"] == starting_balance + 100.0
    assert "created_at" in deposit_txn


async def test_transactions_pagination(client, registered_user):
    # Five fresh deposits — we assert on the page size, not on absolute
    # ``total``, because a starting-balance grant may or may not seed a
    # Transaction row depending on registration logic.
    for amount in (10.0, 20.0, 30.0, 40.0, 50.0):
        await client.post(
            "/api/deposit",
            json={"amount": amount},
            headers=registered_user["headers"],
        )
    r = await client.get(
        "/api/transactions?page=1&page_size=2",
        headers=registered_user["headers"],
    )
    body = r.json()
    assert body["total"] >= 5
    assert len(body["items"]) == 2


async def test_transactions_requires_auth(client):
    r = await client.get("/api/transactions")
    assert r.status_code == 401


# -- Platform commission (seller side) -- ------------------------------------

async def test_bin_purchase_writes_commission_row(client, registered_user, second_user):
    """A settled BIN sale writes three transactions: bin_purchase on the
    buyer, auction_sale on the seller (gross), and commission on the
    seller (the 7% platform cut). The seller's last two rows must sum
    to the net payout (sale price × 0.93)."""
    auction = (await client.post(
        "/api/auctions",
        json={
            "title": "Comm BIN",
            "description": "...",
            "starting_price": 100.0,
            "duration_minutes": 60,
            "auction_type": "bin",
            "bin_price": 1000.0,
        },
        headers=registered_user["headers"],
    )).json()

    r = await client.post(
        f"/api/auctions/{auction['id']}/buy-now",
        headers=second_user["headers"],
    )
    assert r.status_code == 200

    seller_tx = (
        await client.get("/api/transactions", headers=registered_user["headers"])
    ).json()
    types = [t["type"] for t in seller_tx["items"][:2]]
    # Newest first — commission is the second move on the seller side.
    assert types == ["commission", "auction_sale"]
    commission_row = seller_tx["items"][0]
    sale_row = seller_tx["items"][1]
    assert commission_row["amount"] == 70.0     # 7% of 1000
    assert sale_row["amount"] == 1000.0
    assert sale_row["balance_after"] == 2000.0  # 1000 starting + 1000 gross
    assert commission_row["balance_after"] == 1930.0  # − 70 commission


async def test_completed_auction_writes_commission_row(
    client, registered_user, second_user
):
    """Same as the BIN path but for the bid-auction settle path
    (complete_auction in app/services/auctions.py). The 7% deduction
    applies to the winning bid amount."""
    from datetime import timedelta

    from app.services.auctions import complete_auction

    auction = (await client.post(
        "/api/auctions",
        json={
            "title": "Comm auction",
            "description": "...",
            "starting_price": 100.0,
            "duration_minutes": 60,
            "auction_type": "bid",
        },
        headers=registered_user["headers"],
    )).json()

    await client.post(
        "/api/bids",
        json={"auction_id": auction["id"], "amount": 500.0},
        headers=second_user["headers"],
    )

    # Force end_time into the past, then drive settle directly. Avoids
    # waiting on the real scheduler tick.
    async with _db_module.SessionLocal() as db:
        auc = (
            await db.execute(select(Auction).where(Auction.id == auction["id"]))
        ).scalar_one()
        auc.end_time = utcnow() - timedelta(seconds=5)
        await db.commit()
    async with _db_module.SessionLocal() as db:
        await complete_auction(auction["id"], db)

    seller_tx = (
        await client.get("/api/transactions", headers=registered_user["headers"])
    ).json()
    types = [t["type"] for t in seller_tx["items"][:2]]
    assert types == ["commission", "auction_sale"]
    assert seller_tx["items"][0]["amount"] == 35.0      # 7% of 500
    assert seller_tx["items"][1]["amount"] == 500.0


async def test_platform_endpoint_exposes_commission_rate(client):
    """The home page's hero strip and the auction page's owner-only
    payout hint both fetch /api/platform on load. The value must be
    a number so the JS Math doesn't blow up."""
    r = await client.get("/api/platform")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["commission_percent"], (int, float))
    assert body["commission_percent"] > 0
