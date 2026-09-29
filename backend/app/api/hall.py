from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import DbSession, FloorReader, HallEditor
from app.core.security import generate_token
from app.models.hall import Hall, Table, TableSession
from app.schemas.hall import (
    HallCreate,
    HallRead,
    HallUpdate,
    LayoutSave,
    TableCreate,
    TableRead,
    TableSessionRead,
    TableUpdate,
)
from app.services import hall as hall_service
from app.services.qr import make_qr, new_table_token, qr_matrix, svg_grid_sheet
from app.services.ws import publish_occupancy_change

router = APIRouter(prefix="/admin/hall", tags=["admin:hall"])


def get_table(db, table_id: uuid.UUID) -> Table:
    table = db.execute(
        select(Table).options(selectinload(Table.hall)).where(Table.id == table_id)
    ).scalar_one_or_none()
    if table is None:
        raise HTTPException(status_code=404, detail="Стол не найден")
    return table


def session_read(session: TableSession | None) -> TableSessionRead | None:
    if session is None:
        return None
    obj = TableSessionRead.model_validate(session)
    user = session.opened_by_user
    if user is not None:
        obj.opened_by = user.full_name or user.username
    return obj


def table_read(db, table: Table) -> TableRead:
    rows = hall_service.table_payloads(db, [table])
    row = rows[0]
    obj = TableRead.model_validate(table)
    obj.qr_url = row["qr_url"]
    obj.status = row["status"]
    obj.current_session = session_read(row["current_session"])
    obj.seated_since = row["current_session"].started_at if row["current_session"] else None
    obj.open_orders = row["open_orders"]
    obj.order_total = row["order_total"]
    obj.next_reservation_at = row["next_reservation_at"]
    return obj


def emit_table(db, table: Table) -> None:
    publish_occupancy_change(
        {"table_id": str(table.id), "table": table.name, **_table_event(db, table)}
    )


def _table_event(db, table: Table) -> dict:
    rows = hall_service.table_payloads(db, [table])
    row = rows[0]
    return {
        "status": row["status"],
        "open_orders": row["open_orders"],
        "order_total": row["order_total"],
        "guests_count": row["current_session"].guests_count if row["current_session"] else 0,
        "seated_since": (
            row["current_session"].started_at.isoformat() if row["current_session"] else None
        ),
    }


# --------------------------------------------------------------------------
# halls
# --------------------------------------------------------------------------
@router.get("/halls", response_model=list[HallRead])
def list_halls(_: FloorReader, db: DbSession, include_inactive: bool = True) -> list[HallRead]:
    out: list[HallRead] = []
    for hall in hall_service.list_halls(db, active_only=not include_inactive):
        payload = hall_service.hall_payload(db, hall)
        obj = HallRead.model_validate(payload["hall"])
        obj.tables_count = payload["tables_count"]
        obj.seats_total = payload["seats_total"]
        out.append(obj)
    return out


@router.post("/halls", response_model=HallRead, status_code=status.HTTP_201_CREATED)
def create_hall(payload: HallCreate, _: HallEditor, db: DbSession) -> HallRead:
    hall = Hall(**payload.model_dump())
    db.add(hall)
    db.commit()
    db.refresh(hall)
    return HallRead.model_validate(hall)


@router.patch("/halls/{hall_id}", response_model=HallRead)
def update_hall(hall_id: uuid.UUID, payload: HallUpdate, _: HallEditor, db: DbSession) -> HallRead:
    hall = db.get(Hall, hall_id)
    if hall is None:
        raise HTTPException(status_code=404, detail="Зал не найден")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(hall, field, value)
    db.commit()
    db.refresh(hall)
    return HallRead.model_validate(hall)


@router.delete("/halls/{hall_id}")
def delete_hall(hall_id: uuid.UUID, _: HallEditor, db: DbSession) -> dict:
    hall = db.get(Hall, hall_id)
    if hall is None:
        raise HTTPException(status_code=404, detail="Зал не найден")
    db.delete(hall)
    db.commit()
    return {"ok": True}


# --------------------------------------------------------------------------
# tables
# --------------------------------------------------------------------------
@router.get("/tables", response_model=list[TableRead])
def list_tables(
    _: FloorReader,
    db: DbSession,
    hall_id: uuid.UUID | None = None,
    include_inactive: bool = True,
) -> list[TableRead]:
    tables = hall_service.list_tables(db, hall_id, active_only=not include_inactive)
    rows = hall_service.table_payloads(db, tables)
    out: list[TableRead] = []
    for row in rows:
        obj = TableRead.model_validate(row["table"])
        obj.qr_url = row["qr_url"]
        obj.status = row["status"]
        obj.current_session = session_read(row["current_session"])
        obj.seated_since = row["current_session"].started_at if row["current_session"] else None
        obj.open_orders = row["open_orders"]
        obj.order_total = row["order_total"]
        obj.next_reservation_at = row["next_reservation_at"]
        out.append(obj)
    return out


