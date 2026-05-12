"""Password-reset flow.

The reset token is stateless and embeds the user's ``token_version``;
a successful /confirm bumps tv so the same link can't be used twice
and any in-flight auth tokens / other reset links for the same
account also get invalidated. The /request endpoint is
anti-enumeration: always 200, with a per-email 60s throttle on top
of the per-IP slowapi limit.
"""

from datetime import timedelta

import jwt
import pytest

from app.config import ALGORITHM, SECRET_KEY
from app.utils.security import (
    PASSWORD_RESET_PURPOSE,
    create_password_reset_token,
)
from app.utils.time import utcnow


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


async def test_request_for_existing_email_sends_mail(client, registered_user, monkeypatch):
    calls: list[tuple[str, str, str]] = []
    from app.services import notifications as notif_mod

    monkeypatch.setattr(
        notif_mod,
        "_fire_and_forget_email",
        lambda to, subj, html: calls.append((to, subj, html)),
    )

    r = await client.post(
        "/api/password-reset/request",
        json={"email": registered_user["user"]["email"]},
    )
    assert r.status_code == 200
    assert len(calls) == 1
    assert calls[0][0] == registered_user["user"]["email"]
    assert "password-reset.html?token=" in calls[0][2]


async def test_request_for_unknown_email_returns_200_silently(client, monkeypatch):
    """Anti-enumeration: response shape must be identical to the
    happy path so an attacker can't probe which addresses are
    registered."""
    calls: list[tuple[str, str, str]] = []
    from app.services import notifications as notif_mod

    monkeypatch.setattr(
        notif_mod,
        "_fire_and_forget_email",
        lambda to, subj, html: calls.append((to, subj, html)),
    )

    r = await client.post(
        "/api/password-reset/request",
        json={"email": "no-such-user@example.com"},
    )
    assert r.status_code == 200
    assert calls == []


async def test_request_per_email_throttle_skips_second_send(
    client, registered_user, monkeypatch
):
    """Two /request calls within 60s for the same email: the first
    sends a mail, the second silently returns 200 without sending.
    This is per-email, distinct from the per-IP slowapi limit."""
    calls: list[tuple[str, str, str]] = []
    from app.services import notifications as notif_mod

    monkeypatch.setattr(
        notif_mod,
        "_fire_and_forget_email",
        lambda to, subj, html: calls.append((to, subj, html)),
    )

    email = registered_user["user"]["email"]
    r1 = await client.post("/api/password-reset/request", json={"email": email})
    r2 = await client.post("/api/password-reset/request", json={"email": email})
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert len(calls) == 1


async def test_confirm_with_valid_token_resets_password(
    client, registered_user, monkeypatch
):
    """End-to-end: token from create_password_reset_token → confirm →
    /login with new password works, /login with old fails."""
    monkeypatch.setattr(
        "app.services.notifications._fire_and_forget_email",
        lambda *_args, **_kw: None,
    )

    from sqlalchemy import select

    from app.database import SessionLocal
    from app.models import User

    async with SessionLocal() as db:
        user = (await db.execute(
            select(User).where(User.id == registered_user["user"]["id"])
        )).scalar_one()
        token = create_password_reset_token(user)

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


async def test_confirm_with_expired_token(client, registered_user, monkeypatch):
    monkeypatch.setattr(
        "app.services.notifications._fire_and_forget_email",
        lambda *_a, **_kw: None,
    )
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
    """An auth token must NOT double as a reset token — otherwise a
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
    client, registered_user, monkeypatch
):
    """The token's ``tv`` claim is checked against the user's row.
    The first /confirm bumps tv to (old+1); the second click on
    the same link still carries tv=(old) → mismatch → 400."""
    monkeypatch.setattr(
        "app.services.notifications._fire_and_forget_email",
        lambda *_a, **_kw: None,
    )

    from sqlalchemy import select

    from app.database import SessionLocal
    from app.models import User

    async with SessionLocal() as db:
        user = (await db.execute(
            select(User).where(User.id == registered_user["user"]["id"])
        )).scalar_one()
        token = create_password_reset_token(user)

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


async def test_confirm_invalidates_existing_session_token(
    client, registered_user, monkeypatch
):
    """The auth token in registered_user['headers'] was issued with the
    pre-reset ``tv``; after /confirm bumps it, the old token must fail
    /me even though it hasn't expired yet."""
    monkeypatch.setattr(
        "app.services.notifications._fire_and_forget_email",
        lambda *_a, **_kw: None,
    )

    from sqlalchemy import select

    from app.database import SessionLocal
    from app.models import User

    async with SessionLocal() as db:
        user = (await db.execute(
            select(User).where(User.id == registered_user["user"]["id"])
        )).scalar_one()
        token = create_password_reset_token(user)

    r = await client.post(
        "/api/password-reset/confirm",
        json={"token": token, "new_password": "new-rotated-pwd"},
    )
    assert r.status_code == 200

    me = await client.get("/api/me", headers=registered_user["headers"])
    assert me.status_code == 401


async def test_confirm_closes_open_ws_notifications(
    client, registered_user, monkeypatch
):
    """Same WS hygiene as /change-password: any socket authenticated
    with the now-invalid tv must be closed so the post-reset session
    doesn't keep receiving pushes."""
    monkeypatch.setattr(
        "app.services.notifications._fire_and_forget_email",
        lambda *_a, **_kw: None,
    )

    from app.services.websocket_manager import manager

    class _StubWS:
        def __init__(self):
            self.closed_with: int | None = None

        async def close(self, code: int = 1000):
            self.closed_with = code

    stub_a, stub_b = _StubWS(), _StubWS()
    user_id = registered_user["user"]["id"]
    manager.user_connections[user_id] = [stub_a, stub_b]

    from sqlalchemy import select

    from app.database import SessionLocal
    from app.models import User

    async with SessionLocal() as db:
        user = (await db.execute(
            select(User).where(User.id == user_id)
        )).scalar_one()
        token = create_password_reset_token(user)

    r = await client.post(
        "/api/password-reset/confirm",
        json={"token": token, "new_password": "ws-rotation-pwd"},
    )
    assert r.status_code == 200
    assert stub_a.closed_with == 1008
    assert stub_b.closed_with == 1008
    assert user_id not in manager.user_connections


async def test_confirm_fires_password_changed_notice(
    client, registered_user, monkeypatch
):
    """After a successful reset, send a "your password was changed"
    notification email so the legitimate user notices the trail even
    if the reset itself was triggered by someone in their inbox."""
    calls: list[tuple[str, str, str]] = []
    from app.services import notifications as notif_mod

    monkeypatch.setattr(
        notif_mod,
        "_fire_and_forget_email",
        lambda to, subj, html: calls.append((to, subj, html)),
    )

    from sqlalchemy import select

    from app.database import SessionLocal
    from app.models import User

    async with SessionLocal() as db:
        user = (await db.execute(
            select(User).where(User.id == registered_user["user"]["id"])
        )).scalar_one()
        token = create_password_reset_token(user)

    r = await client.post(
        "/api/password-reset/confirm",
        json={"token": token, "new_password": "notice-rotation-pwd"},
    )
    assert r.status_code == 200
    assert len(calls) == 1
    to_email, subject, _html = calls[0]
    assert to_email == registered_user["user"]["email"]
    assert "пароль" in subject.lower() or "password" in subject.lower()


async def test_confirm_rejects_short_password(client, registered_user):
    """min_length=8 must reject before the JWT is even decoded — same
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
