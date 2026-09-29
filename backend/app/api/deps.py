from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.db.base import Role
from app.db.session import get_db
from app.models.user import User

bearer_scheme = HTTPBearer(auto_error=False)

DbSession = Annotated[Session, Depends(get_db)]
Credentials = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)]

ROLE_LEVEL = {
    Role.waiter: 0,
    Role.manager: 1,
    Role.admin: 2,
    Role.owner: 3,
}


def get_current_user(db: DbSession, credentials: Credentials) -> User:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Требуется авторизация",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = decode_access_token(credentials.credentials)
    if not payload or payload.get("type") != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Недействительный токен")

    try:
        user_id = uuid.UUID(str(payload.get("sub")))
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Недействительный токен"
        ) from None

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Пользователь отключён")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def _at_least(user: User, minimum: Role) -> bool:
    return ROLE_LEVEL.get(Role(user.role), -1) >= ROLE_LEVEL[minimum]


def _role_checker(minimum: Role):
    def checker(user: CurrentUser) -> User:
        if not _at_least(user, minimum):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Недостаточно прав")
        return user

    return checker


def _flag_checker(flag: str):
    def checker(user: CurrentUser) -> User:
        if not can(user, flag):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Недостаточно прав")
        return user

    return checker


def require_min_role(minimum: Role):
    """Dependency alias: `Annotated[User, Depends(...)]` for role gates."""
    return Annotated[User, Depends(_role_checker(minimum))]


def require_flag(flag: str):
    """Dependency alias for a single capability, e.g. require_flag('can_manage_menu')."""
    return Annotated[User, Depends(_flag_checker(flag))]


def require_any_flag(*flags: str):
    """Passes when the user holds at least one of the capabilities."""

    def checker(user: CurrentUser) -> User:
        if not any(can(user, flag) for flag in flags):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Недостаточно прав")
        return user

    return Annotated[User, Depends(checker)]


def require_roles(*roles: Role):
    allowed = set(roles)

    def checker(user: CurrentUser) -> User:
        if Role(user.role) not in allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Недостаточно прав")
        return user

    return Annotated[User, Depends(checker)]


# --- ready-made gates used across the API ---------------------------
Staff = CurrentUser
Manager = require_min_role(Role.manager)
Admin = require_min_role(Role.admin)
Owner = require_min_role(Role.owner)

# Anyone who works the floor: takes orders, seats guests or lays out the hall.
# Operational reads must not require can_view_reports or a waiter sees a 403
# on the very screen their job depends on.
FloorReader = require_any_flag("can_manage_orders", "can_manage_hall", "can_view_reports")

MenuEditor = require_flag("can_manage_menu")
MenuViewer = FloorReader
HallEditor = require_flag("can_manage_hall")
OrderEditor = require_flag("can_manage_orders")
UserAdmin = require_flag("can_manage_users")
# Reporter gates money and statistics only: a waiter works the floor without it
Reporter = require_flag("can_view_reports")


def can(user: User, flag: str) -> bool:
    return Role(user.role) in (Role.owner, Role.admin) or bool(getattr(user, flag, False))


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
