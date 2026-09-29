from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.api import auth, hall, integration, menu, occupancy, orders, public, upload, users, ws
from app.core.config import settings
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.services.onec import exchange as onec
from app.services.ws import set_main_loop

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("myata")

# import models so Base.metadata is complete before create_all / alembic
from app import models  # noqa: E402,F401


def init_storage() -> None:
    settings.images_path.mkdir(parents=True, exist_ok=True)
    settings.exports_path.mkdir(parents=True, exist_ok=True)


def create_schema() -> None:
    """Used for SQLite bootstrap; PostgreSQL should run alembic upgrade head."""
    Base.metadata.create_all(bind=engine)


async def _auto_export_loop() -> None:
    """Optional periodic push of the menu catalogue to 1C."""
    while True:
        try:
            await asyncio.sleep(300)
            db = SessionLocal()
            try:
                cfg = onec.get_settings(db)
                if not cfg.enabled or cfg.auto_export_interval_minutes <= 0:
                    continue
                last = cfg.last_export_at
                if last and last.tzinfo is None:
                    last = last.replace(tzinfo=UTC)
                interval = timedelta(minutes=cfg.auto_export_interval_minutes)
                if last and datetime.now(UTC) - last < interval:
                    continue
                onec.run_export(
                    db,
                    categories=cfg.export_categories,
                    dishes=cfg.export_dishes,
                    modifiers=cfg.export_modifiers,
                    orders=cfg.export_orders,
                    day_closes=cfg.export_day_closes,
                    order_statuses=["closed"],
                )
            finally:
                db.close()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - background task must not die
            log.warning("auto export failed: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_storage()
    set_main_loop(asyncio.get_running_loop())

    if settings.is_sqlite:
        create_schema()

    db = SessionLocal()
    try:
        from app.seed import seed_if_empty

        seed_if_empty(db)
    except Exception as exc:  # noqa: BLE001 - never block startup on seeding
        log.warning("seed skipped: %s", exc)
    finally:
        db.close()

    task = asyncio.create_task(_auto_export_loop())
    log.info("%s API ready", settings.project_name)
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass


app = FastAPI(
    title=f"{settings.project_name} API",
    description=(
        "Электронное меню, QR-коды на столы, учёт загруженности зала, "
        "управление персоналом и обмен с 1С:УНФ."
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for module in (public, auth, menu, hall, occupancy, orders, users, upload, integration, ws):
    app.include_router(module.router, prefix=settings.api_prefix)


@app.get("/health")
def health() -> dict:
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:  # noqa: BLE001
        db_ok = False
    finally:
        db.close()
    return {
        "ok": db_ok,
        "service": settings.project_name,
        "db": "ok" if db_ok else "error",
        "sqlite": settings.is_sqlite,
        "time": datetime.now(UTC).isoformat(),
    }


@app.get("/")
def root() -> dict:
    return {
        "service": settings.project_name,
        "docs": "/docs",
        "guest_menu": "/t/{table_token}",
        "admin": "React SPA on the Vite dev server",
    }


app.mount("/static", StaticFiles(directory=str(settings.images_path)), name="static")


@app.exception_handler(ValueError)
async def value_error_handler(_request, exc: ValueError):  # noqa: ANN001
    return JSONResponse(status_code=400, content={"detail": str(exc)})