@router.get("/tables/{table_id}", response_model=TableRead)
def get_table_detail(table_id: uuid.UUID, _: FloorReader, db: DbSession) -> TableRead:
    return table_read(db, get_table(db, table_id))


@router.post("/tables", response_model=TableRead, status_code=status.HTTP_201_CREATED)
def create_table(payload: TableCreate, _: HallEditor, db: DbSession) -> TableRead:
    if db.get(Hall, payload.hall_id) is None:
        raise HTTPException(status_code=400, detail="Зал не найден")
    table = Table(
        **payload.model_dump(),
        qr_token=new_table_token(),
        qr_regenerated_at=datetime.now(UTC),
    )
    db.add(table)
    db.commit()
    db.refresh(table)
    return table_read(db, table)


@router.patch("/tables/{table_id}", response_model=TableRead)
def update_table(
    table_id: uuid.UUID, payload: TableUpdate, _: HallEditor, db: DbSession
) -> TableRead:
    table = get_table(db, table_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(table, field, value)
    db.commit()
    db.refresh(table)
    return table_read(db, table)


@router.post("/tables/layout", response_model=list[TableRead])
def save_layout(
    payload: LayoutSave,
    _: HallEditor,
    db: DbSession,
) -> list[TableRead]:
    """Persist positions after drag & drop on the plan canvas."""
    updated: list[Table] = []
    for item in payload.tables:
        table = db.get(Table, item.id)
        if table is None:
            continue
        table.x = item.x
        table.y = item.y
        table.width = item.width
        table.height = item.height
        table.rotation = item.rotation
        if item.shape:
            table.shape = item.shape
        updated.append(table)
    db.commit()
    for table in updated:
        db.refresh(table)
    return [table_read(db, t) for t in updated]


@router.delete("/tables/{table_id}")
def delete_table(table_id: uuid.UUID, _: HallEditor, db: DbSession) -> dict:
    table = db.get(Table, table_id)
    if table is None:
        raise HTTPException(status_code=404, detail="Стол не найден")
    db.delete(table)
    db.commit()
    return {"ok": True}


# --------------------------------------------------------------------------
# QR codes
# --------------------------------------------------------------------------
@router.get("/tables/{table_id}/qr")
def table_qr(
    table_id: uuid.UUID,
    _: HallEditor,
    db: DbSession,
    scale: int = Query(8, ge=2, le=24),
) -> dict:
    table = get_table(db, table_id)
    qr = make_qr(table.qr_token, size=scale)
    return {
        "table": table.name,
        "url": qr.url,
        "svg": qr.svg,
        "png_base64": f"data:image/png;base64,{_b64(qr.png)}",
        "matrix": qr.modules,
        "filename": qr.filename,
    }


@router.get("/tables/{table_id}/qr.png")
def table_qr_png(
    table_id: uuid.UUID,
    _: HallEditor,
    db: DbSession,
    scale: int = Query(10, ge=2, le=30),
) -> Response:
    table = get_table(db, table_id)
    qr = make_qr(table.qr_token, size=scale)
    return Response(
        content=qr.png,
        media_type="image/png",
        headers={"Content-Disposition": f'inline; filename="{qr.filename}"'},
    )


@router.post("/tables/{table_id}/qr/regenerate", response_model=TableRead)
def regenerate_qr(table_id: uuid.UUID, _: HallEditor, db: DbSession) -> TableRead:
    """Issue a fresh token - invalidates the old printed sticker."""
    table = get_table(db, table_id)
    table.qr_token = generate_token(12)
    table.qr_regenerated_at = datetime.now(UTC)
    db.commit()
    db.refresh(table)
    return table_read(db, table)


@router.get("/qr/sheet")
def qr_sheet(
    _: HallEditor,
    db: DbSession,
    hall_id: uuid.UUID | None = None,
    columns: int = Query(3, ge=1, le=8),
) -> Response:
    """One printable SVG with a QR for every table in the venue."""
    tables = hall_service.list_tables(db, hall_id, active_only=True)
    entries = [(t.qr_token, t.name, t.seats) for t in tables]
    if not entries:
        raise HTTPException(status_code=404, detail="Нет столов для печати")
    svg = svg_grid_sheet(entries, columns=columns)
    return Response(
        content=svg,
        media_type="image/svg+xml",
        headers={"Content-Disposition": 'inline; filename="qr-sheets.svg"'},
    )


@router.get("/qr/preview")
def qr_preview(token: str, scale: int = Query(6, ge=2, le=20)) -> Response:
    qr = make_qr(token, size=scale)
    return Response(content=qr.png, media_type="image/png")


@router.get("/tables/{table_id}/qr/matrix")
def table_qr_matrix(table_id: uuid.UUID, _: HallEditor, db: DbSession) -> dict:
    table = get_table(db, table_id)
    return qr_matrix(table.qr_token)


def _b64(data: bytes) -> str:
    import base64

    return base64.b64encode(data).decode("ascii")
