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
