"""End-to-end smoke test for the Myata Food API.

Run against a live server:  python smoke_test.py [base_url]
"""
from __future__ import annotations

import re
import sys
from uuid import uuid4

import httpx

sys.stdout.reconfigure(encoding="utf-8")

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/")
API = f"{BASE}/api"

passed = 0
failed: list[str] = []


def print_report() -> None:
    print()
    print("=" * 62)
    print(f"  PASS: {passed}    FAIL: {len(failed)}")
    if failed:
        print("  failed: " + ", ".join(failed))
    print("=" * 62)


def step(name, critical: bool = False):
    """critical=True aborts the run: later steps need this value."""

    def deco(fn):
        global passed
        try:
            result = fn()
        except Exception as exc:  # noqa: BLE001
            failed.append(name)
            print(f"FAIL  {name} :: {type(exc).__name__}: {exc}")
            if critical:
                print_report()
                raise SystemExit(2) from None
            return None
        passed += 1
        print(f"PASS  {name}")
        return result

    return deco


def expect(cond, msg):
    if not cond:
        raise AssertionError(msg)


client = httpx.Client(timeout=30.0)

# ---------------------------------------------------------------- auth
login = step("login admin", critical=True)(
    lambda: client.post(
        f"{API}/auth/login", json={"username": "admin", "password": "admin123"}
    ).raise_for_status().json()
)
TOKEN = login["access_token"]
H = {"Authorization": f"Bearer {TOKEN}"}


def get(path, **kw):
    r = client.get(f"{API}{path}", headers=H, **kw)
    r.raise_for_status()
    return r.json()


def post(path, body=None, **kw):
    r = client.post(f"{API}{path}", headers=H, json=body, **kw)
    r.raise_for_status()
    return r.json()


def patch(path, body=None):
    r = client.patch(f"{API}{path}", headers=H, json=body)
    r.raise_for_status()
    return r.json()


def delete(path):
    r = client.delete(f"{API}{path}", headers=H)
    r.raise_for_status()
    return r.json()


def anon(method, path, body=None):
    r = client.request(method, f"{API}{path}", json=body)
    expect(r.status_code in (401, 403, 404, 409), f"expected auth error, got {r.status_code}")
    return r


step("auth me")(lambda: expect(get("/auth/me")["username"] == "admin", "wrong user"))
step("auth roles")(lambda: expect(len(get("/auth/roles")) == 4, "roles"))
step("auth 401 without token")(
    lambda: expect(
        client.get(f"{API}/admin/menu/categories").status_code == 401, "no 401"
    )
)
step("auth bad password")(
    lambda: expect(
        client.post(
            f"{API}/auth/login", json={"username": "admin", "password": "wrong"}
        ).status_code
        == 401,
        "bad password accepted",
    )
)

# ---------------------------------------------------------------- menu
categories = step("list categories", critical=True)(lambda: get("/admin/menu/categories"))
print(f"      categories: {len(categories)}")
dishes = step("list dishes", critical=True)(lambda: get("/admin/menu/dishes"))
print(f"      dishes: {len(dishes)}")
step("menu stats")(lambda: expect(get("/admin/menu/stats")["dishes_total"] > 20, "stats"))
step("menu tree")(lambda: expect(len(get("/admin/menu/categories/tree")) >= 7, "tree"))
step("modifier groups")(
    lambda: expect(len(get("/admin/menu/modifier-groups")) >= 3, "groups")
)
step("search dishes")(
    lambda: expect(len(get("/admin/menu/dishes", params={"search": "борщ"})) >= 1, "search")
)
step("filter by category")(
    lambda: expect(
        len(get("/admin/menu/dishes", params={"category_id": categories[0]["id"]})) >= 3,
        "filter",
    )
)

