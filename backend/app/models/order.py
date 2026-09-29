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
    from app.models.hall import Table
    from app.models.user import User


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=BaseHelpers.new_id)
    order_number: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    table_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tables.id", ondelete="SET NULL"), default=None, index=True
    )
    table_session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("table_sessions.id", ondelete="SET NULL"), default=None, index=True
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )

    status: Mapped[str] = mapped_column(String(20), default="new", index=True)
    source: Mapped[str] = mapped_column(String(20), default="qr")

    guests_count: Mapped[int] = mapped_column(Integer, default=1)
    guest_comment: Mapped[str] = mapped_column(Text, default="")
    client_name: Mapped[str] = mapped_column(String(150), default="")

    total_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    total_discount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)

    # 1C:UNF linkage: filled after the document is imported by 1C
    external_id: Mapped[str | None] = mapped_column(String(64), default=None, index=True)
    exported_to_1c: Mapped[bool] = mapped_column(Boolean, default=False)

    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    items: Mapped[list[OrderItem]] = relationship(
        back_populates="order", cascade="all, delete-orphan", order_by="OrderItem.created_at"
    )
    table: Mapped[Table | None] = relationship()
    created_by_user: Mapped[User | None] = relationship(back_populates="orders")

    @property
    def pays_total(self) -> Decimal:
        return (self.total_amount or Decimal(0)) - (self.total_discount or Decimal(0))


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=BaseHelpers.new_id)
    order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), index=True
    )
    dish_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("dishes.id", ondelete="SET NULL"), default=None, index=True
    )

    # snapshot so historic orders survive menu edits
    dish_name: Mapped[str] = mapped_column(String(200))
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    comment: Mapped[str] = mapped_column(Text, default="")

    cooking_minutes: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="new")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    order: Mapped[Order] = relationship(back_populates="items")
    modifiers: Mapped[list[OrderItemModifier]] = relationship(
        back_populates="item", cascade="all, delete-orphan"
    )

    @property
    def line_total(self) -> Decimal:
        # modifiers apply per unit, matching recalc_total() and order_read();
        # counting them once per line made staff-report revenue disagree with
        # the order total as soon as a modifier was used with quantity > 1
        extra = sum((m.price_delta for m in self.modifiers), Decimal(0))
        return (self.price + extra) * self.quantity


class OrderItemModifier(Base):
    __tablename__ = "order_item_modifiers"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=BaseHelpers.new_id)
    order_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("order_items.id", ondelete="CASCADE"), index=True
    )
    modifier_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("modifiers.id", ondelete="SET NULL"), default=None
    )
    name: Mapped[str] = mapped_column(String(120))
    price_delta: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)

    item: Mapped[OrderItem] = relationship(back_populates="modifiers")
