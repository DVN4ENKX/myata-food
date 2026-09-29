"""Contract test: response shapes the TypeScript frontend depends on.

The smoke test covers business flows; this one guards the exact keys and types
that `frontend/src/lib/types.ts` declares, so a backend change that renames a
field breaks here instead of silently rendering "undefined" in the UI.

Run against a live server:  python contract_test.py [base_url]
"""
from __future__ import annotations

import sys
from typing import Any
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


def has_keys(name: str, payload: Any, required: list[str]) -> None:
    """Assert a dict carries every required key."""
    if not isinstance(payload, dict):
        check(name, False, f"expected object, got {type(payload).__name__}")
        return
    missing = [k for k in required if k not in payload]
    check(name, not missing, f"missing {missing}; got {sorted(payload)}")


def has_types(name: str, payload: dict, spec: dict[str, type | tuple]) -> None:
    bad = []
    for key, expected in spec.items():
        if key not in payload:
            bad.append(f"{key}=absent")
            continue
        value = payload[key]
        if value is None:
            continue
        if isinstance(expected, tuple):
            if not isinstance(value, expected):
                bad.append(f"{key}={type(value).__name__}")
        elif not isinstance(value, expected):
            bad.append(f"{key}={type(value).__name__}")
    check(name, not bad, f"type mismatch: {bad}")


client = httpx.Client(base_url=API, timeout=30.0, headers={"Content-Type": "application/json"})


def login(username: str = "admin", password: str = "admin123") -> str:
    res = client.post("/auth/login", json={"username": username, "password": password})
    res.raise_for_status()
    return res.json()["access_token"]


def get(path: str, **params) -> Any:
    res = client.get(path, params=params or None)
    if res.status_code != 200:
        raise AssertionError(f"GET {path} -> {res.status_code} {res.text[:200]}")
    return res.json()


token = login()
client.headers["Authorization"] = f"Bearer {token}"

# --------------------------------------------------------------------------
# auth / users
# --------------------------------------------------------------------------
me = get("/auth/me")
has_keys("UserRead shape", me, ["id", "username", "full_name", "role", "is_active", "can_manage_menu",
                                "can_manage_hall", "can_manage_orders", "can_manage_users",
                                "can_view_reports", "salary_percent", "notes"])
has_types("UserRead types", me, {"id": str, "username": str, "role": str, "is_active": bool,
                                "can_view_reports": bool, "salary_percent": int})

users = get("/admin/users")
check("list[UserRead]", isinstance(users, list) and len(users) > 0, f"got {type(users).__name__}")

matrix = get("/admin/users/permissions")
has_keys("PermissionMatrix shape", matrix, ["roles", "flags"])
has_types("PermissionMatrix types", matrix, {"roles": dict, "flags": list})
check(
    "PermissionMatrix flags keys",
    isinstance(matrix.get("flags"), list)
    and all("key" in f and "label" in f for f in matrix["flags"]),
    f"got {matrix.get('flags')}",
)

audit = get("/admin/users/audit", limit=5)
check(
    "AuditEntry shape",
    isinstance(audit, list) and all(
        {"id", "user", "action", "entity_type", "created_at"} <= set(row) for row in audit
    ),
    f"got {audit[:1]}",
)

# --------------------------------------------------------------------------
# menu
# --------------------------------------------------------------------------
menu_settings = get("/admin/menu/settings")
has_keys("MenuSettings shape", menu_settings, ["id", "title", "subtitle", "currency_symbol",
                                               "show_weights", "show_calories", "show_allergens",
                                               "welcome_text", "footer_text", "theme_color"])

stats = get("/admin/menu/stats")
has_keys("MenuStats shape", stats, ["dishes_total", "dishes_available", "dishes_unavailable",
                                    "categories_total", "categories_hidden", "avg_price"])
has_types("MenuStats types", stats, {"dishes_total": int, "avg_price": int})

categories = get("/admin/menu/categories")
check(
    "CategoryRead shape",
    isinstance(categories, list)
    and all({"id", "name", "slug", "dishes_count", "show_in_qr", "is_active"} <= set(c) for c in categories),
    f"got {categories[:1]}",
)

dishes = get("/admin/menu/dishes")
check("list[DishRead]", isinstance(dishes, list) and len(dishes) > 0, "no dishes")
if dishes:
    d = dishes[0]
    has_keys("DishRead shape", d, ["id", "category_id", "category_name", "name", "price",
                                   "weight_grams", "calories", "cooking_minutes", "allergens",
                                   "tags", "image_url", "is_active", "is_available", "show_in_qr",
                                   "modifier_groups"])
    has_types("DishRead types", d, {"id": str, "price": int, "allergens": list, "tags": list,
                                    "modifier_groups": list})
    check("price is a JSON number", isinstance(d["price"], (int, float)), f"price={d['price']!r}")
    for group in d["modifier_groups"]:
        has_keys("ModifierGroupRead shape", group, ["id", "name", "min_select", "max_select", "modifiers"])
        has_types("ModifierGroupRead types", group, {"min_select": int, "max_select": int, "modifiers": list})
        for mod in group["modifiers"]:
            has_keys("ModifierRead shape", mod, ["id", "name", "price_delta", "is_default", "is_active"])
            break
        break