new_dish = step("create dish", critical=True)(
    lambda: post(
        "/admin/menu/dishes",
        {
            "category_id": categories[0]["id"],
            "name": "Тестовое блюдо",
            "description": "проверка CRUD",
            "price": 19900,
            "cooking_minutes": 7,
            "allergens": ["молоко"],
            "tags": ["тест"],
            "modifier_group_ids": [],
        },
    )
)
step("update dish")(lambda: expect(patch(f"/admin/menu/dishes/{new_dish['id']}", {"price": 21900})["price"] == 21900, "price"))
step("toggle availability")(
    lambda: post(f"/admin/menu/dishes/{new_dish['id']}/availability", {"is_available": False})
)
step("bulk availability")(
    lambda: expect(
        post(
            "/admin/menu/dishes/bulk-availability",
            {"dish_ids": [new_dish["id"]], "is_available": True},
        )["updated"]
        == 1,
        "bulk",
    )
)
step("delete dish")(lambda: delete(f"/admin/menu/dishes/{new_dish['id']}"))

new_cat = step("create category", critical=True)(
    lambda: post("/admin/menu/categories", {"name": "Тестовая группа", "description": "x"})
)
step("rename category")(lambda: expect(patch(f"/admin/menu/categories/{new_cat['id']}", {"name": "Группа 2"})["name"] == "Группа 2", "rename"))
step("reorder categories")(
    lambda: post(
        "/admin/menu/categories/reorder",
        {"items": [{"id": new_cat["id"], "sort_order": 99}]},
    )
)
step("delete category")(lambda: delete(f"/admin/menu/categories/{new_cat['id']}"))
step("menu settings")(lambda: expect(get("/admin/menu/settings")["title"], "settings"))


def patch_settings():
    return client.put(
        f"{API}/admin/menu/settings", headers=H, json={"title": "Меню Myata"}
    ).raise_for_status().json()


step("update menu settings")(lambda: expect(patch_settings()["title"] == "Меню Myata", "settings title"))

# ---------------------------------------------------------------- hall
halls = step("list halls", critical=True)(lambda: get("/admin/hall/halls"))
print(f"      halls: {len(halls)}")
tables = step("list tables", critical=True)(lambda: get("/admin/hall/tables"))
print(f"      tables: {len(tables)}")
table = tables[0]

created = step("create table", critical=True)(
    lambda: post(
        "/admin/hall/tables",
        {
            "hall_id": halls[0]["id"],
            "name": "Т-Test",
            "seats": 4,
            "shape": "rect",
            "x": 500,
            "y": 500,
            "width": 150,
            "height": 90,
        },
    )
)
step(
    "save layout"
)(
    lambda: expect(
        post(
            "/admin/hall/tables/layout",
            {"tables": [{"id": table["id"], "x": 111, "y": 222, "width": 130, "height": 95, "rotation": 15, "shape": "round"}]},
        )[0]["x"]
        == 111,
        "layout not saved",
    )
)
step("table detail")(lambda: expect(get(f"/admin/hall/tables/{table['id']}")["x"] == 111, "detail"))

qr = step("table qr", critical=True)(lambda: get(f"/admin/hall/tables/{created['id']}/qr"))
step("qr payload")(lambda: expect(qr["svg"].startswith("<svg") and qr["url"].endswith(created["qr_token"]), "svg/url"))
step("qr png")(
    lambda: expect(
        len(client.get(f"{API}/admin/hall/tables/{created['id']}/qr.png", headers=H).content) > 200,
        "png",
    )
)
step("qr sheet")(lambda: expect(len(client.get(f"{API}/admin/hall/qr/sheet", headers=H).content) > 5000, "sheet"))
step("qr matrix")(lambda: expect(len(get(f"/admin/hall/tables/{created['id']}/qr/matrix")["matrix"]) > 10, "matrix"))
step("regenerate qr")(
    lambda: expect(
        post(f"/admin/hall/tables/{created['id']}/qr/regenerate")["qr_token"] != created["qr_token"],
        "regen",
    )
)
# the token changed, so re-read the table before using it as a guest
created = get(f"/admin/hall/tables/{created['id']}")

# ---------------------------------------------------------------- occupancy
board = step("occupancy board", critical=True)(lambda: get("/admin/occupancy/board"))
step("board summary")(lambda: expect(board["summary"]["tables_total"] == len(tables) + 1, "summary"))
print(
    f"      busy={board['summary']['tables_busy']} free={board['summary']['tables_free']} "
    f"occ={board['summary']['occupancy_percent']}% seats={board['summary']['seats_total']}"
)

