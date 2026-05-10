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
