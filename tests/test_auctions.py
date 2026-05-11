def _make_auction_payload(**overrides):
    payload = {
        "title": "Test lot",
        "description": "Test description",
        "starting_price": 100.0,
        "duration_minutes": 60,
        "auction_type": "bid",
    }
    payload.update(overrides)
    return payload


async def test_create_auction_authenticated(client, registered_user):
    response = await client.post(
        "/api/auctions",
        json=_make_auction_payload(),
        headers=registered_user["headers"],
    )
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Test lot"
    assert body["starting_price"] == 100.0
    assert body["current_price"] == 100.0
    assert body["created_by"] == registered_user["user"]["id"]
    assert body["is_active"] is True


async def test_create_auction_unauthenticated(client):
    response = await client.post("/api/auctions", json=_make_auction_payload())
    assert response.status_code == 401


async def test_get_auction_by_id(client, registered_user):
    create = await client.post(
        "/api/auctions",
        json=_make_auction_payload(title="Lookup test"),
        headers=registered_user["headers"],
    )
    auction_id = create.json()["id"]

    response = await client.get(f"/api/auctions/{auction_id}")
    assert response.status_code == 200
    assert response.json()["title"] == "Lookup test"


async def test_get_nonexistent_auction_returns_404(client):
    response = await client.get("/api/auctions/99999")
    assert response.status_code == 404


async def test_javascript_image_url_rejected(client, registered_user):
    """``image_url=javascript:...`` must 422 — server-side defence
    against stored-XSS via lot images, on top of client-side escape."""
    r = await client.post(
        "/api/auctions",
        json=_make_auction_payload(image_url="javascript:alert(1)"),
        headers=registered_user["headers"],
    )
    assert r.status_code == 422


async def test_data_image_url_in_array_rejected(client, registered_user):
    r = await client.post(
        "/api/auctions",
        json=_make_auction_payload(
            image_urls=["/static/uploads/ok.jpg", "data:text/html,<script>x</script>"]
        ),
        headers=registered_user["headers"],
    )
    assert r.status_code == 422


async def test_relative_and_absolute_image_urls_accepted(client, registered_user):
    """Both ``/static/...`` and ``https://...`` should pass."""
    r = await client.post(
        "/api/auctions",
        json=_make_auction_payload(
            image_url="/static/uploads/foo.jpg",
            image_urls=["/static/uploads/foo.jpg", "https://cdn.example/bar.png"],
        ),
        headers=registered_user["headers"],
    )
    assert r.status_code == 200, r.text


