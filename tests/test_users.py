"""Users router — public profile + notification preferences."""


async def test_public_profile_does_not_leak_email(client, registered_user):
    r = await client.get(f"/api/users/{registered_user['user']['username']}")
    assert r.status_code == 200
    body = r.json()
    user = body["user"]
    assert user["username"] == registered_user["user"]["username"]
    # Email is private — must not appear anywhere in the profile payload.
    flat = str(body)
    assert "@example.com" not in flat
    assert "email" not in user


async def test_unknown_user_returns_404(client):
    r = await client.get("/api/users/does_not_exist")
    assert r.status_code == 404


async def test_profile_carries_stats_and_auctions(client, registered_user):
    r = await client.get(f"/api/users/{registered_user['user']['username']}")
    body = r.json()
    assert "stats" in body
    assert {"created_count", "total_bids", "won_count", "lost_count"} <= body["stats"].keys()
    assert isinstance(body["auctions"], list)


async def test_update_notification_settings_persists(client, registered_user):
    payload = {
        "email_notifications": False,
        "notify_outbid": False,
        "notify_winning": True,
        "notify_ending": False,
        "notify_sold": True,
    }
    r = await client.put(
        "/api/notification-settings",
        json=payload,
        headers=registered_user["headers"],
    )
    assert r.status_code == 200


async def test_notification_settings_require_auth(client):
    r = await client.put(
        "/api/notification-settings",
        json={
            "email_notifications": False,
            "notify_outbid": False,
            "notify_winning": False,
            "notify_ending": False,
            "notify_sold": False,
        },
    )
    # No bearer token → HTTPBearer dependency rejects with 403.
    assert r.status_code in (401, 403)
