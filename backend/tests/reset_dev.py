"""Dev helper: reset the local SQLite database and restart the API.

    python tests/reset_dev.py            # fresh DB + seed + restart on :8000
    python tests/reset_dev.py --no-start # only rebuild the DB
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
VENV_SCRIPTS = BACKEND / ".venv" / "Scripts"
DB_FILE = BACKEND / "storage" / "myata.db"
PORT = 8000


def pids_on_port(port: int) -> list[int]:
    out = subprocess.run(
        ["netstat", "-ano"], capture_output=True, text=True, encoding="utf-8", errors="ignore"
    ).stdout
    pids = set()
    for line in out.splitlines():
        parts = line.split()
        if len(parts) > 4 and parts[1].endswith(f":{port}") and parts[3] == "LISTENING":
            pids.add(int(parts[4]))
    return sorted(pids)


def stop_api() -> None:
    for pid in pids_on_port(PORT):
        subprocess.run(["taskkill", "/PID", str(pid), "/F", "/T"], capture_output=True)
        print(f"  stopped pid {pid}")
    for _ in range(20):
        if not pids_on_port(PORT):
            return
        time.sleep(0.5)
    raise SystemExit(f"port {PORT} is still busy")


def drop_db() -> None:
    for path in (DB_FILE, DB_FILE.with_name(DB_FILE.name + "-wal"), DB_FILE.with_name(DB_FILE.name + "-shm")):
        if path.exists():
            for _attempt in range(10):
                try:
                    path.unlink()
                    print(f"  deleted {path.name}")
                    break
                except PermissionError:
                    time.sleep(0.5)
            else:
                raise SystemExit(f"cannot delete {path} - server still holds it?")


def migrate() -> None:
    subprocess.run([str(VENV_SCRIPTS / "alembic.exe"), "upgrade", "head"], cwd=BACKEND, check=True)


def start_api() -> None:
    log_dir = BACKEND / "storage" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    subprocess.Popen(
        [
            str(VENV_SCRIPTS / "uvicorn.exe"),
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(PORT),
        ],
        cwd=BACKEND,
        stdout=(log_dir / "api.out.log").open("w", encoding="utf-8"),
        stderr=(log_dir / "api.err.log").open("w", encoding="utf-8"),
    )
    import urllib.request

    for _ in range(40):
        time.sleep(0.5)
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=2) as r:
                print(f"  health: {r.read().decode()}")
                return
        except Exception:
            continue
    raise SystemExit("API did not come up - see storage/logs/api.err.log")


if __name__ == "__main__":
    print("resetting dev database")
    stop_api()
    drop_db()
    migrate()
    if "--no-start" not in sys.argv:
        start_api()
    print("done")
