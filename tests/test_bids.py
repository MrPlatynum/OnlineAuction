def _create_auction(client, headers, **overrides):
    payload = {
        "title": "Bid test lot",
        "description": "...",
        "starting_price": 100.0,
        "duration_minutes": 60,
        "auction_type": "bid",
    }
    payload.update(overrides)
    response = client.post("/api/auctions", json=payload, headers=headers)
    assert response.status_code == 200
    return response.json()


def test_place_bid_increases_current_price(client, registered_user, second_user):
    auction = _create_auction(client, registered_user["headers"])

    response = client.post(
        "/api/bids",
        json={"auction_id": auction["id"], "amount": 150.0},
        headers=second_user["headers"],
    )
    assert response.status_code == 200

    refreshed = client.get(f"/api/auctions/{auction['id']}").json()
    assert refreshed["current_price"] == 150.0
    assert refreshed["bids_count"] == 1


def test_bid_below_current_price_rejected(client, registered_user, second_user):
    auction = _create_auction(client, registered_user["headers"], starting_price=100.0)

    response = client.post(
        "/api/bids",
        json={"auction_id": auction["id"], "amount": 50.0},
        headers=second_user["headers"],
    )
    assert response.status_code == 400


def test_bid_equal_to_current_price_rejected(client, registered_user, second_user):
    auction = _create_auction(client, registered_user["headers"], starting_price=100.0)

    response = client.post(
        "/api/bids",
        json={"auction_id": auction["id"], "amount": 100.0},
        headers=second_user["headers"],
    )
    assert response.status_code == 400


def test_bid_above_user_balance_rejected(client, registered_user, second_user):
    # second_user starts with $1000 balance.
    auction = _create_auction(client, registered_user["headers"], starting_price=100.0)

    response = client.post(
        "/api/bids",
        json={"auction_id": auction["id"], "amount": 5000.0},
        headers=second_user["headers"],
    )
    assert response.status_code == 400
    assert "balance" in response.json()["detail"].lower()


def test_bid_outbid_replaces_leader(client, registered_user, second_user):
    auction = _create_auction(client, registered_user["headers"], starting_price=100.0)

    first = client.post(
        "/api/bids",
        json={"auction_id": auction["id"], "amount": 150.0},
        headers=second_user["headers"],
    )
    assert first.status_code == 200

    second = client.post(
        "/api/bids",
        json={"auction_id": auction["id"], "amount": 200.0},
        headers=registered_user["headers"],
    )
    assert second.status_code == 200

    refreshed = client.get(f"/api/auctions/{auction['id']}").json()
    assert refreshed["current_price"] == 200.0
    assert refreshed["bids_count"] == 2


def test_cannot_overcommit_balance_across_active_auctions(
    client, registered_user, second_user
):
    """A user with $1000 leading on a $700 auction can't also lead a
    $400 auction — the second bid would over-commit them ($1100 > $1000)."""
    a1 = _create_auction(client, registered_user["headers"], title="Lot 1")
    a2 = _create_auction(client, registered_user["headers"], title="Lot 2")

    r1 = client.post(
        "/api/bids",
        json={"auction_id": a1["id"], "amount": 700.0},
        headers=second_user["headers"],
    )
    assert r1.status_code == 200

    r2 = client.post(
        "/api/bids",
        json={"auction_id": a2["id"], "amount": 400.0},
        headers=second_user["headers"],
    )
    assert r2.status_code == 400
    assert "available" in r2.json()["detail"].lower()


def test_user_can_raise_their_own_bid_within_balance(
    client, registered_user, second_user
):
    """Raising your own bid replaces the previous commitment, so it's
    fine as long as the new amount fits within balance."""
    a1 = _create_auction(client, registered_user["headers"])

    r1 = client.post(
        "/api/bids",
        json={"auction_id": a1["id"], "amount": 500.0},
        headers=second_user["headers"],
    )
    assert r1.status_code == 200

    r2 = client.post(
        "/api/bids",
        json={"auction_id": a1["id"], "amount": 800.0},
        headers=second_user["headers"],
    )
    assert r2.status_code == 200, r2.text


def test_outbid_user_can_reuse_their_full_balance(client, registered_user, second_user):
    """If user is outbid, their previous commitment is released and
    they can use their full balance again on a different auction."""
    third = client.post("/api/register", json={
        "username": "carol",
        "email": "carol@example.com",
        "password": "password123",
    }).json()
    third_headers = {"Authorization": f"Bearer {third['token']}"}

    a1 = _create_auction(client, registered_user["headers"], title="Lot 1")
    a2 = _create_auction(client, registered_user["headers"], title="Lot 2")

    # second_user (alice's twin bob) bids $700 on a1 and is now leading.
    r1 = client.post(
        "/api/bids",
        json={"auction_id": a1["id"], "amount": 700.0},
        headers=second_user["headers"],
    )
    assert r1.status_code == 200

    # carol outbids on a1 with $750 (within carol's $1000 budget).
    r2 = client.post(
        "/api/bids",
        json={"auction_id": a1["id"], "amount": 750.0},
        headers=third_headers,
    )
    assert r2.status_code == 200

    # Now bob's commitment on a1 is gone — he can spend full $1000 on a2.
    r3 = client.post(
        "/api/bids",
        json={"auction_id": a2["id"], "amount": 900.0},
        headers=second_user["headers"],
    )
    assert r3.status_code == 200, r3.text
