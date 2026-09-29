"""Checks the image upload/download/delete path used by the dish photo field.

`python tests/upload_test.py [base_url]`
"""
from __future__ import annotations

import base64
import sys
from pathlib import Path

import httpx

sys.stdout.reconfigure(encoding="utf-8")

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/")
API = f"{BASE}/api"

# 1x1 transparent PNG
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
BAD = b"<svg onload=alert(1)></svg>"

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


admin = httpx.Client(base_url=API, timeout=30.0)
token = admin.post("/auth/login", json={"username": "admin", "password": "admin123"}).json()["access_token"]
admin.headers["Authorization"] = f"Bearer {token}"

res = admin.post("/admin/upload/image", files={"file": ("photo.png", PNG, "image/png")})
check("upload accepts png", res.status_code == 201, f"{res.status_code} {res.text[:200]}")
url = res.json().get("url", "") if res.status_code == 201 else ""

if url:
    # /static is mounted straight at storage/images, so the url must NOT gain an
    # extra "images" segment or the browser gets a 404
    check("url points at the mounted /static root", url.startswith("/static/") and url.count("/") == 2,
          f"got {url}")
    check("filename is randomised", "photo" not in url.split("/")[-1], f"leaks the original name: {url}")

    fetched = httpx.get(f"{BASE}{url}", timeout=30.0)
    check("uploaded image is served", fetched.status_code == 200, f"{fetched.status_code}")
    check("bytes round-trip", fetched.content == PNG, f"{len(fetched.content)} vs {len(PNG)}")

    # deleting must remove the file, and a traversal attempt must not
    gone = admin.request("DELETE", "/admin/upload/image", json={"url": url})
    check("delete returns ok", gone.status_code == 200 and gone.json().get("ok") is True, f"{gone.text[:160]}")
    check("file is gone after delete", httpx.get(f"{BASE}{url}", timeout=30.0).status_code == 404,
          "still served")

# deleting must not be able to escape the images directory
canary = Path(__file__).resolve().parent.parent / "app" / "main.py"
before = canary.read_bytes()
traversal = admin.request(
    "DELETE", "/admin/upload/image", json={"url": "/static/../../app/main.py"}
)
check("traversal delete is a no-op", traversal.status_code == 200, f"{traversal.status_code}")
check("traversal delete leaves the file intact", canary.read_bytes() == before, "app/main.py was deleted")

res = admin.post("/admin/upload/image", files={"file": ("evil.svg", BAD, "image/svg+xml")})
check("svg upload is refused", res.status_code == 415, f"{res.status_code} {res.text[:160]}")

empty = admin.post("/admin/upload/image", files={"file": ("x.png", b"", "image/png")})
check("empty upload is refused", empty.status_code == 400, f"{empty.status_code}")

# an unauthenticated upload must not work
anon = httpx.Client(base_url=API, timeout=30.0)
res = anon.post("/admin/upload/image", files={"file": ("photo.png", PNG, "image/png")})
check("upload requires auth", res.status_code in (401, 403), f"{res.status_code}")

# a waiter may not upload (menu is manager territory)
waiter = httpx.Client(base_url=API, timeout=30.0)
wt = waiter.post("/auth/login", json={"username": "waiter", "pin": "1111"}).json()["access_token"]
waiter.headers["Authorization"] = f"Bearer {wt}"
res = waiter.post("/admin/upload/image", files={"file": ("photo.png", PNG, "image/png")})
check("waiter cannot upload", res.status_code == 403, f"{res.status_code}")

# the real user-facing path: attach the photo to a dish and show it on the QR menu
res = admin.post("/admin/upload/image", files={"file": ("photo.png", PNG, "image/png")})
if res.status_code == 201:
    photo = res.json()["url"]
    dishes = admin.get("/admin/menu/dishes").json()
    dish = next((d for d in dishes if not d.get("image_url")), None)
    if dish is None:
        dish = dishes[0]
    patched = admin.patch(f"/admin/menu/dishes/{dish['id']}", json={"image_url": photo})
    check("photo can be attached to a dish", patched.status_code == 200, f"{patched.text[:160]}")
    check("dish keeps the photo", patched.json().get("image_url") == photo, f"{patched.json().get('image_url')}")

    token = admin.get("/admin/hall/tables").json()[0]["qr_token"]
    menu = httpx.get(f"{API}/public/menu/{token}", timeout=30.0).json()

    # the public menu nests dishes inside the category tree, so flatten it
    def walk(cats: list[dict]) -> list[dict]:
        out: list[dict] = []
        for c in cats:
            out.extend(c.get("dishes", []))
            out.extend(walk(c.get("children", [])))
        return out

    shown = next((d for d in walk(menu["categories"]) if d["id"] == dish["id"]), None)
    check("guest menu exposes the photo", shown is not None and shown["image_url"] == photo,
          f"guest sees {shown and shown.get('image_url')}")
    check("photo is fetchable from the guest origin", httpx.get(f"{BASE}{photo}", timeout=30.0).status_code == 200)
    admin.request("DELETE", "/admin/upload/image", json={"url": photo})

print()
print("=" * 62)
print(f"  PASS: {passed}    FAIL: {len(failed)}")
if failed:
    for name in failed:
        print(f"    - {name}")
print("=" * 62)
sys.exit(1 if failed else 0)
