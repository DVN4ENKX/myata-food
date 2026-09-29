"""WebSocket checks: auth, snapshot, live occupancy and kitchen events.

    python tests/ws_test.py [base_url]
"""
from __future__ import annotations

import asyncio
import json
import sys

import httpx
import websockets

sys.stdout.reconfigure(encoding="utf-8")

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/")
HTTP = BASE.replace("http://", "ws://").replace("https://", "wss://")
API = f"{BASE}/api"

passed = 0
failed: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    global passed
    if ok:
        passed += 1
        print(f"PASS  {name}")
    else:
        failed.append(name)
        print(f"FAIL  {name} :: {detail}")


async def expect_event(ws, event: str, timeout: float = 6.0) -> dict:
    """Read until the wanted event arrives, collecting everything seen."""
    seen: list[dict] = []
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=max(0.1, deadline - loop.time()))
        except TimeoutError:
            break
        message = json.loads(raw)
        seen.append(message)
        if message.get("event") == event:
            return message
    raise AssertionError(f"{event} not received, saw {[m.get('event') for m in seen]}")


async def main() -> int:
    async with httpx.AsyncClient(base_url=API, timeout=20.0) as client:
        login = (await client.post("/auth/login", json={"username": "admin", "password": "admin123"})).json()
    token = login["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # anonymous sockets must be refused
    for channel in ("occupancy", "kitchen"):
        try:
            async with websockets.connect(f"{HTTP}/api/ws/{channel}") as ws:
                await ws.recv()
            check(f"ws {channel} rejects anonymous", False, "connection stayed open")
        except Exception:
            check(f"ws {channel} rejects anonymous", True)

    try:
        async with websockets.connect(f"{HTTP}/api/ws/unknown") as ws:
            await ws.recv()
        check("ws unknown channel refused", False, "connection stayed open")
    except Exception:
        check("ws unknown channel refused", True)

    # invalid token
    try:
        async with websockets.connect(f"{HTTP}/api/ws/occupancy?token=garbage") as ws:
            await ws.recv()
        check("ws rejects bad token", False, "connection stayed open")
    except Exception:
        check("ws rejects bad token", True)

    async with httpx.AsyncClient(base_url=API, timeout=20.0, headers=headers) as client:
        tables = (await client.get("/admin/hall/tables")).json()
        target = next(t for t in tables if t["status"] == "free")

    # occupancy: snapshot + live change
    async with websockets.connect(f"{HTTP}/api/ws/occupancy?token={token}") as ws:
        hello = json.loads(await ws.recv())
        check("ws occupancy hello", hello.get("event") == "connected", str(hello))
        snapshot = await expect_event(ws, "occupancy.snapshot")
        check(
            "ws occupancy snapshot",
            snapshot["data"]["summary"]["tables_total"] >= 20
            and len(snapshot["data"]["tables"]) >= 20,
            str(snapshot["data"]["summary"]),
        )

        await ws.send("ping")
        check("ws ping/pong", (await expect_event(ws, "pong")) is not None)

        async with httpx.AsyncClient(base_url=API, timeout=20.0, headers=headers) as client:
            await client.post(f"/admin/occupancy/tables/{target['id']}/seat", json={"guests_count": 2})
        change = await expect_event(ws, "occupancy.updated")
        check(
            "ws occupancy live event",
            change["data"]["table_id"] == target["id"] and change["data"]["status"] == "seated",
            str(change["data"]),
        )

        async with httpx.AsyncClient(base_url=API, timeout=20.0, headers=headers) as client:
            await client.post(
                f"/admin/occupancy/tables/{target['id']}/close", json={"clear_tables": True}
            )
        close_event = await expect_event(ws, "occupancy.updated")
        check("ws occupancy close event", close_event["data"]["status"] == "free", str(close_event["data"]))

    # kitchen: a guest order must appear live
    async with httpx.AsyncClient(base_url=API, timeout=20.0) as client:
        async with httpx.AsyncClient(base_url=API, timeout=20.0, headers=headers) as admin:
            await admin.post(
                f"/admin/occupancy/tables/{target['id']}/seat", json={"guests_count": 2}
            )
        menu = (await client.get(f"/public/menu/{target['qr_token']}")).json()
        dish = next(d for c in menu["categories"] for d in c["dishes"])

        async with websockets.connect(f"{HTTP}/api/ws/kitchen?token={token}") as ws:
            hello = json.loads(await ws.recv())
            check("ws kitchen hello", hello.get("event") == "connected", str(hello))

            order = await client.post(
                f"/public/table/{target['qr_token']}/order",
                json={"items": [{"dish_id": dish["id"], "quantity": 1, "modifiers": []}]},
            )
            order.raise_for_status()
            event = await expect_event(ws, "order.updated")
            check(
                "ws kitchen order event",
                event["data"]["order"]["order_number"] == order.json()["order_number"],
                str(event["data"]["order"]["order_number"]),
            )

        async with httpx.AsyncClient(base_url=API, timeout=20.0, headers=headers) as admin:
            await admin.post(
                f"/admin/occupancy/tables/{target['id']}/close", json={"clear_tables": True}
            )

    print()
    print("=" * 62)
    print(f"  PASS: {passed}    FAIL: {len(failed)}")
    if failed:
        print("  failed: " + ", ".join(failed))
    print("=" * 62)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
