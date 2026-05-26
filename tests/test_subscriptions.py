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


async def test_subscribe_integrity_race_returns_400_not_500(
    client, registered_user, second_user, monkeypatch
):
    """The pre-check is a TOCTOU window: in production two concurrent
    calls can both pass it before either commits, and the unique
    constraint then raises IntegrityError on the loser. The ASGI test
    client serialises requests so a plain asyncio.gather doesn't
    reproduce the race; monkeypatch the existence check to None to
    drive the second request straight into the INSERT path while the
    first call's row is already in the DB."""
    seller_id = registered_user["user"]["id"]

    # First call - lays down the row normally.
    first = await client.post(
        f"/api/sellers/{seller_id}/subscribe",
        headers=second_user["headers"],
    )
    assert first.status_code == 200, first.text

    # Force the pre-check on the next call to claim no row exists, so
    # the handler reaches the INSERT and Postgres' unique constraint
    # raises IntegrityError.
    from app.routers import subscriptions as subs_mod

    real_execute = subs_mod.AsyncSession.execute
    call_count = {"n": 0}

    async def _spoof_existence(self, stmt, *a, **kw):
        result = await real_execute(self, stmt, *a, **kw)
        # Only swap the *second* select() inside subscribe() (the
        # existence check). The first one (seller lookup) is untouched.
        compiled = str(stmt)
        if "subscriptions" in compiled and "WHERE" in compiled:
            call_count["n"] += 1
            if call_count["n"] == 1:
                class _Empty:
                    def scalar_one_or_none(self_inner):
                        return None
                return _Empty()
        return result

    monkeypatch.setattr(subs_mod.AsyncSession, "execute", _spoof_existence)

    second = await client.post(
        f"/api/sellers/{seller_id}/subscribe",
        headers=second_user["headers"],
    )
    # Without the IntegrityError handler this surfaces as 500.
    assert second.status_code == 400, second.text
    assert "подписан" in second.json()["detail"].lower()


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
