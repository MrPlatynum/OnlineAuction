"""Reviews router — leave / list / delete seller reviews."""


async def _buy_from_seller(client, seller_headers, buyer_headers, *, bin_price=200, title="Lot"):
    """Create a BIN auction by ``seller`` and have ``buyer`` purchase
    it. Returns the auction id. Required setup for any review — the
    handler now requires the reviewer to have actually transacted with
    the seller."""
    auction = (await client.post(
        "/api/auctions",
        json={
            "title": title,
            "description": "...",
            "starting_price": 100.0,
            "duration_minutes": 60,
            "auction_type": "bin",
            "bin_price": bin_price,
        },
        headers=seller_headers,
    )).json()
    r = await client.post(
        f"/api/auctions/{auction['id']}/buy-now",
        headers=buyer_headers,
    )
    assert r.status_code == 200, r.text
    return auction["id"]


async def test_create_review_for_seller(client, registered_user, second_user):
    auction_id = await _buy_from_seller(
        client, registered_user["headers"], second_user["headers"]
    )
    payload = {
        "seller_id": registered_user["user"]["id"],
        "auction_id": auction_id,
        "rating": 5,
        "comment": "Отличный продавец",
    }
    r = await client.post("/api/reviews", json=payload, headers=second_user["headers"])
    assert r.status_code == 200
    assert "id" in r.json()


async def test_review_without_purchase_rejected(
    client, registered_user, second_user
):
    """Second user has never won anything from registered_user — must 403
    even when a real auction id is supplied."""
    auction_id = (await client.post(
        "/api/auctions",
        json={
            "title": "Untouched lot",
            "description": "...",
            "starting_price": 100.0,
            "duration_minutes": 60,
            "auction_type": "bid",
        },
        headers=registered_user["headers"],
    )).json()["id"]
    payload = {
        "seller_id": registered_user["user"]["id"],
        "auction_id": auction_id,
        "rating": 5,
    }
    r = await client.post("/api/reviews", json=payload, headers=second_user["headers"])
    assert r.status_code == 403


async def test_review_on_self_rejected(client, registered_user):
    payload = {
        "seller_id": registered_user["user"]["id"],
        "auction_id": 1,
        "rating": 5,
    }
    r = await client.post("/api/reviews", json=payload, headers=registered_user["headers"])
    assert r.status_code == 400


async def test_review_on_unknown_seller_returns_404(client, second_user):
    r = await client.post(
        "/api/reviews",
        json={"seller_id": 999_999, "auction_id": 1, "rating": 4},
        headers=second_user["headers"],
    )
    assert r.status_code == 404


async def test_review_without_auction_id_is_422(
    client, registered_user, second_user
):
    """auction_id is required: omitting it must fail at Pydantic — the
    field used to be optional, which let one reviewer post unlimited
    reviews on the same seller (the (reviewer_id, auction_id) UNIQUE
    constraint treats NULLs as distinct in Postgres)."""
    r = await client.post(
        "/api/reviews",
        json={"seller_id": registered_user["user"]["id"], "rating": 5},
        headers=second_user["headers"],
    )
    assert r.status_code == 422


async def test_rating_outside_1_5_rejected(client, registered_user, second_user):
    """Pydantic Field(ge=1, le=5) — 0 / 6 must be rejected before the
    handler runs."""
    for bad in (0, 6, 99):
        r = await client.post(
            "/api/reviews",
            json={"seller_id": registered_user["user"]["id"], "auction_id": 1, "rating": bad},
            headers=second_user["headers"],
        )
        assert r.status_code == 422, bad


async def test_duplicate_review_on_same_auction_rejected(
    client, registered_user, second_user
):
    """The handler explicitly forbids leaving two reviews from the
    same reviewer on the same auction (avoids review-bombing)."""
    auction_id = await _buy_from_seller(
        client, registered_user["headers"], second_user["headers"]
    )
    base = {
        "seller_id": registered_user["user"]["id"],
        "auction_id": auction_id,
        "rating": 5,
    }
    r1 = await client.post("/api/reviews", json=base, headers=second_user["headers"])
    assert r1.status_code == 200
    r2 = await client.post("/api/reviews", json=base, headers=second_user["headers"])
    assert r2.status_code == 400


async def test_delete_own_review_works(client, registered_user, second_user):
    seller_id = registered_user["user"]["id"]
    auction_id = await _buy_from_seller(
        client, registered_user["headers"], second_user["headers"]
    )
    created = (await client.post(
        "/api/reviews",
        json={"seller_id": seller_id, "auction_id": auction_id, "rating": 4},
        headers=second_user["headers"],
    )).json()

    r = await client.delete(
        f"/api/reviews/{created['id']}",
        headers=second_user["headers"],
    )
    assert r.status_code == 200


async def test_delete_someone_elses_review_forbidden(
    client, registered_user, second_user
):
    """403 (not 404) on someone else's review — leaks existence but
    distinguishes ownership, which is the documented behaviour."""
    seller_id = registered_user["user"]["id"]
    auction_id = await _buy_from_seller(
        client, registered_user["headers"], second_user["headers"]
    )
    created = (await client.post(
        "/api/reviews",
        json={"seller_id": seller_id, "auction_id": auction_id, "rating": 4},
        headers=second_user["headers"],
    )).json()

    r = await client.delete(
        f"/api/reviews/{created['id']}",
        headers=registered_user["headers"],
    )
    assert r.status_code == 403


async def test_seller_reviews_returns_stats_and_list(
    client, registered_user, second_user
):
    seller_id = registered_user["user"]["id"]
    auction_id = await _buy_from_seller(
        client, registered_user["headers"], second_user["headers"]
    )
    await client.post(
        "/api/reviews",
        json={
            "seller_id": seller_id, "auction_id": auction_id,
            "rating": 5, "comment": "A+",
        },
        headers=second_user["headers"],
    )
    r = await client.get(f"/api/sellers/{seller_id}/reviews")
    assert r.status_code == 200
    body = r.json()
    assert body["stats"]["total"] == 1
    assert body["stats"]["avg"] == 5.0
    assert body["stats"]["distribution"]["5"] == 1
    assert len(body["reviews"]) == 1


async def test_seller_with_no_reviews_returns_empty_stats(client, registered_user):
    """Empty-list branches: ``reviewers = {}`` (l.59) and
    ``auctions_map = {}`` (l.68) fire when the seller has no reviews yet.
    Without this, those else-branches never execute under the test
    suite."""
    seller_id = registered_user["user"]["id"]
    r = await client.get(f"/api/sellers/{seller_id}/reviews")
    assert r.status_code == 200
    body = r.json()
    assert body["stats"]["total"] == 0
    assert body["stats"]["avg"] == 0
    assert body["reviews"] == []


async def test_delete_nonexistent_review_returns_404(client, registered_user):
    r = await client.delete(
        "/api/reviews/999999", headers=registered_user["headers"]
    )
    assert r.status_code == 404
