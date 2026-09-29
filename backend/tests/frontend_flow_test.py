"""Simulates the exact browser calls the React frontend makes (through a base URL).

Verifies the guest QR flow and admin reads with the precise payloads that
`frontend/src/pages/GuestMenu.tsx` and the admin pages send, including the
"modifiers carry only modifier_id" shape used for price-tamper protection.

Run against a live server:  python frontend_flow_test.py [base_url]
"""
from __future__ import annotations

import sys
from uuid import uuid4

import httpx

sys.stdout.reconfigure(encoding="utf-8")

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/")
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


def gget(client: httpx.Client, path: str, **params):
    res = client.get(path, params=params or None)
    if res.status_code != 200:
        raise AssertionError(f"GET {path} -> {res.status_code} {res.text[:300]}")
    return res.json()


def gpost(client: httpx.Client, path: str, payload=None, **params):
    res = client.post(path, json=payload, params=params or None)
    return res


admin = httpx.Client(base_url=API, timeout=30.0, headers={"Content-Type": "application/json"})
token = admin.post("/auth/login", json={"username": "admin", "password": "admin123"}).json()["access_token"]
admin.headers["Authorization"] = f"Bearer {token}"

suffix = uuid4().hex[:8]
dishes = gget(admin, "/admin/menu/dishes", include_inactive="false")
dishes = [d for d in dishes if d["is_available"]]
check("admin sees dishes", len(dishes) > 0, "seed menu is empty")
if not dishes:
    print(f"  PASS: {passed}    FAIL: {len(failed)}")
    sys.exit(1)

dish = dishes[0]
group = dish["modifier_groups"][0] if dish["modifier_groups"] else None
mod = group["modifiers"][0] if group and group["modifiers"] else None

hall = gget(admin, "/admin/hall/halls")[0]
tables = gget(admin, "/admin/hall/tables", hall_id=hall["id"])
# pick a genuinely free table: a previous suite (or an earlier run) may have
# left the first one occupied, and the guest flow below needs an unseated table
free = [t for t in tables if t.get("status") == "free" and not t.get("current_session")]
table = free[0] if free else tables[0]
if not free:
    admin.post(f"/admin/occupancy/tables/{table['id']}/close", json={"clear_tables": True})
qr = table["qr_token"]

# ---- guest reads exactly as GuestMenu.tsx does ----------------------------
guest = httpx.Client(base_url=API, timeout=30.0, headers={"Content-Type": "application/json"})

menu = gget(guest, f"/public/menu/{qr}")
check("guest menu loads", menu["table_name"] == table["name"], f"{menu['table_name']} vs {table['name']}")
check("guest menu has settings", "settings" in menu and menu["settings"]["title"] != "", "no settings")
check("guest menu categories", len(menu["categories"]) > 0, "no categories")

info = gget(guest, f"/public/table/{qr}")
check("guest table info", info["id"] == table["id"] and info["orders"] == [], f"got {info}")
check("guest not seated yet", info["is_seated"] is False, f"is_seated={info['is_seated']}")

# ordering before being seated must fail with the 409 the UI expects
early = gpost(guest, f"/public/table/{qr}/order", {
    "items": [{"dish_id": dish["id"], "quantity": 1, "comment": "", "modifiers": []}],
    "guest_comment": "",
    "guests_count": 1,
})
check("ordering unseated returns 409", early.status_code == 409,
      f"got {early.status_code} {early.text[:160]}")

# ---- waiter seats the table (AdminLayout / HallPage) ----------------------
seated = gpost(admin, f"/admin/occupancy/tables/{table['id']}/seat",
               {"guests_count": 2, "guest_name": "Frontend Probe", "comment": "flow test",
                "wait_minutes": 0})
check("seat table", seated.status_code == 200, f"{seated.status_code} {seated.text[:200]}")
check("table is seated", seated.json()["status"] == "seated", f"status={seated.json()['status']}")

info = gget(guest, f"/public/table/{qr}")
check("guest now sees seated", info["is_seated"] is True and info["guests_count"] == 2, f"got {info}")

# ---- the exact cart payload from GuestMenu.addDraftToCart -----------------
item: dict = {"dish_id": dish["id"], "quantity": 2, "comment": "без лука", "modifiers": []}
if mod:
    # only the id is sent: name/price are recomputed server side
    item["modifiers"] = [{"modifier_id": mod["id"]}]

order = gpost(guest, f"/public/table/{qr}/order", {
    "items": [item],
    "guest_comment": "из фронтенда",
    "guests_count": 2,
})
check("guest order accepted", order.status_code == 201, f"{order.status_code} {order.text[:300]}")
if order.status_code == 201:
    data = order.json()
    # menu prices/modifier deltas are kopecks, order totals are major units
    expected = 2 * (dish["price"] + (mod["price_delta"] if mod else 0)) / 100
    check("total uses server-side modifier price", abs(data["total_amount"] - expected) < 0.01,
          f"total={data['total_amount']} expected={expected}")
    check("order total equals sum of lines",
          abs(data["total_amount"] - sum(i["line_total"] for i in data["items"])) < 0.01,
          f"total={data['total_amount']} lines={[i['line_total'] for i in data['items']]}")
    check("order belongs to the session", data["table_session_id"] is not None, "no session")
    check("order source is qr", data["source"] == "qr", f"source={data['source']}")
    line = data["items"][0]
    check("modifier name filled by server",
          (line["modifiers"][0]["name"] == mod["name"]) if mod else True,
          f"got {line['modifiers']}")
    check("order number generated", bool(data["order_number"]), f"got {data['order_number']!r}")

