import asyncio
from datetime import timedelta

from sqlalchemy import select, update

from app import database as _db_module
from app.models import Auction
from app.utils.time import utcnow


async def _create_auction(client, headers, **overrides):
    payload = {
        "title": "Bid test lot",
        "description": "...",
        "starting_price": 100.0,
        "duration_minutes": 60,
        "auction_type": "bid",
    }
    payload.update(overrides)
    response = await client.post("/api/auctions", json=payload, headers=headers)
    assert response.status_code == 200
    return response.json()


async def test_place_bid_increases_current_price(client, registered_user, second_user):
    auction = await _create_auction(client, registered_user["headers"])

    response = await client.post(
        "/api/bids",
        json={"auction_id": auction["id"], "amount": 150.0},
        headers=second_user["headers"],
    )
    assert response.status_code == 200

    refreshed = (await client.get(f"/api/auctions/{auction['id']}")).json()
    assert refreshed["current_price"] == 150.0
    assert refreshed["bids_count"] == 1


async def test_bid_on_bin_lot_rejected(client, registered_user, second_user):
    """BIN lots are fixed-price listings, not auctions - /bids must
    refuse them. Without this, a bidder could push current_price past
    bin_price while another user could still call /buy-now and grab the
    lot at the lower fixed price."""
    listing = (await client.post(
        "/api/auctions",
        json={
            "title": "Fixed-price lot",
            "description": "...",
            "starting_price": 100.0,
            "duration_minutes": 60,
            "auction_type": "bin",
            "bin_price": 250.0,
        },
        headers=registered_user["headers"],
    )).json()

    r = await client.post(
        "/api/bids",
        json={"auction_id": listing["id"], "amount": 300.0},
        headers=second_user["headers"],
    )
    assert r.status_code == 400
    assert "фиксированной" in r.json()["detail"].lower()


async def test_owner_cannot_bid_on_own_auction(client, registered_user):
    auction = await _create_auction(client, registered_user["headers"], starting_price=100.0)

    response = await client.post(
        "/api/bids",
        json={"auction_id": auction["id"], "amount": 200.0},
        headers=registered_user["headers"],
    )
    assert response.status_code == 400
    assert "свой" in response.json()["detail"].lower()


async def test_bid_below_current_price_rejected(client, registered_user, second_user):
    auction = await _create_auction(client, registered_user["headers"], starting_price=100.0)

    response = await client.post(
        "/api/bids",
        json={"auction_id": auction["id"], "amount": 50.0},
        headers=second_user["headers"],
    )
    assert response.status_code == 400


async def test_bid_equal_to_current_price_rejected(client, registered_user, second_user):
    auction = await _create_auction(client, registered_user["headers"], starting_price=100.0)

    response = await client.post(
        "/api/bids",
        json={"auction_id": auction["id"], "amount": 100.0},
        headers=second_user["headers"],
    )
    assert response.status_code == 400


async def test_bid_above_user_balance_rejected(client, registered_user, second_user):
    auction = await _create_auction(client, registered_user["headers"], starting_price=100.0)

    response = await client.post(
        "/api/bids",
        json={"auction_id": auction["id"], "amount": 5000.0},
        headers=second_user["headers"],
    )
    assert response.status_code == 400
    assert "средств" in response.json()["detail"].lower()


async def test_bid_outbid_replaces_leader(client, registered_user, second_user, third_user):
    auction = await _create_auction(client, registered_user["headers"], starting_price=100.0)

    first = await client.post(
        "/api/bids",
        json={"auction_id": auction["id"], "amount": 150.0},
        headers=second_user["headers"],
    )
    assert first.status_code == 200

    second = await client.post(
        "/api/bids",
        json={"auction_id": auction["id"], "amount": 200.0},
        headers=third_user["headers"],
    )
    assert second.status_code == 200

    refreshed = (await client.get(f"/api/auctions/{auction['id']}")).json()
    assert refreshed["current_price"] == 200.0
    assert refreshed["bids_count"] == 2


