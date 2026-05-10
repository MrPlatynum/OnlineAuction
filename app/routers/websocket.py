import asyncio
import logging
import time
from collections import defaultdict, deque
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

# Cap incoming messages per /ws/auction connection: every receive_text
# triggers a SELECT auctions, so an attacker can DoS Postgres through
# the socket even within the per-IP connection cap. Sliding window
# count over the last 60s; messages above the cap are silently dropped
# without hitting the DB.
WS_AUCTION_MSG_WINDOW_SECS = 60
WS_AUCTION_MSG_MAX_PER_WINDOW = 30


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
    msg_timestamps: deque[float] = deque()
    await manager.connect(websocket, auction_id)
    try:
        while True:
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=30.0)

                now = time.monotonic()
                while msg_timestamps and now - msg_timestamps[0] > WS_AUCTION_MSG_WINDOW_SECS:
                    msg_timestamps.popleft()
                if len(msg_timestamps) >= WS_AUCTION_MSG_MAX_PER_WINDOW:
                    continue
                msg_timestamps.append(now)

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
    # Token preferred via Sec-WebSocket-Protocol subprotocol — clients send
    #   new WebSocket(url, ['bearer', '<jwt>'])
    # — so the JWT never lands in URLs (proxy/access logs / browser history).
    # Query-string fallback retained for backward compat; will be removed
    # once all clients are on the subprotocol scheme.
    accepted_protocol: Optional[str] = None
    sub = websocket.headers.get("sec-websocket-protocol", "")
    parts = [p.strip() for p in sub.split(",") if p.strip()]
    if len(parts) == 2 and parts[0] == "bearer":
        token = parts[1]
        accepted_protocol = "bearer"

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

    # ``connect_user`` calls accept() — propagate the subprotocol echo so the
    # browser handshake completes (per RFC 6455 §1.9 server must echo one
    # of the offered subprotocols).
    if accepted_protocol:
        await websocket.accept(subprotocol=accepted_protocol)
        manager.user_connections.setdefault(user_id, []).append(websocket)
    else:
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
