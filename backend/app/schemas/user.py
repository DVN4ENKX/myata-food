from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.db.base import Role

Username = Annotated[str, Field(min_length=2, max_length=64, pattern=r"^[A-Za-z0-9_.\-]+$")]


class ORMBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class LoginRequest(BaseModel):
    """Staff sign-in. Either a password or a 4-6 digit PIN works."""

    username: str
    password: str = Field(default="", max_length=200)
    pin: str | None = Field(default=None, max_length=12)


class UserBase(BaseModel):
    username: Username | None = None
    full_name: str = Field(default="", max_length=150)
    email: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=40)
    role: Role = Role.waiter
    is_active: bool = True
    can_manage_menu: bool = False
    can_manage_hall: bool = False
    can_manage_orders: bool = False
    can_manage_users: bool = False
    can_view_reports: bool = True
    salary_percent: int = Field(default=0, ge=0, le=100)
    notes: str = ""

    @field_validator("email")
    @classmethod
    def _check_email(cls, v: str | None) -> str | None:
        if v and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", v):
            raise ValueError("Некорректный email")
        return v

    @field_validator("notes", mode="before")
    @classmethod
    def _coerce_notes(cls, v: object) -> str:
        return "" if v is None else str(v)


class UserCreate(UserBase):
    # None = "take the default for the role", so creating a manager does not
    # silently hand out owner-level rights
    password: str = Field(min_length=4, max_length=200)
    pin: str | None = Field(default=None, min_length=4, max_length=12)
    can_manage_menu: bool | None = None
    can_manage_hall: bool | None = None
    can_manage_orders: bool | None = None
    can_manage_users: bool | None = None
    can_view_reports: bool | None = None


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, max_length=150)
    email: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=40)
    role: Role | None = None
    is_active: bool | None = None
    can_manage_menu: bool | None = None
    can_manage_hall: bool | None = None
    can_manage_orders: bool | None = None
    can_manage_users: bool | None = None
    can_view_reports: bool | None = None
    salary_percent: int | None = Field(default=None, ge=0, le=100)
    notes: str | None = None
    password: str | None = Field(default=None, min_length=4, max_length=200)
    pin: str | None = Field(default=None, min_length=4, max_length=12)


class UserRead(ORMBase, UserBase):
    id: uuid.UUID
    username: Username
    last_login_at: datetime | None = None
    created_at: datetime | None = None


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserRead


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=4, max_length=128)


class PinReset(BaseModel):
    pin: str = Field(min_length=4, max_length=12)