async def test_cannot_overcommit_balance_across_active_auctions(
    client, registered_user, second_user
):
    """A user with $1000 leading on a $700 auction can't also lead a
    $400 auction - the second bid would over-commit them ($1100 > $1000)."""
    a1 = await _create_auction(client, registered_user["headers"], title="Lot 1")
    a2 = await _create_auction(client, registered_user["headers"], title="Lot 2")

    r1 = await client.post(
        "/api/bids",
        json={"auction_id": a1["id"], "amount": 700.0},
        headers=second_user["headers"],
    )
    assert r1.status_code == 200

    r2 = await client.post(
        "/api/bids",
        json={"auction_id": a2["id"], "amount": 400.0},
        headers=second_user["headers"],
    )
    assert r2.status_code == 400
    assert "зарезервировано" in r2.json()["detail"].lower()


async def test_user_cannot_outbid_themselves(
    client, registered_user, second_user, third_user
):
    """Leading bidder can't raise their own bid - only another user
    breaking the leader's streak unlocks a fresh bid from them."""
    a1 = await _create_auction(client, registered_user["headers"])

    r1 = await client.post(
        "/api/bids",
        json={"auction_id": a1["id"], "amount": 500.0},
        headers=second_user["headers"],
    )
    assert r1.status_code == 200

    r2 = await client.post(
        "/api/bids",
        json={"auction_id": a1["id"], "amount": 800.0},
        headers=second_user["headers"],
    )
    assert r2.status_code == 400
    assert "лидиру" in r2.json()["detail"].lower()

    r3 = await client.post(
        "/api/bids",
        json={"auction_id": a1["id"], "amount": 600.0},
        headers=third_user["headers"],
    )
    assert r3.status_code == 200

    r4 = await client.post(
        "/api/bids",
        json={"auction_id": a1["id"], "amount": 900.0},
        headers=second_user["headers"],
    )
    assert r4.status_code == 200, r4.text


async def test_outbid_user_can_reuse_their_full_balance(
    client, registered_user, second_user, third_user
):
    third_headers = third_user["headers"]

    a1 = await _create_auction(client, registered_user["headers"], title="Lot 1")
    a2 = await _create_auction(client, registered_user["headers"], title="Lot 2")

    r1 = await client.post(
        "/api/bids",
        json={"auction_id": a1["id"], "amount": 700.0},
        headers=second_user["headers"],
    )
    assert r1.status_code == 200

    r2 = await client.post(
        "/api/bids",
        json={"auction_id": a1["id"], "amount": 750.0},
        headers=third_headers,
    )
    assert r2.status_code == 200

    r3 = await client.post(
        "/api/bids",
        json={"auction_id": a2["id"], "amount": 900.0},
        headers=second_user["headers"],
    )
    assert r3.status_code == 200, r3.text


async def test_concurrent_cross_auction_bids_respect_balance(
    client, registered_user, second_user
):
    """Same user fires two simultaneous bids on *different* auctions, each
    of which alone fits the balance but together over-commit it. The
    user-row ``SELECT ... FOR UPDATE`` in /bids must serialise them so
    only one passes the available-balance check."""
    a1 = await _create_auction(client, registered_user["headers"], title="Lot 1")
    a2 = await _create_auction(client, registered_user["headers"], title="Lot 2")

    r1, r2 = await asyncio.gather(
        client.post(
            "/api/bids",
            json={"auction_id": a1["id"], "amount": 700.0},
            headers=second_user["headers"],
        ),
        client.post(
            "/api/bids",
            json={"auction_id": a2["id"], "amount": 700.0},
            headers=second_user["headers"],
        ),
    )

    statuses = sorted([r1.status_code, r2.status_code])
    assert statuses == [200, 400], (
        f"cross-auction same-user race on lots {a1['id']}/{a2['id']}: "
        f"got {[r1.status_code, r2.status_code]}, bodies={r1.text!r} / {r2.text!r}"
    )


