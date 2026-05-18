"""Process-local registry of live WebSocket connections.

Tracks anonymous per-auction sockets (``auction_connections``) and
authenticated per-user sockets (``user_connections``). The shared
``_fan_out`` loop is the only path that writes to the wire and
prunes dead sockets in-place — without that pruning the buckets
grow forever as tabs close without a clean shutdown handshake.
"""

import logging

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[int, list[WebSocket]] = {}  # auction_id -> websockets
        self.user_connections: dict[int, list[WebSocket]] = {}    # user_id -> websockets

    async def connect(self, websocket: WebSocket, auction_id: int):
        await websocket.accept()
        self.active_connections.setdefault(auction_id, []).append(websocket)

    async def connect_user(self, websocket: WebSocket, user_id: int):
        await websocket.accept()
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
        bucket grows forever as clients silently drop off — every
        future broadcast then iterates dead sockets and re-raises."""
        bucket = registry.get(key)
        if not bucket:
            return
        dead: list[WebSocket] = []
        for connection in bucket:
            try:
                await connection.send_json(message)
            except Exception as exc:
                logger.debug("Dropping dead websocket on %s: %s", key, exc)
                dead.append(connection)
        for connection in dead:
            if connection in bucket:
                bucket.remove(connection)
        if not bucket:
            registry.pop(key, None)


manager = ConnectionManager()
