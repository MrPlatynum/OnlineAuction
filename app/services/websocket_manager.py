from typing import Dict, List

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[int, List[WebSocket]] = {}  # auction_id -> websockets
        self.user_connections: Dict[int, List[WebSocket]] = {}    # user_id -> websockets

    async def connect(self, websocket: WebSocket, auction_id: int):
        await websocket.accept()
        if auction_id not in self.active_connections:
            self.active_connections[auction_id] = []
        self.active_connections[auction_id].append(websocket)

    async def connect_user(self, websocket: WebSocket, user_id: int):
        await websocket.accept()
        if user_id not in self.user_connections:
            self.user_connections[user_id] = []
        self.user_connections[user_id].append(websocket)

    def disconnect(self, websocket: WebSocket, auction_id: int):
        if auction_id in self.active_connections:
            if websocket in self.active_connections[auction_id]:
                self.active_connections[auction_id].remove(websocket)

    def disconnect_user(self, websocket: WebSocket, user_id: int):
        if user_id in self.user_connections:
            if websocket in self.user_connections[user_id]:
                self.user_connections[user_id].remove(websocket)

    async def broadcast(self, message: dict, auction_id: int):
        if auction_id in self.active_connections:
            for connection in self.active_connections[auction_id]:
                try:
                    await connection.send_json(message)
                except Exception:
                    pass

    async def send_notification(self, user_id: int, message: dict):
        if user_id in self.user_connections:
            for connection in self.user_connections[user_id]:
                try:
                    await connection.send_json(message)
                except Exception:
                    pass


manager = ConnectionManager()
