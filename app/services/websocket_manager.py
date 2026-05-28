"""Process-local registry of live WebSocket connections.

Tracks anonymous per-auction sockets (``auction_connections``) and
authenticated per-user sockets (``user_connections``). The shared
``_fan_out`` loop is the only path that writes to the wire and
prunes dead sockets in-place - without that pruning the buckets
grow forever as tabs close without a clean shutdown handshake.
"""

import asyncio
import logging

from fastapi import WebSocket

logger = logging.getLogger(__name__)


# Per-recipient deadline for ``send_json``. A half-open peer (laptop
# closed lid, NAT timeout, intermediary buffering) that never ACKs
# would otherwise block the entire ``_fan_out`` loop while the kernel
# send buffer drains - every other subscriber of a hot lot then waits
# behind the dead socket. Two seconds is generous for a JSON payload
# of a few hundred bytes over WS; anything slower is treated as dead.
_SEND_TIMEOUT_SECS = 2.0


class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[int, list[WebSocket]] = {}  # auction_id -> websockets
        self.user_connections: dict[int, list[WebSocket]] = {}    # user_id -> websockets

    async def connect(self, websocket: WebSocket, auction_id: int):
        await websocket.accept()
        self.active_connections.setdefault(auction_id, []).append(websocket)

    async def connect_user(
        self, websocket: WebSocket, user_id: int, *, subprotocol: str | None = None
    ):
        # ``subprotocol`` echo is required by RFC 6455 §1.9 when the
        # client offered one - the notifications handshake passes
        # ``"bearer"`` so the JWT can ride as a subprotocol header
        # instead of leaking into URL access logs. Accept-side and
        # registry-write are funneled through this one helper so the
        # subprotocol path can't drift from the non-subprotocol path
        # (and any future bookkeeping added here applies to both).
        await websocket.accept(subprotocol=subprotocol)
        self.user_connections.setdefault(user_id, []).append(websocket)

    def disconnect(self, websocket: WebSocket, auction_id: int):
        bucket = self.active_connections.get(auction_id)
        if not bucket:
            return
        if websocket in bucket:
            bucket.remove(websocket)
        if not bucket:
            self.active_connections.pop(auction_id, None)

    def disconnect_user(self, websocket: WebSocket, user_id: int):
        bucket = self.user_connections.get(user_id)
        if not bucket:
            return
        if websocket in bucket:
            bucket.remove(websocket)
        if not bucket:
            self.user_connections.pop(user_id, None)

    async def broadcast(self, message: dict, auction_id: int):
        await self._fan_out(self.active_connections, auction_id, message)

    async def send_notification(self, user_id: int, message: dict):
        await self._fan_out(self.user_connections, user_id, message)

    async def _fan_out(self, registry: dict[int, list[WebSocket]], key: int, message: dict):
        """Send ``message`` to every socket under ``key``, dropping any
        connection whose ``send_json`` raises. Without the cleanup the
        bucket grows forever as clients silently drop off - every
        future broadcast then iterates dead sockets and re-raises."""
        bucket = registry.get(key)
        if not bucket:
            return
        # Snapshot the bucket: each ``await send_json`` below yields to the
        # event loop, and a concurrent ``disconnect`` calling ``bucket.remove``
        # would shift list indices under the live iterator and silently skip a
        # live socket. Iterating a copy is safe; pruning still mutates the
        # original below.
        snapshot = list(bucket)
        dead: list[WebSocket] = []
        for connection in snapshot:
            try:
                # ``wait_for`` so a half-open peer (silent NAT timeout,
                # stalled send buffer) can't block every other subscriber
                # behind it. A timed-out send drops the socket the same
                # way an exception would.
                await asyncio.wait_for(
                    connection.send_json(message), timeout=_SEND_TIMEOUT_SECS
                )
            except Exception as exc:
                logger.debug("Dropping dead websocket on %s: %s", key, exc)
                dead.append(connection)
        for connection in dead:
            if connection in bucket:
                bucket.remove(connection)
        if not bucket:
            registry.pop(key, None)


manager = ConnectionManager()
