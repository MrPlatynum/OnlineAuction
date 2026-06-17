"""Direct unit tests for the WebSocket router endpoints.

Drives the endpoint coroutines with a hand-rolled fake socket - same
pattern as ``_StubSocket`` in test_bids.py / test_websocket_manager.py
but extended to the methods the router itself touches (accept, close,
receive_text, headers, client). This exercises the auth / rate-limit /
cap / disconnect-cleanup paths without a real WS handshake.
"""

from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi import WebSocketDisconnect

from app.database import SessionLocal
from app.models import Auction, User
from app.routers import websocket as ws_router
from app.services.websocket_manager import manager
from app.utils.security import create_access_token, hash_password
from app.utils.time import utcnow


class FakeWebSocket:
    """Minimal stand-in for starlette.websockets.WebSocket sufficient to
    drive routers.websocket. ``incoming`` is a FIFO of items to return
    from receive_text; non-string items that are exception instances are
    raised instead of returned."""

    def __init__(self, *, host: str = "1.2.3.4", headers: dict | None = None):
        self.client = SimpleNamespace(host=host)
        self.headers = headers or {}
        self.accepted = False
        self.subprotocol: str | None = None
        self.close_code: int | None = None
        self.sent: list[dict] = []
        self.incoming: list = []

    async def accept(self, subprotocol: str | None = None):
        self.accepted = True
        self.subprotocol = subprotocol

    async def close(self, code: int):
        self.close_code = code

    async def receive_text(self) -> str:
        if not self.incoming:
            raise WebSocketDisconnect()
        item = self.incoming.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    async def send_json(self, msg: dict):
        self.sent.append(msg)