target = next(t for t in tables if t["status"] == "free")
token = target["qr_token"]
step("seat guests")(lambda: post(f"/admin/occupancy/tables/{target['id']}/seat", {"guests_count": 3, "guest_name": "Иван", "wait_minutes": 5}))
step("board shows seated")(
    lambda: expect(
        [t for t in get("/admin/occupancy/board")["tables"] if t["id"] == target["id"]][0]["status"] == "seated",
        "not seated",
    )
)
step("double seat rejected")(lambda: anon("POST", f"/admin/occupancy/tables/{target['id']}/seat", {"guests_count": 2}))
step("update session")(lambda: post(f"/admin/occupancy/tables/{target['id']}/update-session", {"guests_count": 5}))

# ---------------------------------------------------------------- guest QR
menu = step("public menu", critical=True)(lambda: client.get(f"{API}/public/menu/{token}").raise_for_status().json())
step("menu content")(lambda: expect(len(menu["categories"]) >= 7 and menu["dishes_count"] >= 30, "menu empty"))
print(f"      guest sees {len(menu['categories'])} categories / {menu['dishes_count']} dishes, table {menu['table_name']}")
step("menu categories have dishes")(
    lambda: expect(any(c["dishes"] for c in menu["categories"]), "no dishes attached")
)
step("modifiers attached")(
    lambda: expect(any(d["modifier_groups"] for c in menu["categories"] for d in c["dishes"]), "no modifiers")
)

info = step("table info", critical=True)(lambda: client.get(f"{API}/public/table/{token}").raise_for_status().json())
step("table is seated")(lambda: expect(info["is_seated"] and info["guests_count"] == 5, "seated state"))

all_dishes = [d for c in menu["categories"] for d in c["dishes"]]
# deliberately pick a dish that actually has modifiers: the first dish differs
# between backends (no total ordering without an explicit tiebreak), and a dish
# without modifier groups would silently skip the modifier assertions
d1 = next((d for d in all_dishes if d.get("modifier_groups")), all_dishes[0])
d2 = next(d for d in all_dishes if d["id"] != d1["id"])
# a zero-delta modifier would make the per-unit vs per-line check meaningless
_mods = d1["modifier_groups"][0]["modifiers"]
mod = next((m for m in reversed(_mods) if float(m["price_delta"]) != 0), _mods[-1] if _mods else None)
menu_dish_price = d1["price"]

order = step("guest places order", critical=True)(
    lambda: client.post(
        f"{API}/public/table/{token}/order",
        json={
            "items": [
                {"dish_id": d1["id"], "quantity": 2, "comment": "без лука", "modifiers": ([{"modifier_id": mod["id"]}] if mod else [])},
                {"dish_id": d2["id"], "quantity": 1, "modifiers": []},
            ],
            "guest_comment": "побыстрее",
            "guests_count": 5,
        },
    ).raise_for_status().json()
)
step("order total")(lambda: expect(order["total_amount"] > 0, "total=0"))
step("order source is qr")(lambda: expect(order["source"] == "qr", "source"))
step("order number format")(
    lambda: expect(re.match(r"^\d{6}-\d{3}$", order["order_number"]), order["order_number"])
)
print(f"      order {order['order_number']} total={order['total_amount']} items={len(order['items'])}")


def _expected_total(o: dict) -> float:
    """Sum the API's per-line totals. line_total already includes modifiers
    (applied per unit), so adding them again would double count them."""
    return round(sum(float(i["line_total"]) for i in o["items"]), 2)


