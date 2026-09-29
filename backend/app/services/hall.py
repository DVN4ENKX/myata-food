from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.db.base import OrderStatus, TableStatus
from app.models.hall import (
    Hall,
    OccupancyEvent,
    Reservation,
    Table,
    TableSession,
)
from app.models.order import Order

ACTIVE_ORDER_STATUSES = (
    OrderStatus.new,
    OrderStatus.in_progress,
    OrderStatus.ready,
    OrderStatus.served,
)


def day_bounds(moment: datetime | None = None) -> tuple[datetime, datetime]:
    moment = moment or datetime.now(UTC)
    start = moment.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=1)


def get_active_session(db: Session, table_id: uuid.UUID) -> TableSession | None:
    return db.execute(
        select(TableSession)
        .where(TableSession.table_id == table_id, TableSession.ended_at.is_(None))
        .order_by(TableSession.started_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def _open_order_stats(db: Session, table_ids: list[uuid.UUID]) -> dict[uuid.UUID, tuple[int, int]]:
    """table_id -> (open order count, open order total in kopecks)"""
    if not table_ids:
        return {}
    stmt = (
        select(
            Order.table_id,
            func.count(Order.id),
            func.coalesce(func.sum(Order.total_amount), 0),
        )
        .where(
            Order.table_id.in_(table_ids),
            Order.status.in_(ACTIVE_ORDER_STATUSES),
        )
        .group_by(Order.table_id)
    )
    return {row[0]: (row[1], int(row[2])) for row in db.execute(stmt)}


def _next_reservations(db: Session, table_ids: list[uuid.UUID]) -> dict[uuid.UUID, datetime]:
    if not table_ids:
        return {}
    now = datetime.now(UTC)
    stmt = (
        select(Reservation.table_id, func.min(Reservation.reserved_at))
        .where(
            Reservation.table_id.in_(table_ids),
            Reservation.status == "planned",
            Reservation.reserved_at >= now,
        )
        .group_by(Reservation.table_id)
    )
    return {row[0]: row[1] for row in db.execute(stmt)}


def table_status(db: Session, table: Table, now: datetime | None = None) -> TableStatus:
    now = now or datetime.now(UTC)
    session = get_active_session(db, table.id)
    if session:
        return TableStatus(session.status)
    resv = db.execute(
        select(func.count(Reservation.id)).where(
            Reservation.table_id == table.id,
            Reservation.status == "planned",
            Reservation.reserved_at <= now + timedelta(hours=1),
            Reservation.reserved_at >= now - timedelta(hours=1),
        )
    ).scalar()
    return TableStatus.reserved if resv else TableStatus.free


def list_tables(db: Session, hall_id: uuid.UUID | None = None, active_only: bool = True) -> list[Table]:
    stmt = select(Table).options(selectinload(Table.hall))
    if hall_id:
        stmt = stmt.where(Table.hall_id == hall_id)
    if active_only:
        stmt = stmt.where(Table.is_active.is_(True))
    stmt = stmt.order_by(Table.sort_order, Table.name)
    return list(db.execute(stmt).scalars().unique())


def table_payloads(db: Session, tables: list[Table], now: datetime | None = None) -> list[dict]:
    from app.services.qr import build_menu_url

    now = now or datetime.now(UTC)
    table_ids = [t.id for t in tables]
    orders = _open_order_stats(db, table_ids)
    resv = _next_reservations(db, table_ids)

    sessions: dict[uuid.UUID, TableSession] = {}
    if table_ids:
        rows = db.execute(
            select(TableSession).where(
                TableSession.table_id.in_(table_ids), TableSession.ended_at.is_(None)
            )
        ).scalars()
        for s in rows:
            sessions.setdefault(s.table_id, s)

    out: list[dict] = []
    for t in tables:
        session = sessions.get(t.id)
        status = TableStatus(session.status) if session else table_status(db, t, now)
        open_count, open_total = orders.get(t.id, (0, 0))
        out.append(
            {
                "table": t,
                "hall_name": t.hall.name if t.hall else "",
                "qr_url": build_menu_url(t.qr_token),
                "status": status,
                "current_session": session,
                "open_orders": open_count,
                "order_total": open_total,
                "next_reservation_at": resv.get(t.id),
            }
        )
    return out


def summary(db: Session, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    start, end = day_bounds(now)

    tables = list(db.execute(select(Table).where(Table.is_active.is_(True))).scalars().unique())
    payloads = table_payloads(db, tables, now)

    busy = free = reserved = cleaning = 0
    guests = 0
    seats_total = 0
    for row in payloads:
        seats_total += row["table"].seats
        status = row["status"]
        if status == TableStatus.seated:
            busy += 1
            guests += row["current_session"].guests_count if row["current_session"] else 0
        elif status == TableStatus.reserved:
            reserved += 1
        elif status == TableStatus.cleaning:
            cleaning += 1
        else:
            free += 1

    revenue = db.execute(
        select(func.coalesce(func.sum(Order.total_amount), 0)).where(
            Order.created_at >= start, Order.created_at < end
        )
    ).scalar()
    orders_today = db.execute(
        select(func.count(Order.id)).where(Order.created_at >= start, Order.created_at < end)
    ).scalar()
    reservations_today = db.execute(
        select(func.count(Reservation.id)).where(
            Reservation.reserved_at >= start, Reservation.reserved_at < end
        )
    ).scalar()

    total = len(tables)
    percent = round((busy / total) * 100) if total else 0

    return {
        "tables_total": total,
        "tables_busy": busy,
        "tables_free": free,
        "tables_reserved": reserved,
        "tables_cleaning": cleaning,
        "seats_total": seats_total,
        "guests_now": guests,
        "occupancy_percent": percent,
        "revenue_today": int(revenue or 0),
        "orders_today": int(orders_today or 0),
        "active_sessions": busy,
        "reservations_today": int(reservations_today or 0),
    }


def log_event(
    db: Session,
    table_id: uuid.UUID,
    action: str,
    *,
    session_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    guests_count: int = 0,
) -> None:
    db.add(
        OccupancyEvent(
            table_id=table_id,
            session_id=session_id,
            user_id=user_id,
            action=action,
            guests_count=guests_count,
        )
    )


def list_halls(db: Session, active_only: bool = True) -> list[Hall]:
    stmt = select(Hall).options(selectinload(Hall.tables))
    if active_only:
        stmt = stmt.where(Hall.is_active.is_(True))
    stmt = stmt.order_by(Hall.sort_order, Hall.name)
    return list(db.execute(stmt).scalars().unique())


def hall_payload(db: Session, hall: Hall) -> dict:
    tables = [t for t in hall.tables if t.is_active]
    return {
        "hall": hall,
        "tables_count": len(tables),
        "seats_total": sum(t.seats for t in tables),
    }