# ---- guest sees its own orders -------------------------------------------
orders = gget(guest, f"/public/table/{qr}/orders")
check("guest sees placed order", len(orders) >= 1, f"got {len(orders)}")

# ---- kitchen sees it too (OrdersPage kitchen tab) ------------------------
kitchen = gget(admin, "/admin/orders/kitchen")
check("kitchen board shows the order",
      any(o["order_number"] == orders[0]["order_number"] for o in kitchen["orders"]),
      f"kitchen has {[o['order_number'] for o in kitchen['orders']]}")

# ---- status flow exactly as OrdersPage.setStatus -------------------------
oid = orders[0]["id"]
for status in ("in_progress", "ready", "served", "closed"):
    res = gpost(admin, f"/admin/orders/{oid}/status", {"status": status, "note": ""})
    if res.status_code != 200:
        check(f"status -> {status}", False, f"{res.status_code} {res.text[:200]}")
        break
else:
    check("status new -> closed walks the flow", True)
    closed = gget(admin, f"/admin/orders/{oid}")
    check("order is closed", closed["status"] == "closed", f"status={closed['status']}")
    check("closed_at is set", closed["closed_at"] is not None, "no closed_at")

# ---- waiter permissions: works the floor, never sees money ---------------
waiter_token = admin.post("/auth/login", json={"username": "waiter", "pin": "1111"}).json()["access_token"]
waiter = httpx.Client(base_url=API, timeout=30.0, headers={
    "Content-Type": "application/json", "Authorization": f"Bearer {waiter_token}"})

# reads the floor screens their job depends on
for path, label in (
    ("/admin/occupancy/board", "board"),
    ("/admin/occupancy/summary", "summary"),
    ("/admin/hall/tables", "tables"),
    ("/admin/hall/halls", "halls"),
    ("/admin/occupancy/reservations", "reservations"),
    ("/admin/orders?only_open=false&limit=5", "order list"),
    ("/admin/orders/kitchen", "kitchen"),
    ("/admin/menu/dishes?include_inactive=false", "menu"),
):
    res = waiter.get(path)
    check(f"waiter can read {label}", res.status_code == 200, f"got {res.status_code} {res.text[:120]}")

# but never money, staff or the menu editor
for path, label in (
    ("/admin/occupancy/report/daily", "reports"),
    ("/admin/occupancy/report/staff", "staff load report"),
    ("/admin/users", "staff list"),
    ("/admin/integration/1c/settings", "1C settings"),
):
    res = waiter.get(path)
    check(f"waiter is denied {label}", res.status_code == 403, f"got {res.status_code}")

# and cannot rearrange the hall or edit the menu
res = waiter.post("/admin/hall/tables", json={"hall_id": hall["id"], "name": "hack", "seats": 2})
check("waiter cannot create tables", res.status_code == 403, f"got {res.status_code}")
res = waiter.post("/admin/menu/dishes", json={"category_id": gget(admin, "/admin/menu/categories")[0]["id"],
                                              "name": "hack", "price": 100})
check("waiter cannot create dishes", res.status_code == 403, f"got {res.status_code}")

# ---- free the table, then let a waiter run the floor cycle ---------------
gpost(admin, f"/admin/occupancy/tables/{table['id']}/close", {"comment": "", "clear_tables": True})
seated2 = gpost(waiter, f"/admin/occupancy/tables/{table['id']}/seat",
                {"guests_count": 2, "guest_name": "Waiter", "comment": "", "wait_minutes": 0})
check("waiter can seat guests", seated2.status_code == 200, f"{seated2.status_code} {seated2.text[:160]}")
check("waiter seating shows the table busy", seated2.json()["status"] == "seated",
      f"status={seated2.json()['status']}")
closed2 = gpost(waiter, f"/admin/occupancy/tables/{table['id']}/close", {"comment": "", "clear_tables": True})
check("waiter can close a table", closed2.status_code == 200, f"{closed2.status_code}")
check("waiter close frees the table", closed2.json()["status"] == "free",
      f"status={closed2.json()['status']}")

# ---- closing the table frees it (HallPage.closeTable) --------------------
closed_table = gpost(admin, f"/admin/occupancy/tables/{table['id']}/close",
                     {"comment": "", "clear_tables": True})
check("close table is idempotent", closed_table.status_code == 200, f"{closed_table.status_code}")
check("table is free again", closed_table.json()["status"] == "free",
      f"status={closed_table.json()['status']}")

# guest view after close
info = gget(guest, f"/public/table/{qr}")
check("guest sees the table closed", info["is_seated"] is False, f"got {info}")

# ---- an unknown QR token must not leak the menu --------------------------
missing = guest.get("/public/menu/does-not-exist")
check("unknown QR token is 404", missing.status_code == 404, f"got {missing.status_code}")
print()
print("=" * 62)
print(f"  PASS: {passed}    FAIL: {len(failed)}")
if failed:
    print("  failed:")
    for name in failed:
        print(f"    - {name}")
print("=" * 62)
sys.exit(1 if failed else 0)
