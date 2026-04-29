def test_deposit_increases_balance(client, registered_user):
    response = client.post(
        "/api/deposit",
        json={"amount": 250.0},
        headers=registered_user["headers"],
    )
    assert response.status_code == 200
    assert response.json()["balance"] == 1250.0  # 1000 starting + 250


def test_withdraw_decreases_balance(client, registered_user):
    response = client.post(
        "/api/withdraw",
        json={"amount": 300.0},
        headers=registered_user["headers"],
    )
    assert response.status_code == 200
    assert response.json()["balance"] == 700.0


def test_withdraw_more_than_balance_rejected(client, registered_user):
    response = client.post(
        "/api/withdraw",
        json={"amount": 10000.0},
        headers=registered_user["headers"],
    )
    assert response.status_code == 400


def test_buy_now_completes_auction_and_transfers_funds(
    client, registered_user, second_user
):
    # Seller creates a BIN auction priced at $400.
    auction = client.post(
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
    ).json()

    # Buyer buys it.
    response = client.post(
        f"/api/auctions/{auction['id']}/buy-now",
        headers=second_user["headers"],
    )
    assert response.status_code == 200
    assert response.json()["price"] == 400.0

    # Auction should be completed with the buyer as winner.
    refreshed = client.get(f"/api/auctions/{auction['id']}").json()
    assert refreshed["is_active"] is False
    assert refreshed["is_completed"] is True
    assert refreshed["winner_id"] == second_user["user"]["id"]

    # Balances reflect the trade.
    buyer = client.get("/api/me", headers=second_user["headers"]).json()
    seller = client.get("/api/me", headers=registered_user["headers"]).json()
    assert buyer["balance"] == 600.0   # 1000 - 400
    assert seller["balance"] == 1400.0  # 1000 + 400


def test_buy_now_own_lot_rejected(client, registered_user):
    auction = client.post(
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
    ).json()

    response = client.post(
        f"/api/auctions/{auction['id']}/buy-now",
        headers=registered_user["headers"],
    )
    assert response.status_code == 400
