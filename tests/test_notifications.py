"""Notifications router - list / mark-read / delete with ownership checks.

Notifications can't be created via a public endpoint (they're side
effects of bidding, etc), so these tests insert directly via the test
session factory exposed by ``app.database``.
"""

import pytest_asyncio

from app import database as _db_module
from app.models import Notification, NotificationType


async def _seed_notification(user_id: int, **overrides) -> Notification:
    payload = {
        "user_id": user_id,
        "type": NotificationType.BID_OUTBID.value,
        "title": "Test",
        "message": "msg",
        "is_read": False,
        **overrides,
    }
    async with _db_module.SessionLocal() as db:
        n = Notification(**payload)
        db.add(n)
        await db.commit()
        await db.refresh(n)
        return n


@pytest_asyncio.fixture
async def two_notifications(registered_user):
    """One unread + one already-read for the registered user."""
    unread = await _seed_notification(registered_user["user"]["id"])
    read = await _seed_notification(registered_user["user"]["id"], is_read=True, title="Read")
    return {"unread": unread, "read": read}


async def test_list_returns_only_own_notifications(
    client, registered_user, second_user, two_notifications
):
    await _seed_notification(second_user["user"]["id"], title="Bob's lonely notification")

    r = await client.get("/api/notifications", headers=registered_user["headers"])
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 2
    # Bob's notif must not bleed into Alice's feed.
    assert all(it["title"] != "Bob's lonely notification" for it in items)


async def test_unread_only_filter(client, registered_user, two_notifications):
    r = await client.get(
        "/api/notifications?unread_only=true",
        headers=registered_user["headers"],
    )
    items = r.json()
    assert len(items) == 1
    assert items[0]["is_read"] is False


async def test_unread_count(client, registered_user, two_notifications):
    r = await client.get(
        "/api/notifications/unread-count",
        headers=registered_user["headers"],
    )
    assert r.json()["count"] == 1


async def test_mark_read(client, registered_user, two_notifications):
    nid = two_notifications["unread"].id
    r = await client.post(
        f"/api/notifications/{nid}/read",
        headers=registered_user["headers"],
    )
    assert r.status_code == 200

    count = (await client.get(
        "/api/notifications/unread-count",
        headers=registered_user["headers"],
    )).json()["count"]
    assert count == 0


async def test_mark_all_read(client, registered_user, two_notifications):
    # Add two more unread for variety.
    await _seed_notification(registered_user["user"]["id"])
    await _seed_notification(registered_user["user"]["id"])

    r = await client.post(
        "/api/notifications/mark-all-read",
        headers=registered_user["headers"],
    )
    assert r.status_code == 200

    count = (await client.get(
        "/api/notifications/unread-count",
        headers=registered_user["headers"],
    )).json()["count"]
    assert count == 0


async def test_delete_own_notification(client, registered_user, two_notifications):
    nid = two_notifications["unread"].id
    r = await client.delete(
        f"/api/notifications/{nid}",
        headers=registered_user["headers"],
    )
    assert r.status_code == 200


async def test_mark_read_on_someone_elses_notification_returns_404(
    client, registered_user, second_user
):
    """The handler scopes the lookup by user_id, so accessing another
    user's notification id is indistinguishable from a missing row -
    deliberate, prevents leaking existence."""
    alices = await _seed_notification(registered_user["user"]["id"])
    r = await client.post(
        f"/api/notifications/{alices.id}/read",
        headers=second_user["headers"],
    )
    assert r.status_code == 404


async def test_delete_someone_elses_notification_returns_404(
    client, registered_user, second_user
):
    bobs = await _seed_notification(second_user["user"]["id"])
    r = await client.delete(
        f"/api/notifications/{bobs.id}",
        headers=registered_user["headers"],
    )
    assert r.status_code == 404


async def test_auction_lost_email_respects_notify_lost_pref(monkeypatch):
    """notify_user gates the AUCTION_LOST email behind ``notify_lost``;
    flipping it to False stops the fire-and-forget send. The fix
    completes the coverage matrix - every NotificationType now has
    its own user-pref toggle."""
    from app.models import NotificationType, User
    from app.services import notifications as notif_module

    sent: list[tuple[str, str]] = []

    async def fake_send(to_email, subject, html):
        sent.append((to_email, subject))

    monkeypatch.setattr(notif_module, "_fire_and_forget_email", fake_send)

    async with _db_module.SessionLocal() as db:
        user = User(
            username="loser",
            email="loser@example.com",
            hashed_password="x",
            email_notifications=True,
            notify_lost=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)

        await notif_module.notify_user(
            db, user, NotificationType.AUCTION_LOST,
            "Auction lost", "You lost", auction_id=None, auction_title=None,
        )
        assert len(sent) == 1

        sent.clear()
        user.notify_lost = False
        await db.commit()
        await notif_module.notify_user(
            db, user, NotificationType.AUCTION_LOST,
            "Auction lost", "You lost", auction_id=None, auction_title=None,
        )
        assert sent == []