# guards the 100x bug where total_amount was summed in kopecks while every line
# was in major units - a plain "> 0" check sails straight past that
step("order total equals sum of lines")(
    lambda: expect(
        abs(float(order["total_amount"]) - _expected_total(order)) < 0.01,
        f"total={order['total_amount']} lines={_expected_total(order)}",
    )
)
step("order total is in major units")(
    lambda: expect(
        float(order["total_amount"]) < float(menu_dish_price) * 1000,
        f"total={order['total_amount']} looks like kopecks (dish price {menu_dish_price})",
    )
)
step("modifier price applied")(
    lambda: expect(any(i["modifiers"] for i in order["items"]), "no modifiers stored")
)
step("guest sees own orders")(
    lambda: expect(len(client.get(f"{API}/public/table/{token}/orders").json()) >= 1, "orders")
)
step("bad token 404")(
    lambda: expect(client.get(f"{API}/public/menu/nonexistent").status_code == 404, "404")
)
step("modifier without id rejected")(
    lambda: expect(
        client.post(
            f"{API}/public/table/{token}/order",
            json={
                "items": [
                    {
                        "dish_id": d1["id"],
                        "quantity": 1,
                        "modifiers": [{"name": "халява", "price_delta": -99999999}],
                    }
                ]
            },
        ).status_code
        == 422,
        "modifier without id accepted",
    )
)


def tampered_order():
    """A made-up modifier id must be dropped, not priced by the client."""
    r = client.post(
        f"{API}/public/table/{token}/order",
        json={
            "items": [
                {
                    "dish_id": d1["id"],
                    "quantity": 1,
                    "modifiers": [
                        {
                            "modifier_id": "11111111-2222-3333-4444-555555555555",
                            "name": "халява",
                            "price_delta": -99999999,
                        }
                    ],
                }
            ]
        },
    )
    r.raise_for_status()
    created = r.json()
    expect(not created["items"][0]["modifiers"], "invented modifier was priced")
    # menu prices are kopecks, order totals are major units
    expect(
        abs(float(created["total_amount"]) - menu_dish_price / 100) < 0.01,
        f"total={created['total_amount']} expected={menu_dish_price / 100}",
    )
    for _ in range(3):  # new -> in_progress -> ready -> served
        post(f"/admin/orders/{created['id']}/next-status")


step("price tampering ignored")(tampered_order)

free_table = next(t for t in tables if t["status"] != "seated" and t["id"] != target["id"])
step("order rejected when not seated")(
    lambda: expect(
        client.post(
            f"{API}/public/table/{free_table['qr_token']}/order",
            json={"items": [{"dish_id": d1["id"], "quantity": 1, "modifiers": []}]},
        ).status_code
        == 409,
        "should be 409",
    )
)

# ---------------------------------------------------------------- orders
orders = step("list orders", critical=True)(lambda: get("/admin/orders"))
KITCHEN_FLOW = {"new": "in_progress", "in_progress": "ready", "ready": "served"}
# the list is not ordered, and an earlier step walks an order all the way to
# "served", so orders[0] is not guaranteed to be advanceable
order = next((o for o in orders if o["status"] in KITCHEN_FLOW), orders[0])
base_items = len(order["items"])
kitchen = step("kitchen board", critical=True)(lambda: get("/admin/orders/kitchen"))
step("kitchen has work")(lambda: expect(kitchen["orders"], "empty kitchen"))
print(f"      kitchen: {len(kitchen['orders'])} orders, max wait {kitchen['max_wait_minutes']} min")

step("order next status")(
    lambda: expect(
        post(f"/admin/orders/{order['id']}/next-status")["status"] == KITCHEN_FLOW[order["status"]],
        "status",
    )
)
step("order add item")(
    lambda: post(f"/admin/orders/{order['id']}/items", {"dish_id": d1["id"], "quantity": 1, "comment": "дополнительно"})
)
full = step("order detail", critical=True)(lambda: get(f"/admin/orders/{order['id']}"))
step("item count grew")(lambda: expect(len(full["items"]) == base_items + 1, f"items={len(full['items'])}"))
step(
    "order remove item"
)(
    lambda: expect(
        len(
            client.request(
                "DELETE",
                f"{API}/admin/orders/{order['id']}/items/{full['items'][-1]['id']}",
                headers=H,
            )
            .raise_for_status()
            .json()["items"]
        )
        == base_items,
        "remove",
    )
)
step("order served")(
    lambda: expect(post(f"/admin/orders/{order['id']}/next-status")["status"] == "ready", "ready")
)
step("order closed")(
    lambda: expect(post(f"/admin/orders/{order['id']}/next-status")["status"] == "served", "served")
)
step("filter open orders")(lambda: get("/admin/orders", params={"only_open": True}))
step("filter by source")(lambda: get("/admin/orders", params={"source": "qr"}))
step("filter by table")(lambda: get("/admin/orders", params={"table_id": target["id"]}))

