from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, BaseHelpers


class IntegrationSetting(Base):
    """Connection settings for 1C:UNF (exchange plan / web service)."""

    __tablename__ = "integration_settings"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=BaseHelpers.new_id)

    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    exchange_plan: Mapped[str] = mapped_column(String(120), default="ОбменСФерикой")
    endpoint_url: Mapped[str] = mapped_column(String(500), default="")
    login: Mapped[str] = mapped_column(String(120), default="")
    password: Mapped[str] = mapped_column(String(255), default="")
    # Organisation in 1C:UNF that owns the catalogue
    org_ref: Mapped[str] = mapped_column(String(64), default="")
    # Price type / вид цен to export into
    price_type_ref: Mapped[str] = mapped_column(String(64), default="")

    auto_export_interval_minutes: Mapped[int] = mapped_column(Integer, default=0)
    export_categories: Mapped[bool] = mapped_column(Boolean, default=True)
    export_dishes: Mapped[bool] = mapped_column(Boolean, default=True)
    export_modifiers: Mapped[bool] = mapped_column(Boolean, default=True)
    export_orders: Mapped[bool] = mapped_column(Boolean, default=True)
    export_day_closes: Mapped[bool] = mapped_column(Boolean, default=True)

    last_export_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    last_import_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SyncMap(Base):
    """Local entity <-> 1C reference key. The backbone of the exchange."""

    __tablename__ = "sync_map"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=BaseHelpers.new_id)
    entity_type: Mapped[str] = mapped_column(String(40), index=True)
    local_id: Mapped[str] = mapped_column(String(64), index=True)
    external_id: Mapped[str] = mapped_column(String(64), index=True)

    last_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    content_hash: Mapped[str | None] = mapped_column(String(64), default=None)

    __table_args__ = (
        # one 1C ref per local object, and one local object per ref
        UniqueConstraint("entity_type", "local_id", name="uq_sync_map_entity_local"),
        UniqueConstraint("entity_type", "external_id", name="uq_sync_map_entity_external"),
    )


class IntegrationLog(Base):
    __tablename__ = "integration_logs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=BaseHelpers.new_id)
    direction: Mapped[str] = mapped_column(String(20), default="export")
    status: Mapped[str] = mapped_column(String(20), default="pending")
    file_name: Mapped[str | None] = mapped_column(String(255), default=None)
    entities_total: Mapped[int] = mapped_column(Integer, default=0)
    entities_success: Mapped[int] = mapped_column(Integer, default=0)
    entities_error: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str] = mapped_column(Text, default="")
    payload_preview: Mapped[str] = mapped_column(Text, default="")

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=BaseHelpers.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )


class OneCReference(Base):
    """Raw payload received from 1C awaiting processing."""

    __tablename__ = "onec_inbox"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=BaseHelpers.new_id)
    entity_type: Mapped[str] = mapped_column(String(40), default="", index=True)
    external_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    action: Mapped[str] = mapped_column(String(20), default="update")

    name: Mapped[str] = mapped_column(String(200), default="")
    price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), default=None)
    payload: Mapped[str] = mapped_column(Text, default="{}")

    processed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=BaseHelpers.utcnow)
