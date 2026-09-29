from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.core.security import create_access_token, hash_password, verify_password
from app.db.base import Role
from app.models.user import User
from app.schemas.user import (
    LoginRequest,
    PasswordChange,
    Token,
    UserRead,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=Token)
def login(payload: LoginRequest, db: DbSession) -> Token:
    user = db.execute(select(User).where(User.username == payload.username)).scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Неверный логин или пароль")

    if payload.pin:
        ok = user.pin_hash is not None and verify_password(payload.pin, user.pin_hash)
    else:
        ok = verify_password(payload.password, user.hashed_password)

    if not ok:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Неверный логин или пароль")

    user.last_login_at = datetime.now(UTC)
    db.commit()
    db.refresh(user)
    return Token(
        access_token=create_access_token(user.id),
        user=UserRead.model_validate(user),
    )


@router.get("/me", response_model=UserRead)
def me(user: CurrentUser) -> User:
    return user


@router.post("/change-password")
def change_password(
    payload: PasswordChange,
    user: CurrentUser,
    db: DbSession,
) -> dict:
    if not verify_password(payload.current_password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Текущий пароль неверен")

    user.hashed_password = hash_password(payload.new_password)
    db.commit()
    return {"ok": True}


PERMISSION_DEFAULTS: dict[str, dict[str, bool]] = {
    Role.owner: {
        "can_manage_menu": True,
        "can_manage_hall": True,
        "can_manage_orders": True,
        "can_manage_users": True,
        "can_view_reports": True,
    },
    Role.admin: {
        "can_manage_menu": True,
        "can_manage_hall": True,
        "can_manage_orders": True,
        "can_manage_users": True,
        "can_view_reports": True,
    },
    Role.manager: {
        "can_manage_menu": True,
        "can_manage_hall": True,
        "can_manage_orders": True,
        "can_manage_users": False,
        "can_view_reports": True,
    },
    Role.waiter: {
        "can_manage_menu": False,
        "can_manage_hall": False,
        "can_manage_orders": True,
        "can_manage_users": False,
        "can_view_reports": False,
    },
}


@router.get("/roles")
def list_roles() -> list[dict]:
    return [
        {
            "value": role.value,
            "label": label,
            "permissions": PERMISSION_DEFAULTS[role],
        }
        for role, label in (
            (Role.owner, "Владелец"),
            (Role.admin, "Администратор"),
            (Role.manager, "Менеджер"),
            (Role.waiter, "Официант"),
        )
    ]
