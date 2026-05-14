import asyncio


async def _create_auction(client, headers, **overrides):
    payload = {
        "title": "Bid test lot",
        "description": "...",
        "starting_price": 100.0,
        "duration_minutes": 60,
        "auction_type": "bid",
    }
    payload.update(overrides)
    response = await client.post("/api/auctions", json=payload, headers=headers)
    assert response.status_code == 200
    return response.json()


async def test_place_bid_increases_current_price(client, registered_user, second_user):
    auction = await _create_auction(client, registered_user["headers"])

    response = await client.post(
        "/api/bids",
        json={"auction_id": auction["id"], "amount": 150.0},
        headers=second_user["headers"],
    )
    assert response.status_code == 200

    refreshed = (await client.get(f"/api/auctions/{auction['id']}")).json()
    assert refreshed["current_price"] == 150.0
    assert refreshed["bids_count"] == 1


async def test_bid_on_bin_lot_rejected(client, registered_user, second_user):
    """BIN lots are fixed-price listings, not auctions — /bids must
    refuse them. Without this, a bidder could push current_price past
    bin_price while another user could still call /buy-now and grab the
    lot at the lower fixed price."""
    listing = (await client.post(
        "/api/auctions",
        json={
            "title": "Fixed-price lot",
            "description": "...",
            "starting_price": 100.0,
            "duration_minutes": 60,
            "auction_type": "bin",
            "bin_price": 250.0,
        },
        headers=registered_user["headers"],
    )).json()

    r = await client.post(
        "/api/bids",
        json={"auction_id": listing["id"], "amount": 300.0},
        headers=second_user["headers"],
    )
    assert r.status_code == 400
    assert "фиксированной" in r.json()["detail"].lower()


async def test_owner_cannot_bid_on_own_auction(client, registered_user):
    auction = await _create_auction(client, registered_user["headers"], starting_price=100.0)

    response = await client.post(
        "/api/bids",
        json={"auction_id": auction["id"], "amount": 200.0},
        headers=registered_user["headers"],
    )
    assert response.status_code == 400
    assert "свой" in response.json()["detail"].lower()


async def test_bid_below_current_price_rejected(client, registered_user, second_user):
    auction = await _create_auction(client, registered_user["headers"], starting_price=100.0)

    response = await client.post(
        "/api/bids",
        json={"auction_id": auction["id"], "amount": 50.0},
        headers=second_user["headers"],
    )
    assert response.status_code == 400


async def test_bid_equal_to_current_price_rejected(client, registered_user, second_user):
    auction = await _create_auction(client, registered_user["headers"], starting_price=100.0)

    response = await client.post(
        "/api/bids",
        json={"auction_id": auction["id"], "amount": 100.0},
        headers=second_user["headers"],
    )
    assert response.status_code == 400


async def test_bid_above_user_balance_rejected(client, registered_user, second_user):
    auction = await _create_auction(client, registered_user["headers"], starting_price=100.0)

    response = await client.post(
        "/api/bids",
        json={"auction_id": auction["id"], "amount": 5000.0},
        headers=second_user["headers"],
    )
    assert response.status_code == 400
    assert "средств" in response.json()["detail"].lower()


async def test_bid_outbid_replaces_leader(client, registered_user, second_user, third_user):
    auction = await _create_auction(client, registered_user["headers"], starting_price=100.0)

    first = await client.post(
        "/api/bids",
        json={"auction_id": auction["id"], "amount": 150.0},
        headers=second_user["headers"],
    )
    assert first.status_code == 200

    second = await client.post(
        "/api/bids",
        json={"auction_id": auction["id"], "amount": 200.0},
        headers=third_user["headers"],
    )
    assert second.status_code == 200

    refreshed = (await client.get(f"/api/auctions/{auction['id']}")).json()
    assert refreshed["current_price"] == 200.0
    assert refreshed["bids_count"] == 2


async def test_cannot_overcommit_balance_across_active_auctions(
    client, registered_user, second_user
):
    """A user with $1000 leading on a $700 auction can't also lead a
    $400 auction — the second bid would over-commit them ($1100 > $1000)."""
    a1 = await _create_auction(client, registered_user["headers"], title="Lot 1")
    a2 = await _create_auction(client, registered_user["headers"], title="Lot 2")

    r1 = await client.post(
        "/api/bids",
        json={"auction_id": a1["id"], "amount": 700.0},
        headers=second_user["headers"],
    )
    assert r1.status_code == 200

    r2 = await client.post(
        "/api/bids",
        json={"auction_id": a2["id"], "amount": 400.0},
        headers=second_user["headers"],
    )
    assert r2.status_code == 400
    assert "зарезервировано" in r2.json()["detail"].lower()


