import asyncio
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect

from app.database import SessionLocal
from app.models import Auction
from app.services.websocket_manager import manager
from app.utils.security import decode_token

router = APIRouter()


@router.websocket("/ws/auction/{auction_id}")
async def websocket_endpoint(websocket: WebSocket, auction_id: int):
    await manager.connect(websocket, auction_id)
    try:
        while True:
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=30.0)

                db = SessionLocal()
                try:
                    auction = db.query(Auction).filter(Auction.id == auction_id).first()
                    if auction:
                        time_remaining = int((auction.end_time - datetime.utcnow()).total_seconds())
                        await websocket.send_json({
                            "type": "time_update",
                            "time_remaining": max(0, time_remaining),
                            "current_price": auction.current_price,
                        })
                finally:
                    db.close()

            except asyncio.TimeoutError:
                try:
                    await websocket.send_json({"type": "ping"})
                except Exception:
                    break

    except WebSocketDisconnect:
        manager.disconnect(websocket, auction_id)
    except Exception as e:
        print(f"WebSocket error: {e}")
        manager.disconnect(websocket, auction_id)


@router.websocket("/ws/notifications/{user_id}")
async def notifications_websocket(
    websocket: WebSocket, user_id: int, token: Optional[str] = Query(None)
):
    if not token:
        print(f"WS notifications denied: missing token for path user_id {user_id}")
        await websocket.close(code=1008)
        return

    try:
        payload = decode_token(token)
        token_user_id = payload.get("user_id")
        if token_user_id != user_id:
            print(f"WS notifications denied: token user_id {token_user_id} != path user_id {user_id}")
            await websocket.close(code=1008)
            return
    except HTTPException:
        print(f"WS notifications denied: invalid or expired token for path user_id {user_id}")
        await websocket.close(code=1008)
        return

    await manager.connect_user(websocket, user_id)
    try:
        while True:
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
            except asyncio.TimeoutError:
                try:
                    await websocket.send_json({"type": "ping"})
                except Exception:
                    break

    except WebSocketDisconnect:
        manager.disconnect_user(websocket, user_id)
    except Exception as e:
        print(f"Notifications WebSocket error: {e}")
        manager.disconnect_user(websocket, user_id)
