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


async def test_register_rejects_html_in_username(client):
    """Defence-in-depth: usernames flow into Notification.message and
    listing pages. The frontend escapes through esc() everywhere, but
    constraining the source means a future render-path regression
    that calls innerHTML directly on a username can't be exploited."""
    r = await client.post("/api/register", json={
        "username": "<img src=x onerror=alert(1)>",
        "email": "evil@example.com",
        "password": "secret123",
    })
    assert r.status_code == 422, r.text


async def test_register_accepts_cyrillic_username(client):
    """Cyrillic charset passes the validator AND gets folded to lower
    case at the input boundary, so the stored handle is canonical and
    @-mentions / profile URLs case-collapse on both sides."""
    r = await client.post("/api/register", json={
        "username": "Алиса",
        "email": "alisa@example.com",
        "password": "secret123",
    })
    assert r.status_code == 200, r.text
    # ``Алиса`` lowercases to ``алиса`` via str.lower() Unicode handling.
    assert r.json()["user"]["username"] == "алиса"


async def test_register_case_insensitive_collision_rejected(
    client, registered_user
):
    """Registering 'ALICE' must collide with the already-registered
    'alice' from the fixture - the input is case-folded before the
    duplicate check, so 'Alice' / 'alice' / 'ALICE' resolve to the
    same row."""
    r = await client.post("/api/register", json={
        "username": registered_user["user"]["username"].upper(),
        "email": "different@example.com",
        "password": "secret123",
    })
    assert r.status_code == 400


async def test_register_lowercases_email(client):
    """``EmailStr`` only normalises the domain; the handler must fold the
    local part too so the stored email is canonical."""
    r = await client.post("/api/register", json={
        "username": "mixedcase",
        "email": "MixedCase@Example.COM",
        "password": "secret123",
    })
    assert r.status_code == 200, r.text
    assert r.json()["user"]["email"] == "mixedcase@example.com"


async def test_register_case_insensitive_email_collision_rejected(client):
    """Two registrations whose emails differ only in case must collide -
    otherwise the case-sensitive UNIQUE index lets duplicate accounts in
    and a password reset keyed on the other casing silently misses."""
    first = await client.post("/api/register", json={
        "username": "userone",
        "email": "Dup@Example.com",
        "password": "secret123",
    })
    assert first.status_code == 200, first.text
    second = await client.post("/api/register", json={
        "username": "usertwo",
        "email": "dup@example.com",
        "password": "secret123",
    })
    assert second.status_code == 400


async def test_login_case_insensitive_username(client, registered_user):
    """The login form accepts whatever case the user typed; the
    handler folds it to the stored canonical form before lookup."""
    r = await client.post("/api/login", json={
        "username": registered_user["user"]["username"].upper(),
        "password": registered_user["password"],
    })
    assert r.status_code == 200


async def test_profile_lookup_case_insensitive(client, registered_user):
    """``/api/users/{username}`` resolves the path param case-insensitively
    so a link with uppercase in it still lands on the right profile."""
    upper = registered_user["user"]["username"].upper()
    r = await client.get(f"/api/users/{upper}")
    assert r.status_code == 200
    assert r.json()["user"]["username"] == registered_user["user"]["username"]


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


async def test_login_locks_account_after_five_failures(client, registered_user):
    """Per-account credential-stuffing defence: after 5 consecutive
    bad-password attempts the account is locked for a minute and even
    a correct-password attempt during the window returns the generic
    401, so the lock-state isn't a username-enumeration oracle."""
    username = registered_user["user"]["username"]
    for _ in range(5):
        r = await client.post(
            "/api/login",
            json={"username": username, "password": "wrong"},
        )
        assert r.status_code == 401, r.text

    # 6th attempt - correct password - still rejected because the
    # account is locked.
    r_locked = await client.post(
        "/api/login",
        json={"username": username, "password": registered_user["password"]},
    )
    assert r_locked.status_code == 401, r_locked.text


async def test_successful_login_clears_failure_streak(
    client, registered_user
):
    """One or two bad attempts don't lock the account, and a
    successful login zeroes the counter so the next bad attempt
    starts from zero again rather than landing immediately at the
    5-failure threshold."""
    username = registered_user["user"]["username"]
    pw = registered_user["password"]

    for _ in range(4):
        r = await client.post(
            "/api/login",
            json={"username": username, "password": "wrong"},
        )
        assert r.status_code == 401

    # Successful login resets the streak.
    r_ok = await client.post(
        "/api/login", json={"username": username, "password": pw}
    )
    assert r_ok.status_code == 200, r_ok.text

    # Four more wrong attempts then a fifth would have locked the
    # account if the reset didn't fire; the fifth here is still ok.
    for _ in range(4):
        r = await client.post(
            "/api/login",
            json={"username": username, "password": "wrong"},
        )
        assert r.status_code == 401

    r_still_ok = await client.post(
        "/api/login", json={"username": username, "password": pw}
    )
    assert r_still_ok.status_code == 200, r_still_ok.text


async def test_login_oversized_password_rejected_at_schema(client, registered_user):
    """UserLogin.password caps at 128 chars (matches UserCreate /
    ChangePasswordRequest). Without this, /login would parse a multi-MB
    JSON body before verify_password's internal byte-limit kicked in -
    pointless CPU and memory for a request that can't possibly succeed."""
    response = await client.post("/api/login", json={
        "username": registered_user["user"]["username"],
        "password": "x" * 129,
    })
    assert response.status_code == 422


async def test_me_returns_current_user(client, registered_user):
    response = await client.get("/api/me", headers=registered_user["headers"])
    assert response.status_code == 200
    assert response.json()["username"] == registered_user["user"]["username"]


async def test_me_without_token_rejected(client):
    response = await client.get("/api/me")
    # FastAPI ≥ 0.116 returns 401 (semantically correct: no creds = unauthenticated)
    # - earlier versions returned 403 for the same condition.
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
    """An oversized password can never be a valid credential - we
    never accept it for hashing - so reject without spending CPU on
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
    """JWT issued before /change-password must stop working - the
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
    /change-password bumps the version, any already-open socket - including
    one authenticated with a leaked token - must be closed so it stops
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


async def test_change_password_with_wrong_current_rejected(client, registered_user):
    """Covers the ``verify_password`` failure branch in /change-password
    (auth.py:196-197). Without this, the suite only exercises the
    success path."""
    r = await client.put(
        "/api/change-password",
        json={
            "current_password": "definitely-not-my-password",
            "new_password": "anything-new",
        },
        headers=registered_user["headers"],
    )
    assert r.status_code == 400