async def _seed_active_auction(client, headers, **overrides):
    response = await client.post(
        "/api/auctions",
        json=_make_auction_payload(**overrides),
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_update_auction_owner_can_edit_when_no_bids(client, registered_user):
    auction = await _seed_active_auction(client, registered_user["headers"])
    response = await client.patch(
        f"/api/auctions/{auction['id']}",
        json={"title": "Renamed", "description": "Updated"},
        headers=registered_user["headers"],
    )
    assert response.status_code == 200, response.text
    refreshed = (await client.get(f"/api/auctions/{auction['id']}")).json()
    assert refreshed["title"] == "Renamed"
    assert refreshed["description"] == "Updated"


async def test_update_auction_non_owner_forbidden(client, registered_user, second_user):
    auction = await _seed_active_auction(client, registered_user["headers"])
    response = await client.patch(
        f"/api/auctions/{auction['id']}",
        json={"title": "Hijacked"},
        headers=second_user["headers"],
    )
    assert response.status_code == 403


async def test_update_auction_not_found(client, registered_user):
    response = await client.patch(
        "/api/auctions/99999",
        json={"title": "x"},
        headers=registered_user["headers"],
    )
    assert response.status_code == 404


async def test_update_auction_rejects_inactive_lot(client, registered_user):
    """Once a lot is settled, no further field edits are permitted —
    otherwise the seller could rewrite history of a sold item."""
    from sqlalchemy import update

    from app import database as _db_module
    from app.models import Auction

    auction = await _seed_active_auction(client, registered_user["headers"])
    async with _db_module.SessionLocal() as db:
        await db.execute(
            update(Auction)
            .where(Auction.id == auction["id"])
            .values(is_active=False, is_completed=True)
        )
        await db.commit()

    response = await client.patch(
        f"/api/auctions/{auction['id']}",
        json={"title": "Renamed"},
        headers=registered_user["headers"],
    )
    assert response.status_code == 400


async def test_update_auction_blocks_field_edit_when_bids_exist(
    client, registered_user, second_user
):
    auction = await _seed_active_auction(client, registered_user["headers"])
    bid = await client.post(
        "/api/bids",
        json={"auction_id": auction["id"], "amount": 150.0},
        headers=second_user["headers"],
    )
    assert bid.status_code == 200

    response = await client.patch(
        f"/api/auctions/{auction['id']}",
        json={"title": "Bait and switch"},
        headers=registered_user["headers"],
    )
    assert response.status_code == 400


async def test_update_auction_extend_minutes_allowed_with_bids(
    client, registered_user, second_user
):
    """Extending the deadline is the one edit safe to allow after a bid
    landed — a longer auction never harms an existing bidder."""
    auction = await _seed_active_auction(client, registered_user["headers"])
    bid = await client.post(
        "/api/bids",
        json={"auction_id": auction["id"], "amount": 150.0},
        headers=second_user["headers"],
    )
    assert bid.status_code == 200

    before = (await client.get(f"/api/auctions/{auction['id']}")).json()
    response = await client.patch(
        f"/api/auctions/{auction['id']}",
        json={"extend_minutes": 30},
        headers=registered_user["headers"],
    )
    assert response.status_code == 200, response.text
    after = (await client.get(f"/api/auctions/{auction['id']}")).json()
    assert after["end_time"] > before["end_time"]


async def test_list_auctions_paginated(client, registered_user):
    for i in range(3):
        await client.post(
            "/api/auctions",
            json=_make_auction_payload(title=f"Lot {i}"),
            headers=registered_user["headers"],
        )

    response = await client.get("/api/auctions")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert len(body["items"]) == 3


async def test_bin_lot_seeds_current_price_from_bin_price(client, registered_user):
    """A BIN listing is a fixed-price sale: starting_price is meaningless.
    Whatever the form submits as starting_price, the server must seed
    current_price from bin_price — otherwise the listing card shows one
    number ($100) and /buy-now charges another ($300)."""
    listing = (await client.post(
        "/api/auctions",
        json={
            "title": "Fixed-price seed test",
            "description": "...",
            "starting_price": 100.0,
            "duration_minutes": 60,
            "auction_type": "bin",
            "bin_price": 300.0,
        },
        headers=registered_user["headers"],
    )).json()

    assert listing["starting_price"] == 300.0
    assert listing["current_price"] == 300.0
    assert listing["bin_price"] == 300.0


async def test_update_bin_price_syncs_current_price(client, registered_user):
    """PATCH bin_price on a BIN listing must drag current_price along —
    otherwise the listing card still shows the old number while
    /buy-now charges the new one (and `auction.current_price` is the
    figure the listing renders)."""
    listing = (await client.post(
        "/api/auctions",
        json={
            "title": "Fixed-price update test",
            "description": "...",
            "starting_price": 200.0,
            "duration_minutes": 60,
            "auction_type": "bin",
            "bin_price": 200.0,
        },
        headers=registered_user["headers"],
    )).json()
    assert listing["current_price"] == 200.0

    r = await client.patch(
        f"/api/auctions/{listing['id']}",
        json={"bin_price": 450.0},
        headers=registered_user["headers"],
    )
    assert r.status_code == 200, r.text

    refreshed = (await client.get(f"/api/auctions/{listing['id']}")).json()
    assert refreshed["bin_price"] == 450.0
    assert refreshed["current_price"] == 450.0
    assert refreshed["starting_price"] == 450.0


async def test_buy_now_past_end_time_defers_to_scheduler(
    client, registered_user, second_user
):
    """A /buy-now arriving after end_time but before the scheduler tick
    must reject (400) without mutating auction state. complete_auction
    is the single path that finalises a lot — flipping is_active or
    is_completed from the handler short-circuits its later tick. BIN
    lots reject bids (fixed-price), so the test exercises the empty-lot
    case where the scheduler should still close the listing cleanly."""
    from datetime import timedelta

    from sqlalchemy import select

    from app import database as _db_module
    from app.models import Auction
    from app.services.auction_scheduler import cancel_auction
    from app.services.auctions import complete_auction
    from app.utils.time import utcnow

    create = await client.post(
        "/api/auctions",
        json=_make_auction_payload(
            auction_type="bin", bin_price=300.0, duration_minutes=60,
        ),
        headers=registered_user["headers"],
    )
    auction_id = create.json()["id"]

    cancel_auction(auction_id)
    async with _db_module.SessionLocal() as db:
        auc = (
            await db.execute(select(Auction).where(Auction.id == auction_id))
        ).scalar_one()
        auc.end_time = utcnow() - timedelta(seconds=10)
        await db.commit()

    response = await client.post(
        f"/api/auctions/{auction_id}/buy-now",
        headers=second_user["headers"],
    )
    assert response.status_code == 400

    refreshed = (await client.get(f"/api/auctions/{auction_id}")).json()
    assert refreshed["is_active"] is True
    assert refreshed["is_completed"] is False
    assert refreshed["winner_id"] is None

    async with _db_module.SessionLocal() as db:
        await complete_auction(auction_id, db)

    settled = (await client.get(f"/api/auctions/{auction_id}")).json()
    assert settled["is_active"] is False
    assert settled["is_completed"] is True
    assert settled["winner_id"] is None


async def test_late_bid_past_end_time_defers_to_scheduler(
    client, registered_user, second_user, third_user
):
    """A /api/bids arriving after end_time but before the scheduler tick
    must reject (400) without mutating auction state. Previously the
    handler set is_active=False here, which then made complete_auction's
    own is_active guard skip the lot — stranding the leading bidder
    with no payout."""
    from datetime import timedelta

    from sqlalchemy import select

    from app import database as _db_module
    from app.models import Auction
    from app.services.auction_scheduler import cancel_auction
    from app.services.auctions import complete_auction
    from app.utils.time import utcnow

    create = await client.post(
        "/api/auctions",
        json=_make_auction_payload(starting_price=100.0, duration_minutes=60),
        headers=registered_user["headers"],
    )
    auction_id = create.json()["id"]

    leader_bid = await client.post(
        "/api/bids",
        json={"auction_id": auction_id, "amount": 250.0},
        headers=second_user["headers"],
    )
    assert leader_bid.status_code == 200, leader_bid.text

    cancel_auction(auction_id)
    async with _db_module.SessionLocal() as db:
        auc = (
            await db.execute(select(Auction).where(Auction.id == auction_id))
        ).scalar_one()
        auc.end_time = utcnow() - timedelta(seconds=10)
        await db.commit()

    late = await client.post(
        "/api/bids",
        json={"auction_id": auction_id, "amount": 300.0},
        headers=third_user["headers"],
    )
    assert late.status_code == 400

    refreshed = (await client.get(f"/api/auctions/{auction_id}")).json()
    assert refreshed["is_active"] is True
    assert refreshed["is_completed"] is False

    async with _db_module.SessionLocal() as db:
        await complete_auction(auction_id, db)

    settled = (await client.get(f"/api/auctions/{auction_id}")).json()
    assert settled["is_active"] is False
    assert settled["is_completed"] is True
    assert settled["winner_id"] == second_user["user"]["id"]
    assert settled["current_price"] == 250.0

    bidder = (await client.get("/api/me", headers=second_user["headers"])).json()
    seller = (await client.get("/api/me", headers=registered_user["headers"])).json()
    assert bidder["balance"] == 1000.0 - 250.0
    assert seller["balance"] == 1000.0 + 250.0


async def test_delete_own_empty_auction_succeeds(client, registered_user):
    """Auction with no bids and no winner: the owner can delete it.
    Cleans up the in-memory scheduler task as a side-effect."""
    from app.services.auction_scheduler import _completion_tasks

    create = await client.post(
        "/api/auctions",
        json=_make_auction_payload(),
        headers=registered_user["headers"],
    )
    auction_id = create.json()["id"]
    assert auction_id in _completion_tasks

    r = await client.delete(
        f"/api/auctions/{auction_id}", headers=registered_user["headers"]
    )
    assert r.status_code == 200, r.text
    assert auction_id not in _completion_tasks

    refreshed = await client.get(f"/api/auctions/{auction_id}")
    assert refreshed.status_code == 404


async def test_delete_others_auction_forbidden(client, registered_user, second_user):
    create = await client.post(
        "/api/auctions",
        json=_make_auction_payload(),
        headers=registered_user["headers"],
    )
    auction_id = create.json()["id"]

    r = await client.delete(
        f"/api/auctions/{auction_id}", headers=second_user["headers"]
    )
    assert r.status_code == 403


async def test_delete_active_auction_with_bids_rejected(
    client, registered_user, second_user
):
    create = await client.post(
        "/api/auctions",
        json=_make_auction_payload(starting_price=100.0),
        headers=registered_user["headers"],
    )
    auction_id = create.json()["id"]

    bid = await client.post(
        "/api/bids",
        json={"auction_id": auction_id, "amount": 150.0},
        headers=second_user["headers"],
    )
    assert bid.status_code == 200

    r = await client.delete(
        f"/api/auctions/{auction_id}", headers=registered_user["headers"]
    )
    assert r.status_code == 400


async def test_delete_nonexistent_auction_returns_404(client, registered_user):
    r = await client.delete(
        "/api/auctions/99999", headers=registered_user["headers"]
    )
    assert r.status_code == 404


async def test_delete_unauthenticated_rejected(client, registered_user):
    create = await client.post(
        "/api/auctions",
        json=_make_auction_payload(),
        headers=registered_user["headers"],
    )
    r = await client.delete(f"/api/auctions/{create.json()['id']}")
    assert r.status_code == 401
