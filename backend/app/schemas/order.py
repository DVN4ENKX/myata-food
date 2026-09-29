from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, field_validator

from app.db.base import OrderSource, OrderStatus

# money leaves the API as a JSON number, not "390.00"
Money = Annotated[Decimal, PlainSerializer(float, return_type=float, when_used="json")]


class ORMBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class CartModifier(BaseModel):
    """Only the id is trusted: name/price are recomputed server-side."""

    modifier_id: uuid.UUID
    name: str = Field(default="", max_length=120)
    price_delta: int = 0


class CartItem(BaseModel):
    dish_id: uuid.UUID
    quantity: int = Field(default=1, ge=1, le=99)
    comment: str = Field(default="", max_length=500)
    modifiers: list[CartModifier] = Field(default_factory=list)

    @field_validator("modifiers")
    @classmethod
    def _limit_modifiers(cls, v: list[CartModifier]) -> list[CartModifier]:
        if len(v) > 20:
            raise ValueError("Слишком много модификаторов")
        return v


class GuestCartRequest(BaseModel):
    """Sent from the QR menu. Prices are recomputed server-side."""

    items: list[CartItem] = Field(min_length=1, max_length=100)
    guest_comment: str = Field(default="", max_length=1000)
    guests_count: int = Field(default=1, ge=1, le=100)


class OrderItemModifierRead(ORMBase):
    id: uuid.UUID
    modifier_id: uuid.UUID | None = None
    name: str
    price_delta: Money


class OrderItemRead(ORMBase):
    id: uuid.UUID
    dish_id: uuid.UUID | None = None
    dish_name: str
    price: Money
    quantity: int
    comment: str
    cooking_minutes: int = 0
    status: str
    modifiers: list[OrderItemModifierRead] = []
    line_total: Money = Decimal(0)


class OrderBase(BaseModel):
    table_id: uuid.UUID | None = None
    status: OrderStatus = OrderStatus.new
    source: OrderSource = OrderSource.hall
    guests_count: int = Field(default=1, ge=1, le=100)
    guest_comment: str = Field(default="", max_length=1000)
    client_name: str = Field(default="", max_length=150)


class OrderCreate(OrderBase):
    items: list[CartItem] = Field(min_length=1, max_length=100)


class OrderUpdate(BaseModel):
    table_id: uuid.UUID | None = None
    status: OrderStatus | None = None
    guests_count: int | None = Field(default=None, ge=1, le=100)
    guest_comment: str | None = Field(default=None, max_length=1000)
    client_name: str | None = Field(default=None, max_length=150)


class OrderRead(ORMBase):
    id: uuid.UUID
    order_number: str
    table_id: uuid.UUID | None = None
    table_name: str | None = None
    table_session_id: uuid.UUID | None = None
    status: OrderStatus
    source: OrderSource
    guests_count: int
    guest_comment: str
    client_name: str
    total_amount: Money
    total_discount: Money
    external_id: str | None = None
    exported_to_1c: bool = False
    created_at: datetime
    closed_at: datetime | None = None
    items: list[OrderItemRead] = []


class OrderItemAdd(BaseModel):
    dish_id: uuid.UUID
    quantity: int = Field(default=1, ge=1, le=99)
    comment: str = Field(default="", max_length=500)
    modifiers: list[CartModifier] = Field(default_factory=list)


class OrderStatusChange(BaseModel):
    status: OrderStatus
    note: str = ""


class KitchenBoard(BaseModel):
    orders: list[OrderRead]
    max_wait_minutes: int


class SettingsWrite(BaseModel):
    values: dict[str, str]
