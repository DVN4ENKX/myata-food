from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.deps import DbSession, FloorReader, OrderEditor, Reporter
from app.db.base import ReservationStatus, TableStatus
from app.models.hall import DayClose, Reservation, Table, TableSession
from app.models.order import Order
from app.models.user import User
from app.schemas.hall import (
    CloseTableRequest,
    DailyReport,
    HallRead,
    OccupancyBoard,
    ReservationCreate,
    ReservationRead,
    ReservationUpdate,
    SeatRequest,
    SessionUpdate,
    TableRead,
)
from app.services import hall as hall_service
from app.services import orders as order_service
from app.services.ws import publish_occupancy_change

router = APIRouter(prefix="/admin/occupancy", tags=["admin:occupancy"])


def _load_table(db, table_id: uuid.UUID) -> Table:
    table = db.execute(
        select(Table).options(selectinload(Table.hall)).where(Table.id == table_id)
    ).scalar_one_or_none()
    if table is None:
        raise HTTPException(status_code=404, detail="Стол не найден")
    return table


def _pick_free_table(db, guests_count: int) -> uuid.UUID | None:
    """Smallest free table that fits the party, so bookings get a table."""
    from app.models.hall import TableSession as _Session

    busy = select(_Session.table_id).where(_Session.ended_at.is_(None))
    stmt = (
        select(Table.id)
        .where(
            Table.is_active.is_(True),
            Table.seats >= guests_count,
            Table.id.notin_(busy),
        )
        .order_by(Table.seats, Table.sort_order)
        .limit(1)
    )
    return db.execute(stmt).scalar_one_or_none()


def _event(db, table: Table, user: User | None = None) -> None:
    rows = hall_service.table_payloads(db, [table])
    row = rows[0]
    session = row["current_session"]
    publish_occupancy_change(
        {
            "table_id": str(table.id),
            "table": table.name,
            "status": row["status"],
            "open_orders": row["open_orders"],
            "order_total": row["order_total"],
            "guests_count": session.guests_count if session else 0,
            "seated_since": session.started_at.isoformat() if session else None,
            "by": user.full_name or user.username if user else None,
        }
    )


# --------------------------------------------------------------------------
# seating / closing
# --------------------------------------------------------------------------
@router.post("/tables/{table_id}/seat", response_model=TableRead)
def seat_table(
    table_id: uuid.UUID, payload: SeatRequest, user: OrderEditor, db: DbSession
) -> TableRead:
    table = _load_table(db, table_id)
    existing = hall_service.get_active_session(db, table_id)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Стол уже занят ({existing.guests_count} гост.)",
        )

    session = TableSession(
        table_id=table.id,
        opened_by_user_id=user.id,
        guests_count=payload.guests_count,
        status=TableStatus.seated,
        started_at=datetime.now(UTC),
        wait_minutes=payload.wait_minutes,
        comment=payload.comment,
        guest_name=payload.guest_name,
    )
    db.add(session)
    db.flush()
    hall_service.log_event(
        db,
        table.id,
        "seated",
        session_id=session.id,
        user_id=user.id,
        guests_count=payload.guests_count,
    )
    db.commit()
    db.refresh(session)

    from app.api.hall import table_read

    _event(db, table, user)
    return table_read(db, table)


@router.post("/tables/{table_id}/close", response_model=TableRead)
def close_table(
    table_id: uuid.UUID, payload: CloseTableRequest, user: OrderEditor, db: DbSession
) -> TableRead:
    table = _load_table(db, table_id)
    session = hall_service.get_active_session(db, table_id)
    now = datetime.now(UTC)

    if payload.clear_tables:
        order_service.close_table_orders(db, table_id)

    if session:
        session.ended_at = now
        hall_service.log_event(
            db,
            table.id,
            "closed",
            session_id=session.id,
            user_id=user.id,
            guests_count=session.guests_count,
        )
    db.commit()

    from app.api.hall import table_read

    _event(db, table, user)
    result = table_read(db, table)
    result.open_orders = 0
    result.order_total = 0
    return result


