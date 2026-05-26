"""Subscriptions router - follow / unfollow a seller."""


async def test_subscribe_marks_subscribed_and_increments_count(
    client, registered_user, second_user
):
    seller_id = registered_user["user"]["id"]
    r = await client.post(
        f"/api/sellers/{seller_id}/subscribe",
        headers=second_user["headers"],
    )
    assert r.status_code == 200
    body = r.json()
    assert body["subscribed"] is True
    assert body["subscribers_count"] == 1


async def test_subscribe_to_self_rejected(client, registered_user):
    seller_id = registered_user["user"]["id"]
    r = await client.post(
        f"/api/sellers/{seller_id}/subscribe",
        headers=registered_user["headers"],
    )
    assert r.status_code == 400


async def test_subscribe_to_nonexistent_seller_returns_404(client, second_user):
    """Without the existence pre-check, the FK violation on insert used
    to bubble out as a generic 500 - a confusing internal-error response
    to what is just a stale link."""
    r = await client.post(
        "/api/sellers/999999/subscribe",
        headers=second_user["headers"],
    )
    assert r.status_code == 404


async def test_duplicate_subscribe_rejected(client, registered_user, second_user):
    seller_id = registered_user["user"]["id"]
    r1 = await client.post(
        f"/api/sellers/{seller_id}/subscribe",
        headers=second_user["headers"],
    )
    assert r1.status_code == 200
    r2 = await client.post(
        f"/api/sellers/{seller_id}/subscribe",
        headers=second_user["headers"],
    )
    assert r2.status_code == 400


async def test_unsubscribe_removes_subscription(client, registered_user, second_user):
    seller_id = registered_user["user"]["id"]
    await client.post(
        f"/api/sellers/{seller_id}/subscribe",
        headers=second_user["headers"],
    )
    r = await client.delete(
        f"/api/sellers/{seller_id}/subscribe",
        headers=second_user["headers"],
    )
    assert r.status_code == 200
    assert r.json()["subscribed"] is False
    assert r.json()["subscribers_count"] == 0


async def test_unsubscribe_without_subscription_rejected(
    client, registered_user, second_user
):
    seller_id = registered_user["user"]["id"]
    r = await client.delete(
        f"/api/sellers/{seller_id}/subscribe",
        headers=second_user["headers"],
    )
    assert r.status_code == 400


async def test_my_subscriptions_lists_current_seller(client, registered_user, second_user):
    seller_id = registered_user["user"]["id"]
    await client.post(
        f"/api/sellers/{seller_id}/subscribe",
        headers=second_user["headers"],
    )
    r = await client.get(
        "/api/my/subscriptions", headers=second_user["headers"]
    )
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 1
    assert items[0]["seller_id"] == seller_id
    assert items[0]["username"] == registered_user["user"]["username"]


# -- GET /api/sellers/{seller_id}/subscription -- ----------------------------

async def test_subscription_status_returns_false_before_subscribe(
    client, registered_user, second_user
):
    seller_id = registered_user["user"]["id"]
    r = await client.get(
        f"/api/sellers/{seller_id}/subscription",
        headers=second_user["headers"],
    )
    assert r.status_code == 200
    body = r.json()
    assert body["subscribed"] is False
    assert body["subscribers_count"] == 0


async def test_subscription_status_returns_true_after_subscribe(
    client, registered_user, second_user
):
    seller_id = registered_user["user"]["id"]
    await client.post(
        f"/api/sellers/{seller_id}/subscribe",
        headers=second_user["headers"],
    )
    r = await client.get(
        f"/api/sellers/{seller_id}/subscription",
        headers=second_user["headers"],
    )
    body = r.json()
    assert body["subscribed"] is True
    assert body["subscribers_count"] == 1
