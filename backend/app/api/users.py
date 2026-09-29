from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.api.auth import PERMISSION_DEFAULTS
from app.api.deps import DbSession, Reporter, UserAdmin
from app.core.security import hash_password
from app.db.base import Role
from app.models.user import AuditLog, User
from app.schemas.user import PinReset, UserCreate, UserRead, UserUpdate

router = APIRouter(prefix="/admin/users", tags=["admin:users"])


def _audit(db, user: User, action: str, entity_type: str, entity_id: str, payload: dict) -> None:
    import json

    db.add(
        AuditLog(
            user_id=user.id,
            user_name=user.full_name or user.username,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            payload=json.dumps(payload, ensure_ascii=False, default=str),
        )
    )


@router.get("", response_model=list[UserRead])
def list_users(_: UserAdmin, db: DbSession, include_inactive: bool = True) -> list[UserRead]:
    stmt = select(User)
    if not include_inactive:
        stmt = stmt.where(User.is_active.is_(True))
    rows = db.execute(stmt.order_by(User.role, User.username)).scalars().unique()
    return [UserRead.model_validate(u) for u in rows]


@router.get("/permissions")
def permission_matrix(_: UserAdmin) -> dict:
    return {
        "roles": {role.value: perms for role, perms in PERMISSION_DEFAULTS.items()},
        "flags": [
            {"key": "can_manage_menu", "label": "Меню и блюда"},
            {"key": "can_manage_hall", "label": "Схема зала, столы, QR"},
            {"key": "can_manage_orders", "label": "Заказы и посадка гостей"},
            {"key": "can_manage_users", "label": "Сотрудники и доступы"},
            {"key": "can_view_reports", "label": "Отчёты и статистика"},
        ],
    }


@router.get("/audit")
def audit_log(
    _: Reporter, db: DbSession, limit: int = Query(100, ge=1, le=500)
) -> list[dict]:
    rows = db.execute(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)).scalars()
    return [
        {
            "id": str(r.id),
            "user": r.user_name,
            "action": r.action,
            "entity_type": r.entity_type,
            "entity_id": r.entity_id,
            "created_at": r.created_at,
        }
        for r in rows
    ]


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_user(payload: UserCreate, admin: UserAdmin, db: DbSession) -> UserRead:
    exists = db.execute(select(User).where(User.username == payload.username)).scalar_one_or_none()
    if exists:
        raise HTTPException(status_code=409, detail="Такой логин уже занят")

    data = payload.model_dump(exclude={"password", "pin"})
    role = Role(payload.role)
    defaults = PERMISSION_DEFAULTS.get(role, {})
    for flag, value in defaults.items():
        if data.get(flag) is None:
            data[flag] = value
    if role in (Role.owner, Role.admin):
        # owner/admin always keep full rights, even if the form unchecked them
        for flag in defaults:
            data[flag] = True

    user = User(**data, hashed_password=hash_password(payload.password))
    if payload.pin:
        user.pin_hash = hash_password(payload.pin)

    db.add(user)
    db.flush()
    _audit(db, admin, "create", "user", str(user.id), {"username": user.username, "role": user.role})
    db.commit()
    db.refresh(user)
    return UserRead.model_validate(user)


@router.patch("/{user_id}", response_model=UserRead)
def update_user(
    user_id: uuid.UUID, payload: UserUpdate, admin: UserAdmin, db: DbSession
) -> UserRead:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Сотрудник не найден")

    data = payload.model_dump(exclude_unset=True)
    password = data.pop("password", None)
    pin = data.pop("pin", None)

    if user.id == admin.id and data.get("is_active") is False:
        raise HTTPException(status_code=400, detail="Нельзя деактивировать себя")
    if user.id == admin.id and data.get("role") not in (None, Role.owner, Role.admin):
        raise HTTPException(status_code=400, detail="Нельзя понизить самого себя")

    if data.get("role"):
        for flag, value in PERMISSION_DEFAULTS.get(Role(data["role"]), {}).items():
            if data.get(flag) is None:
                data[flag] = value

    for field, value in data.items():
        setattr(user, field, value)
    if password:
        user.hashed_password = hash_password(password)
    if pin:
        user.pin_hash = hash_password(pin)

    _audit(db, admin, "update", "user", str(user.id), {"changes": list(data.keys())})
    db.commit()
    db.refresh(user)
    return UserRead.model_validate(user)


@router.post("/{user_id}/reset-pin")
def set_pin(user_id: uuid.UUID, payload: PinReset, admin: UserAdmin, db: DbSession) -> dict:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Сотрудник не найден")
    user.pin_hash = hash_password(payload.pin)
    _audit(db, admin, "set_pin", "user", str(user.id), {})
    db.commit()
    return {"ok": True}


@router.delete("/{user_id}")
def deactivate_user(user_id: uuid.UUID, admin: UserAdmin, db: DbSession) -> dict:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Сотрудник не найден")
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="Нельзя удалить себя")
    user.is_active = False
    _audit(db, admin, "deactivate", "user", str(user.id), {})
    db.commit()
    return {"ok": True}