@router.post("/tables/{table_id}/update-session", response_model=TableRead)
def update_session(
    table_id: uuid.UUID, payload: SessionUpdate, user: OrderEditor, db: DbSession
) -> TableRead:
    table = _load_table(db, table_id)
    session = hall_service.get_active_session(db, table_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Стол свободен")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(session, field, value)
    db.commit()

    from app.api.hall import table_read

    _event(db, table, user)
    return table_read(db, table)


@router.get("/tables/{table_id}/sessions", response_model=list[dict])
def table_history(
    table_id: uuid.UUID, _: FloorReader, db: DbSession, limit: int = Query(20, ge=1, le=200)
) -> list[dict]:
    rows = db.execute(
        select(TableSession)
        .options(selectinload(TableSession.opened_by_user))
        .where(TableSession.table_id == table_id)
        .order_by(TableSession.started_at.desc())
        .limit(limit)
    ).scalars().unique()
    out = []
    for s in rows:
        orders = db.execute(
            select(func.count(Order.id), func.coalesce(func.sum(Order.total_amount), 0)).where(
                Order.table_session_id == s.id
            )
        ).one()
        out.append(
            {
                "id": str(s.id),
                "guests_count": s.guests_count,
                "status": s.status,
                "started_at": s.started_at,
                "ended_at": s.ended_at,
                "wait_minutes": s.wait_minutes,
                "comment": s.comment,
                "guest_name": s.guest_name,
                "opened_by": (s.opened_by_user.full_name or s.opened_by_user.username)
                if s.opened_by_user
                else None,
                "orders_count": orders[0],
                "revenue": int(orders[1] or 0),
            }
        )
    return out


# --------------------------------------------------------------------------
# board
# --------------------------------------------------------------------------
@router.get("/board", response_model=OccupancyBoard)
def occupancy_board(
    _: FloorReader, db: DbSession, hall_id: uuid.UUID | None = None
) -> OccupancyBoard:
    from app.api.hall import session_read

    tables = hall_service.list_tables(db, hall_id, active_only=True)
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

    halls = []
    for hall in hall_service.list_halls(db, active_only=True):
        payload = hall_service.hall_payload(db, hall)
        h = HallRead.model_validate(payload["hall"])
        h.tables_count = payload["tables_count"]
        h.seats_total = payload["seats_total"]
        halls.append(h)

    data = hall_service.summary(db)
    return OccupancyBoard(
        generated_at=datetime.now(UTC),
        summary=data,  # type: ignore[arg-type]
        halls=halls,
        tables=out,
        reservations_today=data.get("reservations_today", 0),
    )


@router.get("/summary")
def quick_summary(_: FloorReader, db: DbSession) -> dict:
    return hall_service.summary(db)


# --------------------------------------------------------------------------
# reservations
# --------------------------------------------------------------------------
@router.get("/reservations", response_model=list[ReservationRead])
def list_reservations(
    _: FloorReader,
    db: DbSession,
    day: str | None = Query(default=None, description="YYYY-MM-DD"),
    status_filter: str | None = Query(default=None, alias="status"),
) -> list[ReservationRead]:
    stmt = select(Reservation).options(selectinload(Reservation.table))
    if day:
        start = datetime.fromisoformat(f"{day}T00:00:00").replace(tzinfo=UTC)
        stmt = stmt.where(
            Reservation.reserved_at >= start, Reservation.reserved_at < start + timedelta(days=1)
        )
    if status_filter:
        stmt = stmt.where(Reservation.status == status_filter)
    rows = db.execute(stmt.order_by(Reservation.reserved_at)).scalars().unique()
    out = []
    for r in rows:
        obj = ReservationRead.model_validate(r)
        obj.table_name = r.table.name if r.table else None
        out.append(obj)
    return out


@router.post("/reservations", response_model=ReservationRead, status_code=status.HTTP_201_CREATED)
def create_reservation(
    payload: ReservationCreate, user: OrderEditor, db: DbSession
) -> ReservationRead:
    resv = Reservation(
        **payload.model_dump(), created_by_user_id=user.id
    )
    if resv.table_id is not None and db.get(Table, resv.table_id) is None:
        raise HTTPException(status_code=400, detail="Стол не найден")
    if resv.table_id is None:
        resv.table_id = _pick_free_table(db, resv.guests_count)
    db.add(resv)
    db.commit()
    db.refresh(resv)
    obj = ReservationRead.model_validate(resv)
    obj.table_name = resv.table.name if resv.table else None
    return obj


@router.patch("/reservations/{reservation_id}", response_model=ReservationRead)
def update_reservation(
    reservation_id: uuid.UUID, payload: ReservationUpdate, _: OrderEditor, db: DbSession
) -> ReservationRead:
    resv = db.get(Reservation, reservation_id)
    if resv is None:
        raise HTTPException(status_code=404, detail="Бронь не найдена")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(resv, field, value)
    db.commit()
    db.refresh(resv)
    obj = ReservationRead.model_validate(resv)
    obj.table_name = resv.table.name if resv.table else None
    return obj


@router.post("/reservations/{reservation_id}/seat")
def seat_from_reservation(
    reservation_id: uuid.UUID, user: OrderEditor, db: DbSession
) -> dict:
    """Guest arrived: mark the booking and seat them in one step."""
    resv = db.get(Reservation, reservation_id)
    if resv is None:
        raise HTTPException(status_code=404, detail="Бронь не найдена")
    if resv.table_id is None:
        resv.table_id = _pick_free_table(db, resv.guests_count)
    if resv.table_id is None:
        raise HTTPException(status_code=400, detail="Нет свободного стола")

    table = _load_table(db, resv.table_id)
    if hall_service.get_active_session(db, table.id):
        raise HTTPException(status_code=409, detail="Стол уже занят")

    session = TableSession(
        table_id=table.id,
        opened_by_user_id=user.id,
        guests_count=resv.guests_count,
        status=TableStatus.seated,
        started_at=datetime.now(UTC),
        guest_name=resv.guest_name,
    )
    resv.status = ReservationStatus.arrived
    db.add(session)
    db.flush()
    hall_service.log_event(
        db, table.id, "seated_from_reservation", session_id=session.id, user_id=user.id,
        guests_count=resv.guests_count,
    )
    db.commit()
    _event(db, table, user)
    return {"ok": True, "table": table.name, "session_id": str(session.id)}


@router.delete("/reservations/{reservation_id}")
def delete_reservation(reservation_id: uuid.UUID, _: OrderEditor, db: DbSession) -> dict:
    resv = db.get(Reservation, reservation_id)
    if resv is None:
        raise HTTPException(status_code=404, detail="Бронь не найдена")
    db.delete(resv)
    db.commit()
    return {"ok": True}


# --------------------------------------------------------------------------
# reports / day close
# --------------------------------------------------------------------------
@router.get("/report/daily", response_model=DailyReport)
def daily_report(
    _: Reporter, db: DbSession, business_date: str | None = Query(default=None)
) -> DailyReport:
    day = business_date or datetime.now(UTC).strftime("%Y-%m-%d")
    return _daily_report(db, day)


def _daily_report(db, day: str) -> DailyReport:
    start = datetime.fromisoformat(f"{day}T00:00:00").replace(tzinfo=UTC)
    end = start + timedelta(days=1)

    orders = list(
        db.execute(
            select(Order)
            .options(selectinload(Order.items))
            .where(
                Order.created_at >= start,
                Order.created_at < end,
                Order.status != "cancelled",
            )
        ).scalars().unique()
    )

    revenue = sum(int((o.total_amount or 0) * 100) for o in orders)
    guests = db.execute(
        select(func.coalesce(func.sum(TableSession.guests_count), 0)).where(
            TableSession.started_at >= start, TableSession.started_at < end
        )
    ).scalar()
    tables_used = db.execute(
        select(func.count(func.distinct(Order.table_id))).where(
            Order.created_at >= start, Order.created_at < end
        )
    ).scalar()

    by_source: dict[str, int] = {}
    for o in orders:
        by_source[o.source] = by_source.get(o.source, 0) + int((o.total_amount or 0) * 100)

    top: dict[str, dict] = {}
    for order in orders:
        for item in order.items:
            entry = top.setdefault(
                item.dish_name,
                {"name": item.dish_name, "qty": 0, "revenue": 0},
            )
            entry["qty"] += item.quantity
            entry["revenue"] += int(item.line_total * 100)
    top_dishes = sorted(top.values(), key=lambda x: -x["qty"])[:20]

    hourly: dict[int, dict] = {}
    for order in orders:
        created = order.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=UTC)
        hour = created.hour
        entry = hourly.setdefault(hour, {"hour": hour, "orders": 0, "revenue": 0})
        entry["orders"] += 1
        entry["revenue"] += int((order.total_amount or 0) * 100)
    hourly_load = [hourly[h] for h in sorted(hourly)]

    closed = db.execute(
        select(func.count(DayClose.id)).where(DayClose.business_date == day)
    ).scalar()

    return DailyReport(
        business_date=day,
        guests_total=int(guests or 0),
        orders_total=len(orders),
        revenue_total=revenue,
        avg_check=revenue // len(orders) if orders else 0,
        tables_used=int(tables_used or 0),
        by_source=by_source,
        top_dishes=top_dishes,
        hourly_load=hourly_load,
        closed=bool(closed),
    )


