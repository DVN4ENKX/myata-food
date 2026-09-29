from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, BaseHelpers

if TYPE_CHECKING:
    from app.models.user import User


class Hall(Base):
    """A room / area of the venue with its own layout canvas."""

    __tablename__ = "halls"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=BaseHelpers.new_id)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, default="")

    # Layout canvas size in arbitrary units; tables store relative coords.
    layout_width: Mapped[int] = mapped_column(Integer, default=1200)
    layout_height: Mapped[int] = mapped_column(Integer, default=800)

    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    tables: Mapped[list[Table]] = relationship(
        back_populates="hall", cascade="all, delete-orphan", order_by="Table.sort_order"
    )


class Table(Base):
    __tablename__ = "tables"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=BaseHelpers.new_id)
    hall_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("halls.id", ondelete="CASCADE"), index=True
    )

    name: Mapped[str] = mapped_column(String(60), index=True)
    seats: Mapped[int] = mapped_column(Integer, default=2)
    shape: Mapped[str] = mapped_column(String(20), default="rect")

    # --- layout (absolute units inside hall canvas) ---
    x: Mapped[int] = mapped_column(Integer, default=40)
    y: Mapped[int] = mapped_column(Integer, default=40)
    width: Mapped[int] = mapped_column(Integer, default=110)
    height: Mapped[int] = mapped_column(Integer, default=80)
    rotation: Mapped[int] = mapped_column(Integer, default=0)
    color: Mapped[str | None] = mapped_column(String(20), default=None)

    # --- QR ---
    qr_token: Mapped[str] = mapped_column(String(48), unique=True, index=True)
    qr_regenerated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )

    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    note: Mapped[str] = mapped_column(Text, default="")

    # 1C:UNF linkage
    external_id: Mapped[str | None] = mapped_column(String(64), default=None, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    hall: Mapped[Hall] = relationship(back_populates="tables")
    sessions: Mapped[list[TableSession]] = relationship(
        back_populates="table", cascade="all, delete-orphan", order_by="TableSession.started_at"
    )


class TableSession(Base):
    """One sitting: table occupied from started_at until ended_at."""

    __tablename__ = "table_sessions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=BaseHelpers.new_id)
    table_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tables.id", ondelete="CASCADE"), index=True
    )
    opened_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )

    guests_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="seated", index=True)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=BaseHelpers.utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    # wait duration to be seated
    wait_minutes: Mapped[int] = mapped_column(Integer, default=0)
    comment: Mapped[str] = mapped_column(Text, default="")
    guest_name: Mapped[str] = mapped_column(String(150), default="")

    table: Mapped[Table] = relationship(back_populates="sessions")
    opened_by_user: Mapped[User | None] = relationship(back_populates="sessions")


class Reservation(Base):
    __tablename__ = "reservations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=BaseHelpers.new_id)
    table_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tables.id", ondelete="SET NULL"), default=None, index=True
    )

    guest_name: Mapped[str] = mapped_column(String(150))
    phone: Mapped[str] = mapped_column(String(40), default="")
    guests_count: Mapped[int] = mapped_column(Integer, default=2)
    reserved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    duration_minutes: Mapped[int] = mapped_column(Integer, default=120)

    status: Mapped[str] = mapped_column(String(20), default="planned", index=True)
    comment: Mapped[str] = mapped_column(Text, default="")
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    table: Mapped[Table | None] = relationship()


class OccupancyEvent(Base):
    """Audit trail of table state changes, powers the reports screen."""

    __tablename__ = "occupancy_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=BaseHelpers.new_id)
    table_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tables.id", ondelete="CASCADE"), index=True
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("table_sessions.id", ondelete="SET NULL"), default=None
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    action: Mapped[str] = mapped_column(String(40))
    guests_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DayClose(Base):
    """Z-report style daily summary, ready to be pushed to 1C."""

    __tablename__ = "day_closes"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=BaseHelpers.new_id)
    business_date: Mapped[str] = mapped_column(String(10), unique=True, index=True)
    closed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )

    guests_total: Mapped[int] = mapped_column(Integer, default=0)
    orders_total: Mapped[int] = mapped_column(Integer, default=0)
    revenue_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    closed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=BaseHelpers.utcnow)
    exported_to_1c: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str] = mapped_column(Text, default="")
