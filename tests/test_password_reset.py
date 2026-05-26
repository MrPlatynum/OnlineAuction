"""Password-reset flow.

The reset token is stateless and embeds the user's ``token_version``;
a successful /confirm bumps tv so the same link can't be used twice
and any in-flight auth tokens / other reset links for the same
account also get invalidated. The /request endpoint is
anti-enumeration: always 200, with a per-email 60s throttle on top
of the per-IP slowapi limit.
"""

import asyncio
from datetime import timedelta

import jwt
import pytest
from sqlalchemy import select

from app.config import ALGORITHM, SECRET_KEY
from app.database import SessionLocal
from app.models import User
from app.utils.security import (
    PASSWORD_RESET_PURPOSE,
    create_password_reset_token,
)
from app.utils.time import utcnow


async def _reset_token_for(user_id: int) -> str:
    """Build a fresh password-reset token for ``user_id`` by reading
    its current ``token_version`` from the DB. Replaces a repeated
    10-line ``SessionLocal + SELECT + create_password_reset_token``
    block at 6+ test sites."""
    async with SessionLocal() as db:
        user = (
            await db.execute(select(User).where(User.id == user_id))
        ).scalar_one()
        return create_password_reset_token(user)


def _make_token(
    user_id: int,
    tv: int,
    *,
    purpose: str = PASSWORD_RESET_PURPOSE,
    exp_delta: timedelta = timedelta(hours=1),
) -> str:
    payload = {
        "user_id": user_id,
        "tv": tv,
        "purpose": purpose,
        "exp": utcnow() + exp_delta,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


async def test_request_for_existing_email_sends_mail(client, registered_user, capture_emails):
    r = await client.post(
        "/api/password-reset/request",
        json={"email": registered_user["user"]["email"]},
    )
    assert r.status_code == 200
    assert len(capture_emails) == 1
    assert capture_emails[0][0] == registered_user["user"]["email"]
    assert "password-reset.html?token=" in capture_emails[0][2]


async def test_request_for_unknown_email_returns_200_silently(client, capture_emails):
    """Anti-enumeration: response shape must be identical to the
    happy path so an attacker can't probe which addresses are
    registered."""
    r = await client.post(
        "/api/password-reset/request",
        json={"email": "no-such-user@example.com"},
    )
    assert r.status_code == 200
    assert capture_emails == []


async def test_request_per_email_throttle_skips_second_send(
    client, registered_user, capture_emails
):
    """Two /request calls within 60s for the same email: the first
    sends a mail, the second silently returns 200 without sending.
    This is per-email, distinct from the per-IP slowapi limit."""
    email = registered_user["user"]["email"]
    r1 = await client.post("/api/password-reset/request", json={"email": email})
    r2 = await client.post("/api/password-reset/request", json={"email": email})
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert len(capture_emails) == 1


async def test_confirm_with_valid_token_resets_password(
    client, registered_user
):
    """End-to-end: token from create_password_reset_token → confirm →
    /login with new password works, /login with old fails."""
    token = await _reset_token_for(registered_user["user"]["id"])

    r = await client.post(
        "/api/password-reset/confirm",
        json={"token": token, "new_password": "brand-new-password-1"},
    )
    assert r.status_code == 200, r.text

    # Old password no longer accepted
    r_old = await client.post("/api/login", json={
        "username": registered_user["user"]["username"],
        "password": registered_user["password"],
    })
    assert r_old.status_code == 401

    # New password works
    r_new = await client.post("/api/login", json={
        "username": registered_user["user"]["username"],
        "password": "brand-new-password-1",
    })
    assert r_new.status_code == 200


async def test_confirm_with_expired_token(client, registered_user):
    token = _make_token(
        registered_user["user"]["id"], 0, exp_delta=timedelta(seconds=-5)
    )
    r = await client.post(
        "/api/password-reset/confirm",
        json={"token": token, "new_password": "another-new-password"},
    )
    assert r.status_code == 400


async def test_confirm_with_bad_signature(client, registered_user):
    forged = jwt.encode(
        {
            "user_id": registered_user["user"]["id"],
            "tv": 0,
            "purpose": PASSWORD_RESET_PURPOSE,
            "exp": utcnow() + timedelta(hours=1),
        },
        "totally-different-secret",
        algorithm=ALGORITHM,
    )
    r = await client.post(
        "/api/password-reset/confirm",
        json={"token": forged, "new_password": "another-new-password"},
    )
    assert r.status_code == 400


async def test_confirm_rejects_wrong_purpose(client, registered_user):
    """An auth token must NOT double as a reset token - otherwise a
    leaked JWT could be used to silently rotate the password."""
    token = _make_token(
        registered_user["user"]["id"], 0, purpose="login"
    )
    r = await client.post(
        "/api/password-reset/confirm",
        json={"token": token, "new_password": "another-new-password"},
    )
    assert r.status_code == 400


async def test_confirm_replay_fails_after_first_success(
    client, registered_user
):
    """The token's ``tv`` claim is checked against the user's row.
    The first /confirm bumps tv to (old+1); the second click on
    the same link still carries tv=(old) → mismatch → 400."""
    token = await _reset_token_for(registered_user["user"]["id"])

    r1 = await client.post(
        "/api/password-reset/confirm",
        json={"token": token, "new_password": "first-rotation-pwd"},
    )
    r2 = await client.post(
        "/api/password-reset/confirm",
        json={"token": token, "new_password": "second-attempt-pwd"},
    )
    assert r1.status_code == 200
    assert r2.status_code == 400


async def test_confirm_concurrent_same_token_only_one_wins(
    client, registered_user, monkeypatch
):
    """Fire two concurrent /confirm calls with the same valid token. The
    user-row ``SELECT ... FOR UPDATE`` must serialise them so only the
    first commit wins; the second sees the bumped tv and gets a 400."""
    async def _noop(*_a, **_kw):
        return None

    monkeypatch.setattr(
        "app.services.notifications._fire_and_forget_email", _noop
    )

    from sqlalchemy import select

    from app.database import SessionLocal
    from app.models import User

    async with SessionLocal() as db:
        user = (await db.execute(
            select(User).where(User.id == registered_user["user"]["id"])
        )).scalar_one()
        token = create_password_reset_token(user)

    r1, r2 = await asyncio.gather(
        client.post(
            "/api/password-reset/confirm",
            json={"token": token, "new_password": "race-rotation-a"},
        ),
        client.post(
            "/api/password-reset/confirm",
            json={"token": token, "new_password": "race-rotation-b"},
        ),
    )

    statuses = sorted([r1.status_code, r2.status_code])
    assert statuses == [200, 400], (r1.text, r2.text)


async def test_confirm_invalidates_existing_session_token(
    client, registered_user
):
    """The auth token in registered_user['headers'] was issued with the
    pre-reset ``tv``; after /confirm bumps it, the old token must fail
    /me even though it hasn't expired yet."""
    token = await _reset_token_for(registered_user["user"]["id"])

    r = await client.post(
        "/api/password-reset/confirm",
        json={"token": token, "new_password": "new-rotated-pwd"},
    )
    assert r.status_code == 200

    me = await client.get("/api/me", headers=registered_user["headers"])
    assert me.status_code == 401


async def test_confirm_closes_open_ws_notifications(
    client, registered_user
):
    """Same WS hygiene as /change-password: any socket authenticated
    with the now-invalid tv must be closed so the post-reset session
    doesn't keep receiving pushes."""
    from app.services.websocket_manager import manager

    class _StubWS:
        def __init__(self):
            self.closed_with: int | None = None

        async def close(self, code: int = 1000):
            self.closed_with = code

    stub_a, stub_b = _StubWS(), _StubWS()
    user_id = registered_user["user"]["id"]
    manager.user_connections[user_id] = [stub_a, stub_b]

    token = await _reset_token_for(user_id)

    r = await client.post(
        "/api/password-reset/confirm",
        json={"token": token, "new_password": "ws-rotation-pwd"},
    )
    assert r.status_code == 200
    assert stub_a.closed_with == 1008
    assert stub_b.closed_with == 1008
    assert user_id not in manager.user_connections


async def test_confirm_fires_password_changed_notice(
    client, registered_user, capture_emails
):
    """After a successful reset, send a "your password was changed"
    notification email so the legitimate user notices the trail even
    if the reset itself was triggered by someone in their inbox."""
    token = await _reset_token_for(registered_user["user"]["id"])

    r = await client.post(
        "/api/password-reset/confirm",
        json={"token": token, "new_password": "notice-rotation-pwd"},
    )
    assert r.status_code == 200
    assert len(capture_emails) == 1
    to_email, subject, _html = capture_emails[0]
    assert to_email == registered_user["user"]["email"]
    assert "пароль" in subject.lower()


async def test_confirm_rejects_short_password(client, registered_user):
    """min_length=8 must reject before the JWT is even decoded - same
    schema cap as /register and /change-password."""
    token = _make_token(registered_user["user"]["id"], 0)
    r = await client.post(
        "/api/password-reset/confirm",
        json={"token": token, "new_password": "short"},
    )
    assert r.status_code == 422


@pytest.mark.parametrize("missing_field", ["user_id", "tv", "purpose"])
async def test_confirm_rejects_malformed_token(
    client, registered_user, missing_field
):
    """Tokens missing required claims fail at decode. Defensive
    type-checks on user_id/tv mean a token issuer that accidentally
    widens the schema can't sneak through with `null`s."""
    payload = {
        "user_id": registered_user["user"]["id"],
        "tv": 0,
        "purpose": PASSWORD_RESET_PURPOSE,
        "exp": utcnow() + timedelta(hours=1),
    }
    payload.pop(missing_field)
    token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
    r = await client.post(
        "/api/password-reset/confirm",
        json={"token": token, "new_password": "yet-another-pwd"},
    )
    assert r.status_code == 400
