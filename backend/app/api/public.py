from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import DbSession
from app.db.base import TableStatus
from app.models.hall import Table
from app.models.user import AppSetting
from app.schemas.menu import PublicMenu
from app.schemas.order import GuestCartRequest, OrderRead
from app.services import hall as hall_service
from app.services import orders as order_service
from app.services.menu import (
    build_tree,
    get_or_create_menu_settings,
    group_dishes,
    menu_settings_read,
    public_menu_payload,
)
from app.services.ws import publish_kitchen_order, publish_occupancy_change

router = APIRouter(prefix="/public", tags=["public"])


def get_table_by_token(db: Session, token: str, *, require_seated: bool = False) -> Table:
    table = db.execute(
        select(Table).options(selectinload(Table.hall)).where(Table.qr_token == token)
    ).scalar_one_or_none()
    if table is None or not table.is_active:
        raise HTTPException(status_code=404, detail="Стол не найден")
    if require_seated:
        session = hall_service.get_active_session(db, table.id)
        if session is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Сканируйте QR-код, когда вас уже посадили за стол",
            )
    return table


def venue_name(db: Session) -> str:
    row = db.execute(select(AppSetting).where(AppSetting.key == "venue_name")).scalar_one_or_none()
    return row.value if row and row.value else "Ресторан"


def _table_rows(db: Session, token: str) -> Table:
    """Resolve a QR token, loading the hall for name display."""
    return get_table_by_token(db, token)


@router.get("/menu/{token}", response_model=PublicMenu)
def get_menu(token: str, db: DbSession) -> PublicMenu:
    table = get_table_by_token(db, token)
    categories, dishes = public_menu_payload(db)
    tree = build_tree(categories, group_dishes(dishes))
    return PublicMenu(
        venue=venue_name(db),
        table_name=table.name,
        table_number=table.name,
        hall_name=table.hall.name if table.hall else "",
        settings=menu_settings_read(get_or_create_menu_settings(db)),
        categories=tree,
        dishes_count=len(dishes),
    )


@router.get("/table/{token}")
def table_info(token: str, db: DbSession) -> dict:
    table = get_table_by_token(db, token)
    session = hall_service.get_active_session(db, table.id)
    orders = order_service.open_orders_for_table(db, table.id)
    return {
        "id": str(table.id),
        "name": table.name,
        "hall": table.hall.name if table.hall else "",
        "seats": table.seats,
        "venue": venue_name(db),
        "is_seated": session is not None,
        "status": session.status if session else TableStatus.free,
        "guests_count": session.guests_count if session else 0,
        "orders": [order_service.order_read(o).model_dump(mode="json") for o in orders],
    }


@router.post("/table/{token}/order", response_model=OrderRead, status_code=status.HTTP_201_CREATED)
def place_order(token: str, payload: GuestCartRequest, db: DbSession) -> OrderRead:
    table = get_table_by_token(db, token)
    session = hall_service.get_active_session(db, table.id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="За столом ещё никто не сидит. Подойдите к официанту.",
        )

    order = order_service.create_order(
        db,
        payload.items,
        table=table,
        table_session=session,
        source="qr",
        guest_comment=payload.guest_comment,
        guests_count=payload.guests_count,
    )
    if order is None:
        raise HTTPException(status_code=400, detail="Все позиции недоступны")

    loaded = order_service.load_order(db, order.id)
    result = order_service.order_read(loaded)

    publish_kitchen_order(
        {
            "order": result.model_dump(mode="json"),
            "table": table.name,
            "hall": table.hall.name if table.hall else "",
        }
    )
    publish_occupancy_change(
        {
            "table_id": str(table.id),
            "table": table.name,
            "open_orders": len(order_service.open_orders_for_table(db, table.id)),
        }
    )
    return result


@router.get("/table/{token}/orders", response_model=list[OrderRead])
def table_orders(token: str, db: DbSession) -> list[OrderRead]:
    table = get_table_by_token(db, token)
    orders = order_service.open_orders_for_table(db, table.id)
    return [order_service.order_read(o) for o in orders]
