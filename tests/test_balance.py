import asyncio


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
    assert buyer["balance"] == 600.0
    assert seller["balance"] == 1400.0


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
    client, registered_user, second_user
):
    """Two simultaneous /buy-now on the same BIN lot must serialise via
    SELECT FOR UPDATE — only one buyer is debited and the seller is
    credited exactly once."""
    third_resp = await client.post("/api/register", json={
        "username": "carol",
        "email": "carol@example.com",
        "password": "password123",
    })
    third_headers = {"Authorization": f"Bearer {third_resp.json()['token']}"}

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
    # Seller starts at 1000, credited exactly once (+400), not twice.
    assert seller["balance"] == 1400.0
