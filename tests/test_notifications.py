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
    body = r.json()
    assert body["total"] == 2
    items = body["items"]
    assert len(items) == 2
    # Bob's notif must not bleed into Alice's feed.
    assert all(it["title"] != "Bob's lonely notification" for it in items)


async def test_unread_only_filter(client, registered_user, two_notifications):
    r = await client.get(
        "/api/notifications?unread_only=true",
        headers=registered_user["headers"],
    )
    body = r.json()
    assert body["total"] == 1
    items = body["items"]
    assert len(items) == 1
    assert items[0]["is_read"] is False


async def test_notifications_pagination_via_offset(client, registered_user):
    """Seed more rows than the default limit and walk the feed with
    explicit offset; the envelope's ``total`` and the second page's
    items both make older notifications reachable - the prior bare-list
    response capped silently at ``limit`` with no way past it."""
    user_id = registered_user["user"]["id"]
    for i in range(25):
        await _seed_notification(user_id, title=f"N{i}")

    first = (await client.get(
        "/api/notifications?limit=10&offset=0",
        headers=registered_user["headers"],
    )).json()
    second = (await client.get(
        "/api/notifications?limit=10&offset=10",
        headers=registered_user["headers"],
    )).json()
    third = (await client.get(
        "/api/notifications?limit=10&offset=20",
        headers=registered_user["headers"],
    )).json()

    assert first["total"] == 25
    assert len(first["items"]) == 10
    assert len(second["items"]) == 10
    assert len(third["items"]) == 5

    # Disjoint pages: ids on page 2 must not appear on page 1.
    ids_p1 = {n["id"] for n in first["items"]}
    ids_p2 = {n["id"] for n in second["items"]}
    assert ids_p1.isdisjoint(ids_p2)


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

    async def fake_send(to_email, subject, html, *, db=None):
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


async def test_notify_many_persists_in_app_and_outbox_atomically(
    registered_user, second_user, monkeypatch
):
    """``notify_many`` is the batched fan-out helper used by
    ``complete_auction``. Contract:

    1. Every payload's in-app ``Notification`` row AND the corresponding
       ``EmailOutbox`` row (when the recipient's email channel is on)
       persist in a single ``db.commit()`` - one DB round-trip, atomic
       across both channels. This is the durability boundary the outbox
       pattern was supposed to provide: either both channels' records
       land or neither does, no half-state.
    2. WS push runs concurrently after the commit and is best-effort;
       its failures don't unwind the durable channels.
    """
    from sqlalchemy import select

    from app import database as _db_module
    from app.models import EmailOutbox, User
    from app.services import notifications as notifications_service
    from app.services.email_outbox import enqueue_email

    # Lift the conftest autouse no-op so the email path actually inserts
    # outbox rows; this test asserts the atomic-batch contract.
    async def _real_fire(to, subj, html, *, db=None):
        await enqueue_email(to, subj, html, db=db)

    monkeypatch.setattr(notifications_service, "_fire_and_forget_email", _real_fire)

    async with _db_module.SessionLocal() as db:
        users = (
            await db.execute(
                select(User).where(
                    User.id.in_([
                        registered_user["user"]["id"],
                        second_user["user"]["id"],
                    ])
                )
            )
        ).scalars().all()
        # Both fixtures default to email_notifications=True and
        # notify_lost=True, so every payload should produce an outbox row.
        for u in users:
            assert u.email_notifications and u.notify_lost

        payloads = [
            (u, NotificationType.AUCTION_LOST, "Аукцион завершён", "тело")
            for u in users
        ]

        await notifications_service.notify_many(
            db, payloads, auction_id=None, auction_title=None
        )

    async with _db_module.SessionLocal() as db:
        for u in users:
            notif_rows = (
                await db.execute(
                    select(Notification).where(
                        Notification.user_id == u.id,
                        Notification.type == NotificationType.AUCTION_LOST.value,
                    )
                )
            ).scalars().all()
            assert len(notif_rows) == 1, (
                f"in-app row missing for user {u.id} (rows={notif_rows})"
            )
            outbox_rows = (
                await db.execute(
                    select(EmailOutbox).where(EmailOutbox.to_email == u.email)
                )
            ).scalars().all()
            assert len(outbox_rows) == 1, (
                f"outbox row missing for {u.email} - atomic batch failed "
                f"(rows={outbox_rows})"
            )


async def test_notify_many_isolates_ws_push_failures(
    registered_user, second_user, monkeypatch
):
    """The WS channel is best-effort: per-recipient push failures must
    not propagate out of notify_many. The durable channels (in-app +
    outbox) commit BEFORE the WS gather runs, so a broken WS for one
    user can't unwind the others' durable records either."""
    from sqlalchemy import select

    from app import database as _db_module
    from app.models import User
    from app.services import notifications as notifications_service

    sends = {"n": 0}

    class _ExplodingManager:
        async def send_notification(self, *args, **kwargs):
            sends["n"] += 1
            raise RuntimeError("ws send failed")

    async with _db_module.SessionLocal() as db:
        users = (
            await db.execute(
                select(User).where(
                    User.id.in_([
                        registered_user["user"]["id"],
                        second_user["user"]["id"],
                    ])
                )
            )
        ).scalars().all()
        payloads = [
            (u, NotificationType.AUCTION_LOST, "Аукцион завершён", "тело")
            for u in users
        ]

        # Must NOT raise even though every WS push fails.
        await notifications_service.notify_many(
            db, payloads, auction_id=None, auction_title=None,
            manager=_ExplodingManager(),
        )

    # gather attempted every push - the first failure did not
    # short-circuit the rest.
    assert sends["n"] == len(users)

    # Durable channels still landed despite the WS errors.
    async with _db_module.SessionLocal() as db:
        for u in users:
            rows = (
                await db.execute(
                    select(Notification).where(Notification.user_id == u.id)
                )
            ).scalars().all()
            assert rows, f"in-app row lost for user {u.id} on WS-failure path"