async def test_concurrent_equal_bids_only_one_wins(
    client, registered_user, second_user, third_user
):
    """Fire two equal bids on the same auction concurrently. The
    SELECT...FOR UPDATE row lock must serialise them so the second one
    fails the 'must be higher than current price' check instead of both
    silently winning."""
    third_headers = third_user["headers"]

    auction = await _create_auction(client, registered_user["headers"], starting_price=100.0)

    r_a, r_b = await asyncio.gather(
        client.post(
            "/api/bids",
            json={"auction_id": auction["id"], "amount": 150.0},
            headers=second_user["headers"],
        ),
        client.post(
            "/api/bids",
            json={"auction_id": auction["id"], "amount": 150.0},
            headers=third_headers,
        ),
    )

    statuses = sorted([r_a.status_code, r_b.status_code])
    assert statuses == [200, 400], (
        f"equal-amount race on lot {auction['id']}: "
        f"got {[r_a.status_code, r_b.status_code]}, bodies={r_a.text!r} / {r_b.text!r}"
    )

    refreshed = (await client.get(f"/api/auctions/{auction['id']}")).json()
    assert refreshed["current_price"] == 150.0
    assert refreshed["bids_count"] == 1


async def test_concurrent_same_user_bids_on_same_auction(
    client, registered_user, second_user
):
    """Fire two simultaneous bids from the *same* user on the *same*
    auction. The self-outbid guard reads the latest bid under the
    auction row lock - the second call must see the first as leader
    and 400 with 'вы уже лидируете', not double-up the user as both
    bidder positions."""
    auction = await _create_auction(client, registered_user["headers"], starting_price=100.0)

    r1, r2 = await asyncio.gather(
        client.post(
            "/api/bids",
            json={"auction_id": auction["id"], "amount": 150.0},
            headers=second_user["headers"],
        ),
        client.post(
            "/api/bids",
            json={"auction_id": auction["id"], "amount": 175.0},
            headers=second_user["headers"],
        ),
    )

    statuses = sorted([r1.status_code, r2.status_code])
    assert statuses == [200, 400], (r1.text, r2.text)

    refreshed = (await client.get(f"/api/auctions/{auction['id']}")).json()
    assert refreshed["bids_count"] == 1


# -- GET /api/auctions/{id}/bids (bid history) -- ----------------------------

async def test_bid_history_empty_returns_empty_list(client, registered_user):
    auction = await _create_auction(client, registered_user["headers"])
    r = await client.get(f"/api/auctions/{auction['id']}/bids")
    assert r.status_code == 200
    body = r.json()
    assert body["items"] == []
    assert body["total"] == 0


async def test_bid_history_lists_bids_in_reverse_order(client, registered_user, second_user, third_user):
    auction = await _create_auction(client, registered_user["headers"])
    await client.post("/api/deposit", json={"amount": 500.0}, headers=second_user["headers"])
    await client.post("/api/deposit", json={"amount": 500.0}, headers=third_user["headers"])
    await client.post(
        "/api/bids",
        json={"auction_id": auction["id"], "amount": 150.0},
        headers=second_user["headers"],
    )
    await client.post(
        "/api/bids",
        json={"auction_id": auction["id"], "amount": 200.0},
        headers=third_user["headers"],
    )

    r = await client.get(f"/api/auctions/{auction['id']}/bids")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    # Newest first.
    assert body["items"][0]["amount"] == 200.0
    assert body["items"][1]["amount"] == 150.0
    # Username carried through the selectinload join.
    usernames = {b["username"] for b in body["items"]}
    assert usernames == {"bob", "carol"}


async def test_bid_history_pagination(
    client, registered_user, second_user, third_user
):
    # Need >= 2 distinct bidders - a user who is already the leader
    # can't outbid themselves, so a single bidder yields exactly one
    # bid no matter how many POSTs we do.
    auction = await _create_auction(client, registered_user["headers"])
    await client.post(
        "/api/deposit", json={"amount": 500.0}, headers=second_user["headers"]
    )
    await client.post(
        "/api/deposit", json={"amount": 500.0}, headers=third_user["headers"]
    )
    amount = 125.0
    bidders = [second_user, third_user, second_user]
    for bidder in bidders:
        r = await client.post(
            "/api/bids",
            json={"auction_id": auction["id"], "amount": amount},
            headers=bidder["headers"],
        )
        assert r.status_code == 200, r.text
        amount += 25.0
    r = await client.get(f"/api/auctions/{auction['id']}/bids?page=1&page_size=2")
    body = r.json()
    assert body["total"] == 3
    assert body["total_pages"] == 2
    assert len(body["items"]) == 2


