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
