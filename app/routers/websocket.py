import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect

from app.database import SessionLocal
from app.models import Auction
from app.services.websocket_manager import manager
from app.utils.security import decode_token
from app.utils.time import utcnow

logger = logging.getLogger(__name__)

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
                        time_remaining = int((auction.end_time - utcnow()).total_seconds())
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
    except Exception:
        logger.exception("WebSocket error on auction %s", auction_id)
        manager.disconnect(websocket, auction_id)


@router.websocket("/ws/notifications/{user_id}")
async def notifications_websocket(
    websocket: WebSocket, user_id: int, token: Optional[str] = Query(None)
):
    if not token:
        logger.warning("WS notifications denied: missing token for user_id %s", user_id)
        await websocket.close(code=1008)
        return

    try:
        payload = decode_token(token)
        token_user_id = payload.get("user_id")
        if token_user_id != user_id:
            logger.warning(
                "WS notifications denied: token user_id %s != path user_id %s",
                token_user_id, user_id,
            )
            await websocket.close(code=1008)
            return
    except HTTPException:
        logger.warning("WS notifications denied: invalid or expired token for user_id %s", user_id)
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
    except Exception:
        logger.exception("Notifications WebSocket error for user_id %s", user_id)
        manager.disconnect_user(websocket, user_id)