# -- Anti-sniping -----------------------------------------------------------

async def _force_end_time(auction_id: int, seconds_from_now: int) -> None:
    """Push the auction deadline to ``now + seconds_from_now`` so the
    closing-window logic can be exercised without waiting in real time."""
    async with _db_module.SessionLocal() as db:
        await db.execute(
            update(Auction)
            .where(Auction.id == auction_id)
            .values(end_time=utcnow() + timedelta(seconds=seconds_from_now))
        )
        await db.commit()


async def test_bid_in_closing_window_extends_end_time(
    client, registered_user, second_user
):
    """A bid arriving within the 2-minute anti-sniping window must push
    end_time to roughly now + 2 minutes so the previous leader has a
    full window to react. Without this, a sniper bid at end_time - 1s
    wins with no chance for counter-bids."""
    auction = await _create_auction(client, registered_user["headers"])
    original_end = utcnow() + timedelta(seconds=30)
    await _force_end_time(auction["id"], seconds_from_now=30)

    r = await client.post(
        "/api/bids",
        json={"auction_id": auction["id"], "amount": 150.0},
        headers=second_user["headers"],
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["extended_until"] is not None

    async with _db_module.SessionLocal() as db:
        refreshed = (
            await db.execute(select(Auction).where(Auction.id == auction["id"]))
        ).scalar_one()
    # Should be ~120s from now, definitely later than the original 30s deadline.
    delta = (refreshed.end_time - original_end).total_seconds()
    assert delta > 60, (
        f"end_time moved by only {delta:.1f}s - expected ~90s "
        f"(120s extension minus 30s of original lead)"
    )


async def test_bid_outside_closing_window_does_not_extend(
    client, registered_user, second_user
):
    """A bid placed long before the deadline must leave end_time alone -
    extending unconditionally would let any bid reset the timer and
    auctions would never close."""
    auction = await _create_auction(client, registered_user["headers"])
    async with _db_module.SessionLocal() as db:
        original = (
            await db.execute(select(Auction).where(Auction.id == auction["id"]))
        ).scalar_one()
        original_end = original.end_time

    r = await client.post(
        "/api/bids",
        json={"auction_id": auction["id"], "amount": 150.0},
        headers=second_user["headers"],
    )
    assert r.status_code == 200, r.text
    assert r.json()["extended_until"] is None

    async with _db_module.SessionLocal() as db:
        refreshed = (
            await db.execute(select(Auction).where(Auction.id == auction["id"]))
        ).scalar_one()
    assert refreshed.end_time == original_end


async def test_concurrent_late_bids_extend_end_time_once(
    client, registered_user, second_user, third_user
):
    """Two simultaneous bids in the closing window must both pass the
    SELECT FOR UPDATE serialisation - one wins, the other is rejected
    on the 'higher than current price' check - and end_time must be
    extended exactly once. A naive implementation could double-extend
    by ~4 minutes; FOR UPDATE on the auction row prevents that because
    the second bid sees the already-extended end_time."""
    auction = await _create_auction(client, registered_user["headers"], starting_price=100.0)
    await _force_end_time(auction["id"], seconds_from_now=30)

    r_a, r_b = await asyncio.gather(
        client.post(
            "/api/bids",
            json={"auction_id": auction["id"], "amount": 150.0},
            headers=second_user["headers"],
        ),
        client.post(
            "/api/bids",
            json={"auction_id": auction["id"], "amount": 150.0},
            headers=third_user["headers"],
        ),
    )
    statuses = sorted([r_a.status_code, r_b.status_code])
    assert statuses == [200, 400], (r_a.text, r_b.text)

    async with _db_module.SessionLocal() as db:
        refreshed = (
            await db.execute(select(Auction).where(Auction.id == auction["id"]))
        ).scalar_one()
    seconds_left = (refreshed.end_time - utcnow()).total_seconds()
    # Single extension = ~120s. Double extension would be ~240s.
    assert 90 < seconds_left < 150, (
        f"expected single 120s extension, got {seconds_left:.1f}s left"
    )
