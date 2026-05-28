"""ConnectionManager unit tests.

Exercises the broadcast fan-out's dead-connection cleanup directly
against the manager so we don't need a full WebSocket testing harness.
A previous version of broadcast just swallowed the exception and left
the dead socket in the bucket - every subsequent broadcast then
iterated growing piles of dead sockets and re-raised.
"""

import pytest

from app.services.websocket_manager import ConnectionManager


class _StubWebSocket:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.sent: list[dict] = []

    async def send_json(self, message: dict):
        if self.fail:
            raise RuntimeError("connection dropped")
        self.sent.append(message)


@pytest.mark.asyncio
async def test_broadcast_drops_dead_connections():
    mgr = ConnectionManager()
    alive = _StubWebSocket()
    dead = _StubWebSocket(fail=True)
    mgr.active_connections[1] = [alive, dead]

    await mgr.broadcast({"hello": "world"}, 1)

    assert alive.sent == [{"hello": "world"}]
    assert mgr.active_connections.get(1) == [alive]


@pytest.mark.asyncio
async def test_broadcast_clears_empty_bucket():
    mgr = ConnectionManager()
    dead = _StubWebSocket(fail=True)
    mgr.active_connections[7] = [dead]

    await mgr.broadcast({"x": 1}, 7)

    # Last dead socket removed → key removed entirely so the dict
    # doesn't grow unbounded with stale auction ids.
    assert 7 not in mgr.active_connections


@pytest.mark.asyncio
async def test_send_notification_drops_dead_connections():
    mgr = ConnectionManager()
    alive = _StubWebSocket()
    dead = _StubWebSocket(fail=True)
    mgr.user_connections[42] = [alive, dead]

    await mgr.send_notification(42, {"type": "ping"})

    assert alive.sent == [{"type": "ping"}]
    assert mgr.user_connections[42] == [alive]


@pytest.mark.asyncio
async def test_disconnect_clears_empty_bucket():
    mgr = ConnectionManager()
    sock = _StubWebSocket()
    mgr.active_connections[3] = [sock]
    mgr.disconnect(sock, 3)
    assert 3 not in mgr.active_connections


class _DisconnectingWebSocket(_StubWebSocket):
    """Stub that disconnects ``victim`` mid-send. Reproduces the race
    where a concurrent ``disconnect`` mutates the bucket while
    ``_fan_out`` is iterating it: when an *earlier* element is removed,
    a plain ``for conn in bucket`` shifts list indices and silently
    skips a later, live socket."""

    def __init__(self, mgr: ConnectionManager, key: int, victim: _StubWebSocket):
        super().__init__()
        self._mgr = mgr
        self._key = key
        self._victim = victim

    async def send_json(self, message: dict):
        await super().send_json(message)
        self._mgr.disconnect(self._victim, self._key)


class _SlowWebSocket(_StubWebSocket):
    """Stub whose ``send_json`` hangs longer than the fan-out per-socket
    deadline. Models a half-open peer (silent NAT timeout, frozen tab,
    stalled kernel send buffer) - the receiver simply never ACKs."""

    async def send_json(self, message: dict):
        await asyncio.sleep(10)
        self.sent.append(message)


@pytest.mark.asyncio
async def test_broadcast_drops_slow_recipient_without_stalling_others(monkeypatch):
    """A half-open peer used to block the entire ``_fan_out`` loop while
    its ``send_json`` waited indefinitely; every other subscriber of a
    hot lot would then hang behind it. The per-socket ``wait_for``
    cap drops the stalled socket and lets the rest of the bucket
    receive normally."""
    from app.services import websocket_manager as ws_mod

    # Cap to a small value so the test doesn't actually wait 2s.
    monkeypatch.setattr(ws_mod, "_SEND_TIMEOUT_SECS", 0.05)

    mgr = ConnectionManager()
    fast_before = _StubWebSocket()
    slow = _SlowWebSocket()
    fast_after = _StubWebSocket()
    mgr.active_connections[11] = [fast_before, slow, fast_after]

    await mgr.broadcast({"v": 42}, 11)

    assert fast_before.sent == [{"v": 42}]
    assert fast_after.sent == [{"v": 42}]
    # Slow peer's send_json never completed; the socket was treated as
    # dead and pruned from the bucket.
    assert slow.sent == []
    assert slow not in mgr.active_connections[11]


@pytest.mark.asyncio
async def test_broadcast_iteration_safe_against_concurrent_disconnect():
    """While broadcasting to [a, b, c], b's send_json removes a from the
    bucket (e.g. a's WS client closed and a cleanup coroutine ran during
    b's send await). A naive ``for x in bucket`` then advances index 2
    past the end and skips c entirely - the snapshot in _fan_out
    prevents that."""
    mgr = ConnectionManager()
    a = _StubWebSocket()
    c = _StubWebSocket()
    b = _DisconnectingWebSocket(mgr, 9, a)
    mgr.active_connections[9] = [a, b, c]

    await mgr.broadcast({"v": 1}, 9)

    # Key invariant: c still receives the message even though a was
    # removed mid-iteration. Without the snapshot, c is skipped.
    assert c.sent == [{"v": 1}]
    # Bucket reflects the in-flight disconnect of a.
    assert mgr.active_connections[9] == [b, c]