async def test_user_cannot_outbid_themselves(
    client, registered_user, second_user, third_user
):
    """Leading bidder can't raise their own bid — only another user
    breaking the leader's streak unlocks a fresh bid from them."""
    a1 = await _create_auction(client, registered_user["headers"])

    r1 = await client.post(
        "/api/bids",
        json={"auction_id": a1["id"], "amount": 500.0},
        headers=second_user["headers"],
    )
    assert r1.status_code == 200

    r2 = await client.post(
        "/api/bids",
        json={"auction_id": a1["id"], "amount": 800.0},
        headers=second_user["headers"],
    )
    assert r2.status_code == 400
    assert "лидиру" in r2.json()["detail"].lower()

    r3 = await client.post(
        "/api/bids",
        json={"auction_id": a1["id"], "amount": 600.0},
        headers=third_user["headers"],
    )
    assert r3.status_code == 200

    r4 = await client.post(
        "/api/bids",
        json={"auction_id": a1["id"], "amount": 900.0},
        headers=second_user["headers"],
    )
    assert r4.status_code == 200, r4.text


async def test_outbid_user_can_reuse_their_full_balance(
    client, registered_user, second_user, third_user
):
    third_headers = third_user["headers"]

    a1 = await _create_auction(client, registered_user["headers"], title="Lot 1")
    a2 = await _create_auction(client, registered_user["headers"], title="Lot 2")

    r1 = await client.post(
        "/api/bids",
        json={"auction_id": a1["id"], "amount": 700.0},
        headers=second_user["headers"],
    )
    assert r1.status_code == 200

    r2 = await client.post(
        "/api/bids",
        json={"auction_id": a1["id"], "amount": 750.0},
        headers=third_headers,
    )
    assert r2.status_code == 200

    r3 = await client.post(
        "/api/bids",
        json={"auction_id": a2["id"], "amount": 900.0},
        headers=second_user["headers"],
    )
    assert r3.status_code == 200, r3.text


async def test_concurrent_cross_auction_bids_respect_balance(
    client, registered_user, second_user
):
    """Same user fires two simultaneous bids on *different* auctions, each
    of which alone fits the balance but together over-commit it. The
    user-row ``SELECT ... FOR UPDATE`` in /bids must serialise them so
    only one passes the available-balance check."""
    a1 = await _create_auction(client, registered_user["headers"], title="Lot 1")
    a2 = await _create_auction(client, registered_user["headers"], title="Lot 2")

    r1, r2 = await asyncio.gather(
        client.post(
            "/api/bids",
            json={"auction_id": a1["id"], "amount": 700.0},
            headers=second_user["headers"],
        ),
        client.post(
            "/api/bids",
            json={"auction_id": a2["id"], "amount": 700.0},
            headers=second_user["headers"],
        ),
    )

    statuses = sorted([r1.status_code, r2.status_code])
    assert statuses == [200, 400], (r1.text, r2.text)


async def test_concurrent_equal_bids_only_one_wins(
    client, registered_user, second_user, third_user
):
    """Fire two equal bids on the same auction concurrently. The
    SELECT...FOR UPDATE row lock must serialise them so the second one
    fails the 'must be higher than current price' check instead of both
    silently winning."""
    third_headers = third_user["headers"]

    auction = await _create_auction(client, registered_user["headers"], starting_price=100.0)

    r_a, r_b = await asyncio.gather(
        client.post(
            "/api/bids",
            json={"auction_id": auction["id"], "amount": 150.0},
            headers=second_user["headers"],
        ),
        client.post(
            "/api/bids",
            json={"auction_id": auction["id"], "amount": 150.0},
            headers=third_headers,
        ),
    )

    statuses = sorted([r_a.status_code, r_b.status_code])
    assert statuses == [200, 400], (r_a.text, r_b.text)

    refreshed = (await client.get(f"/api/auctions/{auction['id']}")).json()
    assert refreshed["current_price"] == 150.0
    assert refreshed["bids_count"] == 1
