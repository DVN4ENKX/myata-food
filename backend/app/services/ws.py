from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Fan-out of occupancy / kitchen events to every connected screen."""

    def __init__(self) -> None:
        self._clients: dict[UUID, set[WebSocket]] = defaultdict(set)
        self._roles: dict[WebSocket, str] = {}

    async def connect(self, ws: WebSocket, channel: str, role: str = "staff") -> None:
        await ws.accept()
        self._clients[channel].add(ws)
        self._roles[ws] = role

    def disconnect(self, ws: WebSocket) -> None:
        for channel in self._clients:
            self._clients[channel].discard(ws)
        self._roles.pop(ws, None)

    async def broadcast(self, channel: str, event: str, data: Any) -> None:
        message = {"event": event, "data": data}
        dead: list[WebSocket] = []
        for ws in list(self._clients.get(channel, ())):
            try:
                await ws.send_json(message)
            except Exception:  # noqa: BLE001 - client vanished mid-send
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    @property
    def count(self) -> int:
        return sum(len(v) for v in self._clients.values())


manager = ConnectionManager()

CH_OCCUPANCY = "occupancy"
CH_KITCHEN = "kitchen"

_main_loop: asyncio.AbstractEventLoop | None = None


def set_main_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _main_loop
    _main_loop = loop


def publish(channel: str, event: str, data: Any) -> None:
    """Broadcast from anywhere: async endpoint, sync endpoint or startup task.

    Sync endpoints run in a worker thread with no event loop of their own, so
    the coroutine is handed to the loop captured during startup. A failure to
    reach any client must never break the HTTP request that triggered it.
    """
    coro = manager.broadcast(channel, event, data)
    loop = _main_loop
    if loop is not None and loop.is_running():
        try:
            asyncio.run_coroutine_threadsafe(coro, loop)
        except Exception as exc:  # noqa: BLE001
            logger.warning("ws publish failed: %s", exc)
        return
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        try:
            asyncio.run(coro)
        except Exception as exc:  # noqa: BLE001
            logger.warning("ws publish failed: %s", exc)
    else:
        running.create_task(coro)


def publish_menu_changed() -> None:
    """Every open QR menu should refresh (prices, 86-items, new dishes)."""
    publish(CH_KITCHEN, "menu.updated", {"at": "now"})


def publish_occupancy(payload: dict) -> None:
    publish(CH_OCCUPANCY, "occupancy.updated", payload)


def publish_order(payload: dict) -> None:
    publish(CH_KITCHEN, "order.updated", payload)


# aliases used by the API layer
publish_kitchen_order = publish_order
publish_occupancy_change = publish_occupancy


def ws_timestamp() -> str:
    return datetime.now().isoformat()

