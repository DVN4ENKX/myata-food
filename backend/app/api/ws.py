from __future__ import annotations

import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.security import decode_access_token
from app.db.session import SessionLocal
from app.models.user import User
from app.services import hall as hall_service
from app.services.ws import CH_KITCHEN, CH_OCCUPANCY, manager, ws_timestamp

router = APIRouter(tags=["ws"])

WS_POLICY_VIOLATION = 1008


def _authenticate(websocket: WebSocket) -> User | None:
    """Browsers cannot set headers on a WebSocket, so the JWT may arrive as
    a query parameter. Both staff channels carry internal data, so anonymous
    sockets are rejected before the handshake completes."""
    token = websocket.query_params.get("token") or ""
    if not token:
        header = websocket.headers.get("authorization", "")
        if header.lower().startswith("bearer "):
            token = header[7:].strip()

    payload = decode_access_token(token) if token else None
    if not payload or payload.get("type") != "access":
        return None
    try:
        user_id = uuid.UUID(str(payload.get("sub")))
    except (TypeError, ValueError):
        return None

    db = SessionLocal()
    try:
        user = db.get(User, user_id)
    finally:
        db.close()
    if user is None or not user.is_active:
        return None
    return user


@router.websocket("/ws/{channel}")
async def websocket_endpoint(websocket: WebSocket, channel: str) -> None:
    if channel not in (CH_OCCUPANCY, CH_KITCHEN):
        await websocket.close(code=WS_POLICY_VIOLATION)
        return

    user = _authenticate(websocket)
    if user is None:
        await websocket.close(code=WS_POLICY_VIOLATION)
        return

    await manager.connect(websocket, channel, role=user.role)
    try:
        await websocket.send_json(
            {
                "event": "connected",
                "data": {"channel": channel, "user": user.username, "at": ws_timestamp()},
            }
        )
        # prime the client with the current state
        if channel == CH_OCCUPANCY:
            await _send_snapshot(websocket)

        while True:
            message = await websocket.receive_text()
            if message == "ping":
                await websocket.send_json({"event": "pong", "data": {"at": ws_timestamp()}})
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001 - never let a socket crash the server
        pass
    finally:
        manager.disconnect(websocket)


async def _send_snapshot(websocket: WebSocket) -> None:
    db = SessionLocal()
    try:
        tables = hall_service.list_tables(db, None, active_only=True)
        rows = hall_service.table_payloads(db, tables)
        await websocket.send_json(
            {
                "event": "occupancy.snapshot",
                "data": {
                    "summary": hall_service.summary(db),
                    "tables": [
                        {
                            "id": str(r["table"].id),
                            "name": r["table"].name,
                            "status": r["status"],
                            "hall": r["hall_name"],
                            "open_orders": r["open_orders"],
                            "order_total": r["order_total"],
                        }
                        for r in rows
                    ],
                },
            }
        )
    finally:
        db.close()


@router.get("/ws/health")
def ws_health() -> dict:
    return {"ok": True, "clients": manager.count, "at": ws_timestamp()}
