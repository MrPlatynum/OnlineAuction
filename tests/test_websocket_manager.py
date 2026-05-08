"""ConnectionManager unit tests.

Exercises the broadcast fan-out's dead-connection cleanup directly
against the manager so we don't need a full WebSocket testing harness.
A previous version of broadcast just swallowed the exception and left
the dead socket in the bucket — every subsequent broadcast then
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