async def _make_user(username: str = "ws_user") -> User:
    async with SessionLocal() as db:
        user = User(
            username=username,
            email=f"{username}@example.com",
            hashed_password=hash_password("password123"),
            email_verified=True,
            token_version=0,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


async def _make_auction(seller: User, *, ends_in_minutes: int = 60) -> Auction:
    async with SessionLocal() as db:
        now = utcnow()
        auction = Auction(
            created_by=seller.id,
            title="WS test lot",
            description="...",
            starting_price=100,
            current_price=100,
            start_time=now,
            end_time=now + timedelta(minutes=ends_in_minutes),
            is_active=True,
            auction_type="bid",
        )
        db.add(auction)
        await db.commit()
        await db.refresh(auction)
        return auction


# ---------------------------------------------------------------------
# /ws/auction/{id}
# ---------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_per_ip_registry():
    """The per-IP counter is module-level state; cross-test leakage
    would let one test's "exhausted" IP affect the next test's
    "first connect". Reset before and after each."""
    ws_router._auction_ws_per_ip.clear()
    yield
    ws_router._auction_ws_per_ip.clear()


async def test_auction_ws_caps_per_ip():
    """Once an IP holds MAX_AUCTION_WS_PER_IP sockets, the next attempt
    is rejected with close code 1008 before any manager.connect."""
    ip = "9.9.9.9"
    ws_router._auction_ws_per_ip[ip] = ws_router.MAX_AUCTION_WS_PER_IP
    fake = FakeWebSocket(host=ip)
    await ws_router.websocket_endpoint(fake, auction_id=1)
    assert fake.close_code == 1008
    assert not fake.accepted
    # Counter unchanged - the rejected attempt didn't increment.
    assert ws_router._auction_ws_per_ip[ip] == ws_router.MAX_AUCTION_WS_PER_IP


async def test_auction_ws_releases_slot_on_disconnect():
    """Successful connect that immediately disconnects must release the
    per-IP slot (the finally block pops the key when count reaches 0)."""
    fake = FakeWebSocket(host="2.2.2.2")
    # Empty incoming queue -> first receive_text raises WebSocketDisconnect.
    await ws_router.websocket_endpoint(fake, auction_id=999)
    assert fake.accepted
    assert "2.2.2.2" not in ws_router._auction_ws_per_ip


async def test_auction_ws_broadcasts_time_update_on_message():
    """A receive_text returning a string triggers the auction DB lookup
    and a time_update payload back over the socket."""
    seller = await _make_user("seller1")
    auction = await _make_auction(seller)

    fake = FakeWebSocket(host="3.3.3.3")
    fake.incoming = ["client_hello"]  # one message, then disconnect

    await ws_router.websocket_endpoint(fake, auction_id=auction.id)

    assert any(m.get("type") == "time_update" for m in fake.sent)
    update = next(m for m in fake.sent if m["type"] == "time_update")
    assert update["current_price"] == 100.0
    assert update["time_remaining"] > 0


async def test_auction_ws_rate_limit_drops_extra_messages():
    """The sliding-window cap (30 messages / 60 s) silently swallows
    extra messages without hitting Postgres or sending more time_updates."""
    seller = await _make_user("seller2")
    auction = await _make_auction(seller)

    fake = FakeWebSocket(host="4.4.4.4")
    # Queue cap + 5 - we must see exactly cap time_update replies.
    cap = ws_router.WS_AUCTION_MSG_MAX_PER_WINDOW
    fake.incoming = ["m"] * (cap + 5)

    await ws_router.websocket_endpoint(fake, auction_id=auction.id)

    updates = [m for m in fake.sent if m.get("type") == "time_update"]
    assert len(updates) == cap, (
        f"expected exactly {cap} time_update replies under the message cap, got {len(updates)}"
    )


async def test_auction_ws_ping_on_receive_timeout():
    """receive_text raising TimeoutError triggers a ping back to the
    client so the front-end can detect a stuck server."""
    fake = FakeWebSocket(host="5.5.5.5")
    # First receive: timeout -> ping. Second receive: disconnect.
    fake.incoming = [TimeoutError()]
    await ws_router.websocket_endpoint(fake, auction_id=42)
    assert any(m == {"type": "ping"} for m in fake.sent)


async def test_auction_ws_unknown_auction_skips_send():
    """Unknown auction_id - the if-branch is False, no time_update sent.
    The connection still survives until disconnect."""
    fake = FakeWebSocket(host="6.6.6.6")
    fake.incoming = ["m"]
    await ws_router.websocket_endpoint(fake, auction_id=999_999)
    assert all(m.get("type") != "time_update" for m in fake.sent)


# ---------------------------------------------------------------------
# /ws/notifications/{user_id}
# ---------------------------------------------------------------------

async def test_notifications_ws_no_token_closes_1008():
    """No Sec-WebSocket-Protocol header at all - reject before any DB hit."""
    fake = FakeWebSocket(headers={})
    await ws_router.notifications_websocket(fake, user_id=1)
    assert fake.close_code == 1008
    assert not fake.accepted


async def test_notifications_ws_malformed_subprotocol_closes_1008():
    """Subprotocol present but doesn't start with 'bearer, <jwt>' -
    treated as missing token."""
    fake = FakeWebSocket(headers={"sec-websocket-protocol": "graphql-ws"})
    await ws_router.notifications_websocket(fake, user_id=1)
    assert fake.close_code == 1008


async def test_notifications_ws_invalid_token_closes_1008():
    """JWT signature/format invalid - decode raises HTTPException, close."""
    fake = FakeWebSocket(headers={"sec-websocket-protocol": "bearer, not.a.real.jwt"})
    await ws_router.notifications_websocket(fake, user_id=1)
    assert fake.close_code == 1008


async def test_notifications_ws_user_id_mismatch_closes_1008():
    """Token says user A, URL path says user B - reject (one user must
    not subscribe to another's channel even with a valid token)."""
    user = await _make_user("nws_owner")
    token = create_access_token({"user_id": user.id, "tv": user.token_version})

    fake = FakeWebSocket(headers={"sec-websocket-protocol": f"bearer, {token}"})
    await ws_router.notifications_websocket(fake, user_id=user.id + 999)
    assert fake.close_code == 1008


async def test_notifications_ws_token_version_mismatch_closes_1008():
    """Token issued before /change-password bumped token_version is
    rejected at the WS gate same as at get_current_user."""
    user = await _make_user("nws_pwchange")
    stale_token = create_access_token({"user_id": user.id, "tv": 0})

    # Bump the user's version after the token was minted.
    async with SessionLocal() as db:
        db_user = await db.get(User, user.id)
        db_user.token_version = 5
        await db.commit()

    fake = FakeWebSocket(headers={"sec-websocket-protocol": f"bearer, {stale_token}"})
    await ws_router.notifications_websocket(fake, user_id=user.id)
    assert fake.close_code == 1008


async def test_notifications_ws_rejects_token_without_tv_claim():
    """A forged or pre-rollout legacy token without the ``tv`` claim
    used to silently match a fresh account whose ``token_version``
    defaults to 0. The handler now requires the claim to be present;
    missing-claim tokens are 1008-closed same as a mismatched one."""
    user = await _make_user("nws_no_tv")
    token = create_access_token({"user_id": user.id})  # no tv

    fake = FakeWebSocket(headers={"sec-websocket-protocol": f"bearer, {token}"})
    await ws_router.notifications_websocket(fake, user_id=user.id)
    assert fake.close_code == 1008


async def test_notifications_ws_accepts_valid_token_with_subprotocol_echo():
    """Valid token + matching user_id + current tv: accept with
    subprotocol="bearer" echoed back (RFC 6455 §1.9), register socket
    in the user_connections bucket."""
    user = await _make_user("nws_ok")
    token = create_access_token({"user_id": user.id, "tv": user.token_version})

    fake = FakeWebSocket(headers={"sec-websocket-protocol": f"bearer, {token}"})
    # No incoming messages -> first receive raises WebSocketDisconnect.
    await ws_router.notifications_websocket(fake, user_id=user.id)

    assert fake.accepted, "valid handshake must accept the socket"
    assert fake.subprotocol == "bearer", "server must echo the offered subprotocol"
    # disconnect path ran -> bucket cleaned.
    assert user.id not in manager.user_connections or manager.user_connections[user.id] == []


async def test_notifications_ws_ping_on_receive_timeout():
    """Same idle-ping path as the auction socket, but on the
    notifications channel."""
    user = await _make_user("nws_ping")
    token = create_access_token({"user_id": user.id, "tv": user.token_version})

    fake = FakeWebSocket(headers={"sec-websocket-protocol": f"bearer, {token}"})
    fake.incoming = [TimeoutError()]
    await ws_router.notifications_websocket(fake, user_id=user.id)
    assert {"type": "ping"} in fake.sent


# ---------------------------------------------------------------------
# /health 503 branch (separate from WS but small uncovered slice in the
# same module-level audit)
# ---------------------------------------------------------------------

async def test_health_returns_503_when_db_ping_fails(client, monkeypatch):
    """Force the SELECT 1 to raise - the handler must downgrade to 503
    and report ``status: degraded``."""
    from app.database import get_db

    class _RaisingSession:
        async def execute(self, *_a, **_kw):
            raise RuntimeError("simulated outage")

    async def _override_get_db():
        yield _RaisingSession()

    from app import app as fastapi_app
    fastapi_app.dependency_overrides[get_db] = _override_get_db
    try:
        r = await client.get("/health")
    finally:
        fastapi_app.dependency_overrides.pop(get_db, None)

    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "degraded"
    assert body["db"] == "fail"
