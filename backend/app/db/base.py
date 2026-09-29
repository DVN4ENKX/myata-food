from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base for every ORM model."""


class BaseHelpers:
    """Column default factories shared by the models."""

    @staticmethod
    def new_id() -> uuid.UUID:
        return uuid.uuid4()

    @staticmethod
    def utcnow() -> datetime:
        return datetime.now(UTC)


class Role(StrEnum):
    owner = "owner"
    admin = "admin"
    manager = "manager"
    waiter = "waiter"


class DishKind(StrEnum):
    dish = "dish"
    combo = "combo"


class TableShape(StrEnum):
    round = "round"
    square = "square"
    rect = "rect"


class TableStatus(StrEnum):
    free = "free"
    seated = "seated"
    reserved = "reserved"
    cleaning = "cleaning"


class OrderStatus(StrEnum):
    new = "new"
    in_progress = "in_progress"
    ready = "ready"
    served = "served"
    closed = "closed"
    cancelled = "cancelled"


class OrderSource(StrEnum):
    qr = "qr"
    hall = "hall"
    waiter = "waiter"


class ReservationStatus(StrEnum):
    planned = "planned"
    arrived = "arrived"
    cancelled = "cancelled"
    no_show = "no_show"


class SyncDirection(StrEnum):
    export = "export"
    import_ = "import"


class SyncStatus(StrEnum):
    pending = "pending"
    success = "success"
    error = "error"
