"""Email verification flow.

Covers the gate (unverified users can't bid / buy-now / create auctions),
the /verify-email endpoint (success, expired, bad signature, wrong
purpose, mismatched email, idempotency), the resend endpoint
(auth-gated, already-verified case), the grandfather migration's effect
in tests (existing registered_user fixture is auto-verified), and the
post-register fire-and-forget email send.
"""

from datetime import timedelta

import jwt
import pytest

from app.config import ALGORITHM, SECRET_KEY
from app.utils.security import EMAIL_VERIFY_PURPOSE, create_email_verify_token
from app.utils.time import utcnow


def _make_token(user_id: int, email: str, *, purpose: str = EMAIL_VERIFY_PURPOSE,
                exp_delta: timedelta = timedelta(hours=1)) -> str:
    payload = {
        "user_id": user_id,
        "email": email,
        "purpose": purpose,
        "exp": utcnow() + exp_delta,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


async def test_unverified_user_cannot_place_bid(client, registered_user, unverified_user):
    """A bid from an unverified account is rejected with 403, not just
    silently dropped: gating at the dependency layer means /bids never
    sees the request."""
    # registered_user (verified) creates a lot so there's something to bid on.
    auction = await client.post(
        "/api/auctions",
        json={
            "title": "Lot",
            "description": "test",
            "starting_price": 10,
            "duration_minutes": 60,
            "auction_type": "bid",
        },
        headers=registered_user["headers"],
    )
    assert auction.status_code == 200, auction.text
    auction_id = auction.json()["id"]

    r = await client.post(
        "/api/bids",
        json={"auction_id": auction_id, "amount": 20},
        headers=unverified_user["headers"],
    )
    assert r.status_code == 403


async def test_unverified_user_cannot_buy_now(client, registered_user, unverified_user):
    """BIN purchase is a write action that moves money — gated together
    with /bids."""
    auction = await client.post(
        "/api/auctions",
        json={
            "title": "BIN Lot",
            "description": "test",
            "starting_price": 10,
            "duration_minutes": 60,
            "auction_type": "bin",
            "bin_price": 50,
        },
        headers=registered_user["headers"],
    )
    assert auction.status_code == 200, auction.text
    auction_id = auction.json()["id"]

    r = await client.post(
        f"/api/auctions/{auction_id}/buy-now",
        headers=unverified_user["headers"],
    )
    assert r.status_code == 403


async def test_unverified_user_cannot_create_auction(client, unverified_user):
    r = await client.post(
        "/api/auctions",
        json={
            "title": "Lot",
            "description": "test",
            "starting_price": 10,
            "duration_minutes": 60,
            "auction_type": "bid",
        },
        headers=unverified_user["headers"],
    )
    assert r.status_code == 403


async def test_unverified_user_cannot_deposit_or_withdraw(client, unverified_user):
    """Both money-mutation endpoints require a confirmed email — without
    that gate a throwaway account could move money around and complicate
    refund flows even before it tried to bid."""
    r_deposit = await client.post(
        "/api/deposit",
        json={"amount": 100},
        headers=unverified_user["headers"],
    )
    assert r_deposit.status_code == 403

    r_withdraw = await client.post(
        "/api/withdraw",
        json={"amount": 50},
        headers=unverified_user["headers"],
    )
    assert r_withdraw.status_code == 403


async def test_unverified_user_can_still_view_listings(client, unverified_user):
    """Read-only browsing of /api/auctions stays open so an unverified
    user can decide what they'd want to bid on before confirming."""
    r_view = await client.get("/api/auctions")
    assert r_view.status_code == 200


async def test_verify_email_with_valid_token(client, unverified_user):
    user_id = unverified_user["user"]["id"]
    email = unverified_user["email"]
    token = _make_token(user_id, email)

    r = await client.post("/api/verify-email", json={"token": token})
    assert r.status_code == 200

    # The user is now verified — confirmed by /me reflecting the flag.
    me = await client.get("/api/me", headers=unverified_user["headers"])
    assert me.json()["email_verified"] is True


async def test_verify_email_with_expired_token(client, unverified_user):
    """Past-exp tokens get 400 (user-facing input error), not 401 — the
    user's session is still valid, just the verification link is stale."""
    user_id = unverified_user["user"]["id"]
    email = unverified_user["email"]
    token = _make_token(user_id, email, exp_delta=timedelta(seconds=-5))

    r = await client.post("/api/verify-email", json={"token": token})
    assert r.status_code == 400


async def test_verify_email_with_bad_signature(client, unverified_user):
    """Tokens signed with a different key (e.g. forged on the client)
    fail at decode — 400, not 200."""
    user_id = unverified_user["user"]["id"]
    email = unverified_user["email"]
    forged = jwt.encode(
        {
            "user_id": user_id,
            "email": email,
            "purpose": EMAIL_VERIFY_PURPOSE,
            "exp": utcnow() + timedelta(hours=1),
        },
        "totally-different-secret",
        algorithm=ALGORITHM,
    )
    r = await client.post("/api/verify-email", json={"token": forged})
    assert r.status_code == 400


async def test_verify_email_rejects_wrong_purpose(client, unverified_user):
    """An auth token (purpose missing or != email_verify) must NOT be
    accepted as a verification token — otherwise any login token could
    flip the email_verified flag without the email click."""
    user_id = unverified_user["user"]["id"]
    email = unverified_user["email"]
    token = _make_token(user_id, email, purpose="login")
    r = await client.post("/api/verify-email", json={"token": token})
    assert r.status_code == 400


async def test_verify_email_rejects_mismatched_email(client, unverified_user):
    """A token issued for an old address must NOT verify the new
    address after a (future) /change-email flow. We simulate that by
    forging a token whose email claim doesn't match the row."""
    user_id = unverified_user["user"]["id"]
    token = _make_token(user_id, "someone-else@example.com")
    r = await client.post("/api/verify-email", json={"token": token})
    assert r.status_code == 400


async def test_verify_email_is_idempotent(client, unverified_user):
    """A second click on the same link (or a link prefetcher racing
    the user) still returns 200, not an error — re-verifying an
    already-verified user is a no-op."""
    user_id = unverified_user["user"]["id"]
    email = unverified_user["email"]
    token = create_email_verify_token(
        type("U", (), {"id": user_id, "email": email})()
    )
    r1 = await client.post("/api/verify-email", json={"token": token})
    r2 = await client.post("/api/verify-email", json={"token": token})
    assert r1.status_code == 200
    assert r2.status_code == 200


async def test_resend_requires_auth(client):
    r = await client.post("/api/verify-email/resend")
    # No bearer header → 401/403 from HTTPBearer dependency
    assert r.status_code in (401, 403)


async def test_resend_for_already_verified_returns_400(client, registered_user):
    """The registered_user fixture is auto-verified — resending on top
    of that should reject (no point spamming the inbox)."""
    r = await client.post(
        "/api/verify-email/resend",
        headers=registered_user["headers"],
    )
    assert r.status_code == 400


async def test_resend_succeeds_for_unverified(client, unverified_user, capture_emails):
    r = await client.post(
        "/api/verify-email/resend",
        headers=unverified_user["headers"],
    )
    assert r.status_code == 200
    assert len(capture_emails) == 1
    assert capture_emails[0][0] == unverified_user["email"]


async def test_register_fires_verification_email(client, capture_emails):
    """The post-register email goes through ``_fire_and_forget_email``
    just like every other notification; assert the call shape so a
    future refactor that drops it gets flagged."""
    r = await client.post(
        "/api/register",
        json={
            "username": "freshie",
            "email": "freshie@example.com",
            "password": "password123",
        },
    )
    assert r.status_code == 200, r.text
    assert len(capture_emails) == 1
    to_email, subject, html_body = capture_emails[0]
    assert to_email == "freshie@example.com"
    assert "подтверд" in subject.lower()
    assert "verify-email.html?token=" in html_body


async def test_user_response_carries_email_verified_flag(client, unverified_user):
    """The flag must be visible to the frontend so the profile UI can
    decide whether to show the "Not verified" badge and resend button."""
    me = await client.get("/api/me", headers=unverified_user["headers"])
    assert me.status_code == 200
    assert me.json()["email_verified"] is False


@pytest.mark.parametrize("missing_field", ["user_id", "email", "purpose"])
async def test_verify_email_rejects_malformed_token(
    client, unverified_user, missing_field
):
    """Tokens missing any of the required claims must be rejected. The
    decoder defensively checks both purpose and the user_id/email types
    so a future change to the issuer can't silently widen the surface."""
    payload = {
        "user_id": unverified_user["user"]["id"],
        "email": unverified_user["email"],
        "purpose": EMAIL_VERIFY_PURPOSE,
        "exp": utcnow() + timedelta(hours=1),
    }
    payload.pop(missing_field)
    token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
    r = await client.post("/api/verify-email", json={"token": token})
    assert r.status_code == 400
