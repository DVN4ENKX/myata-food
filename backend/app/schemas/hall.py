from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.db.base import ReservationStatus, TableShape, TableStatus


class ORMBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --------------------------------------------------------------------------
# halls
# --------------------------------------------------------------------------
class HallBase(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = ""
    layout_width: int = Field(default=1200, ge=200, le=10000)
    layout_height: int = Field(default=800, ge=200, le=10000)
    sort_order: int = 0
    is_active: bool = True


class HallCreate(HallBase):
    pass


class HallUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    layout_width: int | None = Field(default=None, ge=200, le=10000)
    layout_height: int | None = Field(default=None, ge=200, le=10000)
    sort_order: int | None = None
    is_active: bool | None = None


class HallRead(ORMBase, HallBase):
    id: uuid.UUID
    tables_count: int = 0
    seats_total: int = 0


# --------------------------------------------------------------------------
# tables
# --------------------------------------------------------------------------
class TableBase(BaseModel):
    hall_id: uuid.UUID
    name: str = Field(min_length=1, max_length=60)
    seats: int = Field(default=2, ge=1, le=100)
    shape: TableShape = TableShape.rect
    x: int = Field(default=40, ge=0, le=20000)
    y: int = Field(default=40, ge=0, le=20000)
    width: int = Field(default=110, ge=20, le=5000)
    height: int = Field(default=80, ge=20, le=5000)
    rotation: int = Field(default=0, ge=-360, le=360)
    color: str | None = None
    sort_order: int = 0
    is_active: bool = True
    note: str = ""
    external_id: str | None = None


class TableCreate(TableBase):
    pass


class TableUpdate(BaseModel):
    hall_id: uuid.UUID | None = None
    name: str | None = Field(default=None, min_length=1, max_length=60)
    seats: int | None = Field(default=None, ge=1, le=100)
    shape: TableShape | None = None
    x: int | None = Field(default=None, ge=0, le=20000)
    y: int | None = Field(default=None, ge=0, le=20000)
    width: int | None = Field(default=None, ge=20, le=5000)
    height: int | None = Field(default=None, ge=20, le=5000)
    rotation: int | None = Field(default=None, ge=-360, le=360)
    color: str | None = None
    sort_order: int | None = None
    is_active: bool | None = None
    note: str | None = None
    external_id: str | None = None


class TableSessionRead(ORMBase):
    id: uuid.UUID
    table_id: uuid.UUID
    guests_count: int
    status: str
    started_at: datetime
    ended_at: datetime | None = None
    wait_minutes: int = 0
    comment: str = ""
    guest_name: str = ""
    opened_by: str | None = None


class TableRead(ORMBase, TableBase):
    id: uuid.UUID
    qr_token: str
    qr_url: str = ""
    status: TableStatus = TableStatus.free
    current_session: TableSessionRead | None = None
    seated_since: datetime | None = None
    open_orders: int = 0
    order_total: int = 0
    next_reservation_at: datetime | None = None


class LayoutSave(BaseModel):
    """Bulk save of table positions after dragging them on the canvas."""

    tables: list[LayoutItem] = Field(min_length=1, max_length=500)


class LayoutItem(BaseModel):
    id: uuid.UUID
    x: int = Field(ge=0, le=20000)
    y: int = Field(ge=0, le=20000)
    width: int = Field(default=110, ge=20, le=5000)
    height: int = Field(default=80, ge=20, le=5000)
    rotation: int = Field(default=0, ge=-360, le=360)
    shape: TableShape | None = None


# --------------------------------------------------------------------------
# occupancy
# --------------------------------------------------------------------------
class SeatRequest(BaseModel):
    guests_count: int = Field(default=1, ge=1, le=100)
    guest_name: str = Field(default="", max_length=150)
    comment: str = ""
    wait_minutes: int = Field(default=0, ge=0, le=1440)
    open_order_id: uuid.UUID | None = None


class CloseTableRequest(BaseModel):
    comment: str = ""
    clear_tables: bool = True


class SessionUpdate(BaseModel):
    guests_count: int | None = Field(default=None, ge=1, le=100)
    guest_name: str | None = Field(default=None, max_length=150)
    comment: str | None = None
    status: TableStatus | None = None


class OccupancySummary(BaseModel):
    tables_total: int
    tables_busy: int
    tables_free: int
    tables_reserved: int
    tables_cleaning: int
    seats_total: int
    guests_now: int
    occupancy_percent: int
    revenue_today: int
    orders_today: int
    active_sessions: int


class OccupancyBoard(BaseModel):
    generated_at: datetime
    summary: OccupancySummary
    halls: list[HallRead]
    tables: list[TableRead]
    reservations_today: int


# --------------------------------------------------------------------------
# reservations
# --------------------------------------------------------------------------
class ReservationBase(BaseModel):
    table_id: uuid.UUID | None = None
    guest_name: str = Field(min_length=1, max_length=150)
    phone: str = Field(default="", max_length=40)
    guests_count: int = Field(default=2, ge=1, le=100)
    reserved_at: datetime
    duration_minutes: int = Field(default=120, ge=15, le=1440)
    status: ReservationStatus = ReservationStatus.planned
    comment: str = ""


class ReservationCreate(ReservationBase):
    pass


class ReservationUpdate(BaseModel):
    table_id: uuid.UUID | None = None
    guest_name: str | None = Field(default=None, min_length=1, max_length=150)
    phone: str | None = Field(default=None, max_length=40)
    guests_count: int | None = Field(default=None, ge=1, le=100)
    reserved_at: datetime | None = None
    duration_minutes: int | None = Field(default=None, ge=15, le=1440)
    status: ReservationStatus | None = None
    comment: str | None = None


class ReservationRead(ORMBase, ReservationBase):
    id: uuid.UUID
    table_name: str | None = None
    created_at: datetime | None = None


# --------------------------------------------------------------------------
# reports
# --------------------------------------------------------------------------
class DailyReport(BaseModel):
    business_date: str
    guests_total: int
    orders_total: int
    revenue_total: int
    avg_check: int
    tables_used: int
    by_source: dict[str, int] = {}
    top_dishes: list[dict] = []
    hourly_load: list[dict] = []
    closed: bool = False