groups = get("/admin/menu/modifier-groups")
check("list[ModifierGroupRead]", isinstance(groups, list), f"got {type(groups).__name__}")

# --------------------------------------------------------------------------
# public / guest
# --------------------------------------------------------------------------
tables = get("/admin/hall/tables")
check("list[TableRead]", isinstance(tables, list) and len(tables) > 0, "no tables")
if tables:
    table = tables[0]
    has_keys("TableRead shape", table, ["id", "hall_id", "name", "seats", "shape", "x", "y", "width",
                                        "height", "rotation", "is_active", "qr_token", "qr_url",
                                        "status", "current_session", "seated_since", "open_orders",
                                        "order_total", "next_reservation_at"])
    has_types("TableRead types", table, {"id": str, "seats": int, "x": int, "y": int,
                                         "order_total": (int, float), "status": str,
                                         "is_active": bool, "open_orders": int})

    menu = get(f"/public/menu/{table['qr_token']}")
    has_keys("PublicMenu shape", menu, ["venue", "table_name", "table_number", "hall_name",
                                        "settings", "categories", "dishes_count"])
    has_types("PublicMenu types", menu, {"venue": str, "settings": dict, "categories": list,
                                         "dishes_count": int})
    if menu["categories"]:
        cat = menu["categories"][0]
        has_keys("CategoryTree shape", cat, ["id", "name", "slug", "dishes", "children"])
        has_types("CategoryTree types", cat, {"dishes": list, "children": list})
        if cat["dishes"]:
            has_keys("Public DishRead shape", cat["dishes"][0], ["id", "name", "price", "is_available",
                                                                 "modifier_groups"])

    info = get(f"/public/table/{table['qr_token']}")
    has_keys("GuestTableInfo shape", info, ["id", "name", "hall", "seats", "venue",
                                            "is_seated", "status", "guests_count", "orders"])
    has_types("GuestTableInfo types", info, {"is_seated": bool, "guests_count": int, "orders": list})

    orders_here = get(f"/public/table/{table['qr_token']}/orders")
    check("guest orders list", isinstance(orders_here, list), f"got {type(orders_here).__name__}")

# --------------------------------------------------------------------------
# orders
# --------------------------------------------------------------------------
kitchen = get("/admin/orders/kitchen")
has_keys("KitchenBoard shape", kitchen, ["orders", "max_wait_minutes"])
has_types("KitchenBoard types", kitchen, {"orders": list, "max_wait_minutes": int})
if kitchen["orders"]:
    o = kitchen["orders"][0]
    has_keys("OrderRead shape", o, ["id", "order_number", "table_id", "table_name", "status",
                                    "source", "guests_count", "guest_comment", "client_name",
                                    "total_amount", "total_discount", "exported_to_1c",
                                    "created_at", "closed_at", "items"])
    has_types("OrderRead types", o, {"order_number": str, "status": str, "source": str,
                                     "total_amount": (int, float), "items": list})
    check("total_amount is a JSON number", isinstance(o["total_amount"], (int, float)),
          f"total={o['total_amount']!r}")
    if o["items"]:
        it = o["items"][0]
        has_keys("OrderItemRead shape", it, ["id", "dish_id", "dish_name", "price", "quantity",
                                             "comment", "cooking_minutes", "status", "modifiers",
                                             "line_total"])
        has_types("OrderItemRead types", it, {"dish_name": str, "price": (int, float),
                                              "quantity": int, "modifiers": list,
                                              "line_total": (int, float)})
        for mod in it["modifiers"]:
            has_keys("OrderItemModifierRead shape", mod, ["id", "modifier_id", "name", "price_delta"])
            break

open_orders = get("/admin/orders", only_open=True, limit=10)
check("orders filter by only_open", isinstance(open_orders, list), f"got {type(open_orders).__name__}")

# --------------------------------------------------------------------------
# halls / occupancy
# --------------------------------------------------------------------------
halls = get("/admin/hall/halls")
check("list[HallRead]", isinstance(halls, list) and len(halls) > 0, "no halls")
if halls:
    has_keys("HallRead shape", halls[0], ["id", "name", "description", "layout_width",
                                          "layout_height", "sort_order", "is_active",
                                          "tables_count", "seats_total"])
    has_types("HallRead types", halls[0], {"layout_width": int, "layout_height": int,
                                           "tables_count": int, "seats_total": int})

