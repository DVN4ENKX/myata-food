from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.db.base import SyncStatus


class ORMBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class IntegrationSettingRead(ORMBase):
    id: uuid.UUID
    enabled: bool
    exchange_plan: str
    endpoint_url: str
    login: str
    password_masked: str = ""
    org_ref: str
    price_type_ref: str
    auto_export_interval_minutes: int
    export_categories: bool
    export_dishes: bool
    export_modifiers: bool
    export_orders: bool
    export_day_closes: bool
    last_export_at: datetime | None = None
    last_import_at: datetime | None = None


class IntegrationSettingUpdate(BaseModel):
    enabled: bool | None = None
    exchange_plan: str | None = Field(default=None, max_length=120)
    endpoint_url: str | None = Field(default=None, max_length=500)
    login: str | None = Field(default=None, max_length=120)
    password: str | None = Field(default=None, max_length=255)
    org_ref: str | None = Field(default=None, max_length=64)
    price_type_ref: str | None = Field(default=None, max_length=64)
    auto_export_interval_minutes: int | None = Field(default=None, ge=0, le=1440)
    export_categories: bool | None = None
    export_dishes: bool | None = None
    export_modifiers: bool | None = None
    export_orders: bool | None = None
    export_day_closes: bool | None = None


class IntegrationLogRead(ORMBase):
    id: uuid.UUID
    direction: str
    status: SyncStatus
    file_name: str | None = None
    entities_total: int
    entities_success: int
    entities_error: int
    message: str
    started_at: datetime
    finished_at: datetime | None = None


class ExportRequest(BaseModel):
    """Choose what to put into the 1C exchange message."""

    categories: bool = True
    dishes: bool = True
    modifiers: bool = True
    orders: bool = False
    day_closes: bool = False
    order_status: list[str] = ["new", "in_progress", "ready", "served", "closed"]
    since: datetime | None = None
    deliver: bool = False  # POST straight to the 1C web service


class ExportResult(BaseModel):
    log_id: uuid.UUID
    file_name: str
    entities_total: int
    entities_success: int
    entities_error: int
    status: SyncStatus
    message: str
    download_url: str | None = None


class OneCPush(BaseModel):
    """Reference data sent from 1C into the app (e.g. updated dish prices)."""

    items: list[dict] = Field(min_length=1, max_length=1000)


class OneCPushResult(BaseModel):
    accepted: int
    updated: int
    created: int
    errors: list[str] = []