@router.post("/report/close-day")
def close_day(
    user: Reporter,
    db: DbSession,
    business_date: str | None = Query(default=None),
) -> dict:
    day = business_date or datetime.now(UTC).strftime("%Y-%m-%d")
    report = _daily_report(db, day)
    close = db.execute(
        select(DayClose).where(DayClose.business_date == day)
    ).scalar_one_or_none()
    if close is None:
        close = DayClose(business_date=day, closed_by_user_id=user.id)
        db.add(close)
    close.guests_total = report.guests_total
    close.orders_total = report.orders_total
    close.revenue_total = report.revenue_total / 100
    close.closed_at = datetime.now(UTC)
    db.commit()
    return {"ok": True, "business_date": day, **report.model_dump()}


@router.get("/report/staff")
def staff_load(
    _: Reporter, db: DbSession, business_date: str | None = Query(default=None)
) -> list[dict]:
    day = business_date or datetime.now(UTC).strftime("%Y-%m-%d")
    start = datetime.fromisoformat(f"{day}T00:00:00").replace(tzinfo=UTC)
    end = start + timedelta(days=1)

    rows = db.execute(
        select(
            User.id,
            User.username,
            User.full_name,
            func.count(Order.id),
            func.coalesce(func.sum(Order.total_amount), 0),
        )
        .join(Order, Order.created_by_user_id == User.id)
        .where(Order.created_at >= start, Order.created_at < end)
        .group_by(User.id, User.username, User.full_name)
    ).all()
    return [
        {
            "user_id": str(r[0]),
            "username": r[1],
            "full_name": r[2],
            "orders": r[3],
            "revenue": int((r[4] or 0) * 100),
        }
        for r in rows
    ]