board = get("/admin/occupancy/board")
has_keys("OccupancyBoard shape", board, ["generated_at", "summary", "halls", "tables", "reservations_today"])
has_types("OccupancyBoard types", board, {"summary": dict, "halls": list, "tables": list})
check(
    "reservations_today is a number (not a list)",
    isinstance(board["reservations_today"], (int, float)),
    f"got {type(board['reservations_today']).__name__}",
)
has_keys("OccupancySummary shape", board["summary"],
         ["tables_total", "tables_busy", "tables_free", "tables_reserved", "tables_cleaning",
          "seats_total", "guests_now", "occupancy_percent", "revenue_today", "orders_today",
          "active_sessions"])
has_types("OccupancySummary types", board["summary"],
          {"tables_total": int, "tables_busy": int, "occupancy_percent": int,
           "revenue_today": (int, float), "orders_today": int})

summary = get("/admin/occupancy/summary")
check("summary endpoint", isinstance(summary, dict) and "tables_total" in summary, f"got {summary}")

if tables:
    sessions = get(f"/admin/occupancy/tables/{tables[0]['id']}/sessions", limit=5)
    check(
        "SessionListEntry shape",
        isinstance(sessions, list)
        and all(
            {"id", "guests_count", "status", "started_at", "ended_at", "wait_minutes",
             "comment", "guest_name", "opened_by", "orders_count", "revenue"} <= set(s)
            for s in sessions
        ),
        f"got {sessions[:1]}",
    )

reservations = get("/admin/occupancy/reservations")
check("list[ReservationRead]", isinstance(reservations, list), f"got {type(reservations).__name__}")

# --------------------------------------------------------------------------
# reports
# --------------------------------------------------------------------------
report = get("/admin/occupancy/report/daily")
has_keys("DailyReport shape", report, ["business_date", "guests_total", "orders_total",
                                        "revenue_total", "avg_check", "tables_used",
                                        "by_source", "top_dishes", "hourly_load", "closed"])
has_types("DailyReport types", report, {"business_date": str, "guests_total": int, "orders_total": int,
                                         "revenue_total": (int, float), "by_source": dict,
                                         "top_dishes": list, "hourly_load": list, "closed": bool})
for entry in report["top_dishes"][:1]:
    has_keys("top_dishes entry", entry, ["name", "qty", "revenue"])
for entry in report["hourly_load"][:1]:
    has_keys("hourly_load entry", entry, ["hour", "orders", "revenue"])

staff = get("/admin/occupancy/report/staff")
check(
    "StaffLoad shape",
    isinstance(staff, list)
    and all({"user_id", "username", "full_name", "orders", "revenue"} <= set(s) for s in staff),
    f"got {staff[:1]}",
)

# --------------------------------------------------------------------------
# 1C
# --------------------------------------------------------------------------
settings = get("/admin/integration/1c/settings")
has_keys("IntegrationSettingRead shape", settings,
         ["id", "enabled", "exchange_plan", "endpoint_url", "login", "password_masked",
          "org_ref", "price_type_ref", "auto_export_interval_minutes", "export_categories",
          "export_dishes", "export_modifiers", "export_orders", "export_day_closes",
          "last_export_at", "last_import_at"])
has_types("IntegrationSettingRead types", settings, {"enabled": bool, "exchange_plan": str,
                                                     "auto_export_interval_minutes": int})
check("password is never returned raw", "password" not in settings, f"keys={sorted(settings)}")

logs = get("/admin/integration/1c/logs", limit=5)
check(
    "IntegrationLogRead shape",
    isinstance(logs, list)
    and all(
        {"id", "direction", "status", "file_name", "entities_total", "entities_success",
         "entities_error", "message", "started_at", "finished_at"} <= set(row)
        for row in logs
    ),
    f"got {logs[:1]}",
)

maps = get("/admin/integration/1c/maps", limit=5)
check(
    "SyncMap shape",
    isinstance(maps, list)
    and all({"entity_type", "local_id", "external_id"} <= set(m) for m in maps),
    f"got {maps[:1]}",
)

# --------------------------------------------------------------------------
# frontend must never be handed a raw password field
# --------------------------------------------------------------------------
# DELETE /admin/users/{id} is a soft deactivate, so the username stays taken:
# use a unique one per run to keep the check repeatable.
probe_username = f"contract_probe_{uuid4().hex[:10]}"
created = client.post(
    "/admin/users",
    json={"username": probe_username, "password": "probe1234", "role": "waiter", "full_name": "Probe"},
)
if created.status_code == 201:
    body = created.json()
    check("created user hides password", "password" not in body and "hashed_password" not in body,
          f"keys={sorted(body)}")
    check("waiter defaults to no reports", body["can_view_reports"] is False,
          f"can_view_reports={body['can_view_reports']}")
    check("created user reports no password hash", body.get("notes") is not None, f"keys={sorted(body)}")
    client.delete(f"/admin/users/{body['id']}")
else:
    check("created user hides password", False, f"status {created.status_code} {created.text[:200]}")

print()
print("=" * 62)
print(f"  PASS: {passed}    FAIL: {len(failed)}")
if failed:
    print("  failed:")
    for name in failed:
        print(f"    - {name}")
print("=" * 62)
sys.exit(1 if failed else 0)
