async def test_register_creates_user_and_returns_token(client):
    response = await client.post("/api/register", json={
        "username": "newuser",
        "email": "new@example.com",
        "password": "secret123",
    })
    assert response.status_code == 200
    body = response.json()
    assert "token" in body
    assert body["user"]["username"] == "newuser"
    assert body["user"]["email"] == "new@example.com"
    assert body["user"]["balance"] == 1000.0


async def test_register_duplicate_username_or_email_indistinguishable(
    client, registered_user
):
    """Reply for "username taken" must look identical to "email taken" so
    /register can't be used to enumerate registered usernames or emails."""
    r_username = await client.post("/api/register", json={
        "username": registered_user["user"]["username"],
        "email": "different@example.com",
        "password": "whatever",
    })
    r_email = await client.post("/api/register", json={
        "username": "different",
        "email": registered_user["user"]["email"],
        "password": "whatever",
    })
    assert r_username.status_code == 400
    assert r_email.status_code == 400
    assert r_username.json()["detail"] == r_email.json()["detail"]


async def test_login_with_correct_password(client, registered_user):
    response = await client.post("/api/login", json={
        "username": registered_user["user"]["username"],
        "password": registered_user["password"],
    })
    assert response.status_code == 200
    assert "token" in response.json()


async def test_login_with_wrong_password_returns_401(client, registered_user):
    response = await client.post("/api/login", json={
        "username": registered_user["user"]["username"],
        "password": "wrong-password",
    })
    assert response.status_code == 401


async def test_me_returns_current_user(client, registered_user):
    response = await client.get("/api/me", headers=registered_user["headers"])
    assert response.status_code == 200
    assert response.json()["username"] == registered_user["user"]["username"]


async def test_me_without_token_rejected(client):
    response = await client.get("/api/me")
    # FastAPI ≥ 0.116 returns 401 (semantically correct: no creds = unauthenticated)
    # — earlier versions returned 403 for the same condition.
    assert response.status_code == 401


async def test_bcrypt_hash_upgraded_to_argon2_on_login(client):
    """Existing accounts hashed with bcrypt are still accepted, and the
    successful login rotates the row to argon2id transparently."""
    from passlib.context import CryptContext

    from app.database import SessionLocal
    from app.models import User

    bcrypt_only = CryptContext(schemes=["bcrypt"], deprecated="auto")
    legacy_hash = bcrypt_only.hash("password123")
    assert legacy_hash.startswith("$2"), legacy_hash

    async with SessionLocal() as db:
        db.add(User(
            username="legacy",
            email="legacy@example.com",
            hashed_password=legacy_hash,
        ))
        await db.commit()

    r = await client.post("/api/login", json={
        "username": "legacy", "password": "password123",
    })
    assert r.status_code == 200

    async with SessionLocal() as db:
        from sqlalchemy import select
        stored = await db.scalar(
            select(User.hashed_password).where(User.username == "legacy")
        )
    assert stored.startswith("$argon2"), stored


def test_hash_password_rejects_oversized_input():
    """Defensive cap inside ``hash_password``: Pydantic enforces 128
    chars on the API boundary, but a direct caller (or a future
    schema with no max_length) shouldn't be able to feed multi-MB
    strings into argon2."""
    import pytest

    from app.utils.security import PASSWORD_INPUT_LIMIT, hash_password

    oversized = "x" * (PASSWORD_INPUT_LIMIT + 1)
    with pytest.raises(ValueError):
        hash_password(oversized)


def test_verify_password_rejects_oversized_input():
    """An oversized password can never be a valid credential — we
    never accept it for hashing — so reject without spending CPU on
    argon2/bcrypt verification."""
    from app.utils.security import (
        PASSWORD_INPUT_LIMIT,
        hash_password,
        verify_password,
    )

    real_hash = hash_password("password123")
    assert verify_password("password123", real_hash) is True
    assert verify_password("x" * (PASSWORD_INPUT_LIMIT + 1), real_hash) is False



async def test_change_password_invalidates_old_jwt(client, registered_user):
    """JWT issued before /change-password must stop working — the
    token_version bump makes get_current_user reject anything stamped
    with the old version."""
    old_headers = registered_user["headers"]

    r = await client.put(
        "/api/change-password",
        json={"current_password": registered_user["password"], "new_password": "newpass456"},
        headers=old_headers,
    )
    assert r.status_code == 200, r.text
    new_token = r.json()["token"]
    assert new_token

    me_old = await client.get("/api/me", headers=old_headers)
    assert me_old.status_code == 401

    me_new = await client.get(
        "/api/me", headers={"Authorization": f"Bearer {new_token}"}
    )
    assert me_new.status_code == 200


async def test_change_password_closes_open_ws_notifications(client, registered_user):
    """/ws/notifications validates token_version only at handshake. After
    /change-password bumps the version, any already-open socket — including
    one authenticated with a leaked token — must be closed so it stops
    receiving pushes."""
    from app.services.websocket_manager import manager

    class _StubWS:
        def __init__(self):
            self.closed_with: int | None = None

        async def close(self, code: int = 1000):
            self.closed_with = code

    stub_a, stub_b = _StubWS(), _StubWS()
    user_id = registered_user["user"]["id"]
    manager.user_connections[user_id] = [stub_a, stub_b]

    r = await client.put(
        "/api/change-password",
        json={"current_password": registered_user["password"], "new_password": "newpass456"},
        headers=registered_user["headers"],
    )
    assert r.status_code == 200, r.text

    assert stub_a.closed_with == 1008
    assert stub_b.closed_with == 1008
    assert user_id not in manager.user_connections


async def test_login_unknown_user_consumes_verify_time(client, registered_user, monkeypatch):
    """Unknown usernames used to short-circuit before verify_password,
    leaking 'user-exists' via response timing. The handler must now run
    the verifier against a precomputed dummy hash so both branches
    spend the same CPU."""
    calls: list[str] = []
    from app.utils import security

    original = security.consume_password_verify_time

    def tracking(password):
        calls.append("called")
        return original(password)

    monkeypatch.setattr(security, "consume_password_verify_time", tracking)
    # The router imports the name directly; patch the local import too.
    from app.routers import auth as auth_router
    monkeypatch.setattr(auth_router, "consume_password_verify_time", tracking)

    r = await client.post("/api/login", json={
        "username": "does-not-exist",
        "password": "anything",
    })
    assert r.status_code == 401
    assert calls, "consume_password_verify_time was not invoked for unknown user"


async def test_register_concurrent_duplicate_returns_400_not_500(client):
    """Two simultaneous /register with the same username pass the
    pre-check together and race to insert. Postgres unique-constraint
    makes the loser raise IntegrityError; the handler must translate
    that into 400 (same generic message), not bubble up as 500."""
    import asyncio

    payload = {
        "username": "racer",
        "email_template": "racer{}@example.com",
        "password": "password123",
    }
    r_a, r_b = await asyncio.gather(
        client.post("/api/register", json={
            "username": payload["username"],
            "email": payload["email_template"].format("a"),
            "password": payload["password"],
        }),
        client.post("/api/register", json={
            "username": payload["username"],
            "email": payload["email_template"].format("b"),
            "password": payload["password"],
        }),
    )
    statuses = sorted([r_a.status_code, r_b.status_code])
    assert statuses == [200, 400], (r_a.text, r_b.text)
