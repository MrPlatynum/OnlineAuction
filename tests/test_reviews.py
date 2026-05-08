"""Reviews router — leave / list / delete seller reviews."""


async def test_create_review_for_seller(client, registered_user, second_user):
    payload = {
        "seller_id": registered_user["user"]["id"],
        "rating": 5,
        "comment": "Отличный продавец",
    }
    r = await client.post("/api/reviews", json=payload, headers=second_user["headers"])
    assert r.status_code == 200
    assert "id" in r.json()


async def test_review_on_self_rejected(client, registered_user):
    payload = {"seller_id": registered_user["user"]["id"], "rating": 5}
    r = await client.post("/api/reviews", json=payload, headers=registered_user["headers"])
    assert r.status_code == 400


async def test_review_on_unknown_seller_returns_404(client, second_user):
    r = await client.post(
        "/api/reviews",
        json={"seller_id": 999_999, "rating": 4},
        headers=second_user["headers"],
    )
    assert r.status_code == 404


async def test_rating_outside_1_5_rejected(client, registered_user, second_user):
    """Pydantic Field(ge=1, le=5) — 0 / 6 must be rejected before the
    handler runs."""
    for bad in (0, 6, 99):
        r = await client.post(
            "/api/reviews",
            json={"seller_id": registered_user["user"]["id"], "rating": bad},
            headers=second_user["headers"],
        )
        assert r.status_code == 422, bad


async def test_duplicate_review_on_same_auction_rejected(
    client, registered_user, second_user
):
    """The handler explicitly forbids leaving two reviews from the
    same reviewer on the same auction (avoids review-bombing)."""
    auction = (await client.post(
        "/api/auctions",
        json={
            "title": "Lot",
            "description": "...",
            "starting_price": 100.0,
            "duration_minutes": 60,
            "auction_type": "bin",
            "bin_price": 200.0,
        },
        headers=registered_user["headers"],
    )).json()

    base = {
        "seller_id": registered_user["user"]["id"],
        "auction_id": auction["id"],
        "rating": 5,
    }
    r1 = await client.post("/api/reviews", json=base, headers=second_user["headers"])
    assert r1.status_code == 200
    r2 = await client.post("/api/reviews", json=base, headers=second_user["headers"])
    assert r2.status_code == 400


async def test_delete_own_review_works(client, registered_user, second_user):
    seller_id = registered_user["user"]["id"]
    created = (await client.post(
        "/api/reviews",
        json={"seller_id": seller_id, "rating": 4},
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
    created = (await client.post(
        "/api/reviews",
        json={"seller_id": seller_id, "rating": 4},
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
    await client.post(
        "/api/reviews",
        json={"seller_id": seller_id, "rating": 5, "comment": "A+"},
        headers=second_user["headers"],
    )
    r = await client.get(f"/api/sellers/{seller_id}/reviews")
    assert r.status_code == 200
    body = r.json()
    assert body["stats"]["total"] == 1
    assert body["stats"]["avg"] == 5.0
    assert body["stats"]["distribution"]["5"] == 1
    assert len(body["reviews"]) == 1
