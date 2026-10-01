from __future__ import annotations

import uuid
from datetime import UTC, datetime
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Response
from sqlalchemy import select

from app.api.deps import DbSession, MenuEditor, Reporter
from app.models.integration import IntegrationLog, SyncMap
from app.schemas.integration import (
    ExportRequest,
    ExportResult,
    IntegrationLogRead,
    IntegrationSettingRead,
    IntegrationSettingUpdate,
    OneCPush,
    OneCPushResult,
)
from app.services.onec import exchange as onec

router = APIRouter(prefix="/admin/integration/1c", tags=["admin:1c"])


def _masked(password: str) -> str:
    return "•" * 8 if password else ""


def _attachment(file_name: str) -> str:
    """Content-Disposition that survives latin-1-only HTTP header encoding."""
    quoted = quote(file_name, safe="")
    ascii_fallback = file_name.encode("ascii", "replace").decode("ascii").replace('"', "_")
    return f'attachment; filename="{ascii_fallback}"; filename*=UTF-8\'\'{quoted}'


@router.get("/settings", response_model=IntegrationSettingRead)
def read_settings(_: Reporter, db: DbSession) -> IntegrationSettingRead:
    row = onec.get_settings(db)
    obj = IntegrationSettingRead.model_validate(row)
    obj.password_masked = _masked(row.password)
    return obj


@router.put("/settings", response_model=IntegrationSettingRead)
def update_settings(
    payload: IntegrationSettingUpdate, _: MenuEditor, db: DbSession
) -> IntegrationSettingRead:
    row = onec.get_settings(db)
    data = payload.model_dump(exclude_unset=True)
    password = data.pop("password", None)
    for field, value in data.items():
        setattr(row, field, value)
    if password:
        row.password = password
    db.commit()
    db.refresh(row)
    obj = IntegrationSettingRead.model_validate(row)
    obj.password_masked = _masked(row.password)
    return obj


@router.get("/logs", response_model=list[IntegrationLogRead])
def logs(_: Reporter, db: DbSession, limit: int = Query(50, ge=1, le=500)) -> list[IntegrationLogRead]:
    rows = db.execute(select(IntegrationLog).order_by(IntegrationLog.started_at.desc()).limit(limit)).scalars().unique()
    return [IntegrationLogRead.model_validate(r) for r in rows]


@router.get("/maps")
def sync_maps(_: Reporter, db: DbSession, limit: int = Query(200, ge=1, le=2000)) -> list[dict]:
    rows = db.execute(select(SyncMap).order_by(SyncMap.entity_type).limit(limit)).scalars().unique()
    return [
        {
            "entity_type": r.entity_type,
            "local_id": r.local_id,
            "external_id": r.external_id,
            "last_synced_at": r.last_synced_at,
        }
        for r in rows
    ]


@router.post("/export", response_model=ExportResult)
def export_now(payload: ExportRequest, user: MenuEditor, db: DbSession) -> ExportResult:
    result = onec.run_export(
        db,
        categories=payload.categories,
        dishes=payload.dishes,
        modifiers=payload.modifiers,
        orders=payload.orders,
        day_closes=payload.day_closes,
        order_statuses=payload.order_status,
        since=payload.since,
        user=user,
        deliver=payload.deliver,
    )
    log = result["log"]
    if result.get("error"):
        raise HTTPException(status_code=502, detail=result["error"])
    return ExportResult(
        log_id=log.id,
        file_name=result.get("file_name") or "",
        entities_total=log.entities_total,
        entities_success=log.entities_success,
        entities_error=log.entities_error,
        status=log.status,
        message=log.message,
        download_url=f"/api/admin/integration/1c/exports/{log.id}",
    )


@router.post("/export/preview")
def export_preview(_: MenuEditor, db: DbSession, limit: int = Query(20, ge=1, le=200)) -> dict:
    nodes = onec.build_package(db, orders=True, day_closes=True)
    trimmed = {k: v[:limit] for k, v in nodes.items()}
    cfg = onec.get_settings(db)
    xml = onec.to_xml(trimmed, cfg, exchange_name="preview")
    counts = {k: len(v) for k, v in nodes.items()}
    return {"counts": counts, "xml": xml[:20000]}


@router.get("/exports/{log_id}")
def download_export(log_id: uuid.UUID, _: Reporter, db: DbSession) -> Response:
    log = db.get(IntegrationLog, log_id)
    if log is None or log.status != "success":
        raise HTTPException(status_code=404, detail="Файл не найден")
    from app.core.config import settings

    path = settings.exports_path / (log.file_name or "")
    if not log.file_name or not path.is_file():
        raise HTTPException(status_code=404, detail="Файл удалён с диска")
    return Response(
        content=path.read_bytes(),
        media_type="application/xml",
        # RFC 6266: latin-1 headers cannot carry the Cyrillic file name
        headers={"Content-Disposition": _attachment(log.file_name)},
    )


@router.get("/exports/{log_id}/xml")
def export_xml(log_id: uuid.UUID, _: Reporter, db: DbSession) -> dict:
    log = db.get(IntegrationLog, log_id)
    if log is None:
        raise HTTPException(status_code=404, detail="Лог не найден")
    return {"file_name": log.file_name, "message": log.message, "xml": log.payload_preview}


@router.post("/push", response_model=OneCPushResult)
def receive_push(payload: OneCPush, _: Reporter, db: DbSession) -> OneCPushResult:
    """Endpoint for 1C to push reference data into the app."""
    stats = onec.apply_incoming(db, payload.items)
    cfg = onec.get_settings(db)
    cfg.last_import_at = datetime.now(UTC)
    db.commit()
    return OneCPushResult(**stats)


@router.get("/status")
def integration_status(_: Reporter, db: DbSession) -> dict:
    cfg = onec.get_settings(db)
    pending = db.execute(
        select(IntegrationLog).where(IntegrationLog.status == "error").order_by(IntegrationLog.started_at.desc()).limit(1)
    ).scalar_one_or_none()
    return {
        "enabled": cfg.enabled,
        "exchange_plan": cfg.exchange_plan,
        "configured": bool(cfg.endpoint_url and cfg.login),
        "last_export_at": cfg.last_export_at,
        "last_import_at": cfg.last_import_at,
        "auto_export_interval_minutes": cfg.auto_export_interval_minutes,
        "last_error": pending.message if pending else None,
        "entity_types": onec.ENTITY_TYPES,
    }
