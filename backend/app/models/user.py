from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, BaseHelpers

if TYPE_CHECKING:
    from app.models.hall import TableSession
    from app.models.order import Order


class User(Base):
    """Staff member / manager account."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=BaseHelpers.new_id)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(150), default="")
    email: Mapped[str | None] = mapped_column(String(200), default=None)
    phone: Mapped[str | None] = mapped_column(String(40), default=None)

    hashed_password: Mapped[str] = mapped_column(String(255))
    # Short PIN for fast terminal login by waiters (optional).
    pin_hash: Mapped[str | None] = mapped_column(String(255), default=None)

    role: Mapped[str] = mapped_column(String(20), default="waiter", index=True)
    permissions: Mapped[str] = mapped_column(Text, default="{}")

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    can_manage_menu: Mapped[bool] = mapped_column(Boolean, default=False)
    can_manage_hall: Mapped[bool] = mapped_column(Boolean, default=False)
    can_manage_orders: Mapped[bool] = mapped_column(Boolean, default=False)
    can_manage_users: Mapped[bool] = mapped_column(Boolean, default=False)
    can_view_reports: Mapped[bool] = mapped_column(Boolean, default=False)

    salary_percent: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[str | None] = mapped_column(Text, default=None)

    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    sessions: Mapped[list[TableSession]] = relationship(back_populates="opened_by_user")
    orders: Mapped[list[Order]] = relationship(back_populates="created_by_user")

    @property
    def perms(self) -> dict:
        import json

        try:
            return json.loads(self.permissions or "{}")
        except ValueError:
            return {}


class AuditLog(Base):
    """Who changed what - useful for menu/pricing accountability."""

    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=BaseHelpers.new_id)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None, index=True
    )
    user_name: Mapped[str] = mapped_column(String(150), default="")
    action: Mapped[str] = mapped_column(String(80), index=True)
    entity_type: Mapped[str] = mapped_column(String(50), default="")
    entity_id: Mapped[str | None] = mapped_column(String(64), default=None)
    payload: Mapped[str] = mapped_column(Text, default="{}")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AppSetting(Base):
    """Key/value store for venue-wide settings (name, wifi password, ...)."""

    __tablename__ = "app_settings"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=BaseHelpers.new_id)
    key: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
