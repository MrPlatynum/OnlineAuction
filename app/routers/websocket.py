import asyncio
import logging
from collections import defaultdict
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Auction
from app.services.websocket_manager import manager
from app.utils.security import decode_token
from app.utils.time import utcnow

logger = logging.getLogger(__name__)

router = APIRouter()

# Cap per source IP to keep one client from holding the WebSocket
# slots for everyone — /ws/auction is unauthenticated, so without
# this cap any peer can open thousands of connections and stall the
# event loop on broadcast fan-out.
MAX_AUCTION_WS_PER_IP = 20
_auction_ws_per_ip: dict[str, int] = defaultdict(int)


def _client_ip(websocket: WebSocket) -> str:
    return websocket.client.host if websocket.client else "unknown"


@router.websocket("/ws/auction/{auction_id}")
async def websocket_endpoint(websocket: WebSocket, auction_id: int):
    ip = _client_ip(websocket)
    if _auction_ws_per_ip[ip] >= MAX_AUCTION_WS_PER_IP:
        logger.warning(
            "WS auction denied: IP %s already holds %d connections",
            ip, _auction_ws_per_ip[ip],
        )
        await websocket.close(code=1008)
        return

    _auction_ws_per_ip[ip] += 1
    await manager.connect(websocket, auction_id)
    try:
        while True:
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=30.0)

                async with SessionLocal() as db:
                    auction = (
                        await db.execute(select(Auction).where(Auction.id == auction_id))
                    ).scalar_one_or_none()
                    if auction:
                        time_remaining = int((auction.end_time - utcnow()).total_seconds())
                        await websocket.send_json({
                            "type": "time_update",
                            "time_remaining": max(0, time_remaining),
                            "current_price": float(auction.current_price),
                        })

            except TimeoutError:
                try:
                    await websocket.send_json({"type": "ping"})
                except Exception:
                    break

    except WebSocketDisconnect:
        manager.disconnect(websocket, auction_id)
    except Exception:
        logger.exception("WebSocket error on auction %s", auction_id)
        manager.disconnect(websocket, auction_id)
    finally:
        # Always release the per-IP slot, even on unexpected errors
        # before the disconnect path runs.
        if _auction_ws_per_ip[ip] > 0:
            _auction_ws_per_ip[ip] -= 1
        if _auction_ws_per_ip[ip] == 0:
            _auction_ws_per_ip.pop(ip, None)


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
            except TimeoutError:
                try:
                    await websocket.send_json({"type": "ping"})
                except Exception:
                    break

    except WebSocketDisconnect:
        manager.disconnect_user(websocket, user_id)
    except Exception:
        logger.exception("Notifications WebSocket error for user_id %s", user_id)
        manager.disconnect_user(websocket, user_id)