# ---------------------------------------------------------------- reservations
res = step("create reservation", critical=True)(
    lambda: post(
        "/admin/occupancy/reservations",
        {
            "guest_name": "Мария",
            "phone": "+7 900 000-11-22",
            "guests_count": 2,
            "reserved_at": "2026-09-28T18:00:00Z",
            "duration_minutes": 120,
            "comment": "у окна",
        },
    )
)
step("list reservations")(lambda: expect(get("/admin/occupancy/reservations"), "reservations"))
step("update reservation")(lambda: expect(patch(f"/admin/occupancy/reservations/{res['id']}", {"guests_count": 4})["guests_count"] == 4, "update"))
step("seat from reservation")(
    lambda: expect(post(f"/admin/occupancy/reservations/{res['id']}/seat")["table"], "seat from resv")
)
step("delete reservation")(lambda: delete(f"/admin/occupancy/reservations/{res['id']}"))

# ---------------------------------------------------------------- reports
report = step("daily report", critical=True)(lambda: get("/admin/occupancy/report/daily"))
step("report data")(lambda: expect(report["orders_total"] > 0 and report["top_dishes"], "report"))
print(
    f"      {report['business_date']}: orders={report['orders_total']} revenue={report['revenue_total']} "
    f"avg_check={report['avg_check']} guests={report['guests_total']}"
)
step("report hourly")(lambda: expect(report["hourly_load"], "hourly"))
step("report by source")(lambda: expect(report["by_source"], "source"))
step("staff load")(lambda: get("/admin/occupancy/report/staff"))
step("table history")(lambda: expect(get(f"/admin/occupancy/tables/{target['id']}/sessions"), "history"))
step("close day")(lambda: expect(post("/admin/occupancy/report/close-day")["ok"], "close day"))

# ---------------------------------------------------------------- users
users = step("list users", critical=True)(lambda: get("/admin/users"))
print("      users: " + ", ".join(f"{u['username']}({u['role']})" for u in users))
step("permission matrix")(lambda: expect(get("/admin/users/permissions")["flags"], "matrix"))

# unique per run so the suite is repeatable without wiping the database first
NEW_USERNAME = f"test_mgr_{uuid4().hex[:8]}"
nu = step("create user", critical=True)(
    lambda: post(
        "/admin/users",
        {
            "username": NEW_USERNAME,
            "password": "test1234",
            "pin": "4321",
            "full_name": "Тестовый Менеджер",
            "role": "manager",
            "can_manage_menu": True,
        },
    )
)
step("duplicate username rejected")(
    lambda: expect(
        client.post(f"{API}/admin/users", headers=H, json={"username": NEW_USERNAME, "password": "x1234", "role": "manager"}).status_code
        == 409,
        "duplicate",
    )
)


def pin_login():
    r = client.post(f"{API}/auth/login", json={"username": NEW_USERNAME, "pin": "4321"})
    r.raise_for_status()
    mh = {"Authorization": f"Bearer {r.json()['access_token']}"}
    expect(client.get(f"{API}/admin/menu/categories", headers=mh).status_code == 200, "menu forbidden")
    expect(client.get(f"{API}/admin/users", headers=mh).status_code == 403, "users should be forbidden")


step("pin login + manager permissions")(pin_login)
step("update user")(lambda: expect(patch(f"/admin/users/{nu['id']}", {"full_name": "Обновлён"})["full_name"] == "Обновлён", "update"))
step("set new pin")(lambda: post(f"/admin/users/{nu['id']}/reset-pin", {"pin": "9999"}))
step("cannot deactivate self")(
    lambda: expect(
        client.delete(f"{API}/admin/users/{users[0]['id']}", headers=H).status_code == 200,
        "self delete",
    )
)
step("audit log")(lambda: expect(get("/admin/users/audit"), "audit"))

# ---------------------------------------------------------------- 1C
step("1c settings")(lambda: expect(get("/admin/integration/1c/settings")["exchange_plan"], "settings"))
step(
    "1c update settings"
)(
    lambda: expect(
        client.put(
            f"{API}/admin/integration/1c/settings",
            headers=H,
            json={"exchange_plan": "ОбменMyata", "org_ref": "Осн", "price_type_ref": "Розничная", "export_orders": True},
        ).raise_for_status().json()["org_ref"] == "Осн",
        "update",
    )
)
exp = step("1c export", critical=True)(
    lambda: post("/admin/integration/1c/export", {"categories": True, "dishes": True, "modifiers": True, "orders": True, "day_closes": True})
)
step("export succeeded")(lambda: expect(exp["entities_total"] > 50 and exp["status"] == "success", f"entities={exp['entities_total']}"))
print(f"      export: {exp['file_name']} entities={exp['entities_total']}")
xml = step("download export", critical=True)(
    lambda: client.get(f"{API}/admin/integration/1c/exports/{exp['log_id']}", headers=H).raise_for_status().text
)
step("xml structure")(lambda: expect("СообщениеОбмена" in xml and "Номенклатура" in xml, "xml content"))
step("xml has dishes")(lambda: expect("Борщ" in xml, "no seeded dish in xml"))
step("xml has order")(lambda: expect("ЗаказКлиенту" in xml, "no order in xml"))
step("1c preview")(lambda: expect("Номенклатура" in post("/admin/integration/1c/export/preview")["xml"], "preview"))
step("1c status")(lambda: expect(get("/admin/integration/1c/status")["exchange_plan"], "status"))
maps = step("1c sync maps", critical=True)(lambda: get("/admin/integration/1c/maps"))
step("sync maps created")(lambda: expect(len(maps) > 30, f"maps={len(maps)}"))
print(f"      sync maps: {len(maps)}")

# unique 1C refs per run, otherwise a second run finds them already imported
# and "created" drops to 0, which is correct behaviour but a useless assertion
ext1, ext2 = f"1C-TEST-1-{uuid4().hex[:8]}", f"1C-TEST-2-{uuid4().hex[:8]}"
push = step("1c inbound push", critical=True)(
    lambda: post(
        "/admin/integration/1c/push",
        {
            "items": [
                {"entity": "Справочник.Номенклатура", "external_id": ext1, "name": "Борщ из 1С", "price": 415.00, "is_available": True},
                {"entity": "Справочник.Номенклатура", "external_id": ext2, "name": "Компот", "price": 130.00},
            ]
        },
    )
)
step("push created 2")(lambda: expect(push["created"] == 2, f"created={push['created']}"))
step(
    "push is idempotent"
)(
    lambda: expect(
        post("/admin/integration/1c/push", {"items": [{"entity": "Справочник.Номенклатура", "external_id": ext1, "name": "Борщ обновлён", "price": 455.00}]})["updated"]
        == 1,
        "update",
    )
)
step("pushed dish in menu")(
    lambda: expect(
        any(d["name"] == "Борщ обновлён" for d in get("/admin/menu/dishes", params={"search": "Борщ обновлён"})),
        "not imported",
    )
)
step("1c logs")(lambda: expect(get("/admin/integration/1c/logs"), "logs"))

# ---------------------------------------------------------------- cleanup + finish
step("close table")(lambda: post(f"/admin/occupancy/tables/{target['id']}/close", {"clear_tables": True}))
step("board free again")(
    lambda: expect(
        [t for t in get("/admin/occupancy/board")["tables"] if t["id"] == target["id"]][0]["status"] == "free",
        "still busy",
    )
)
step("deactivate test user")(lambda: delete(f"/admin/users/{nu['id']}"))
step("delete test table")(lambda: delete(f"/admin/hall/tables/{created['id']}"))

print()
print_report()
sys.exit(1 if failed else 0)

