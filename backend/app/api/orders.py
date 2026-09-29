from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import DbSession, FloorReader, OrderEditor
from app.db.base import OrderStatus
from app.models.hall import Table
from app.models.order import Order, OrderItem, OrderItemModifier
from app.schemas.order import (
    KitchenBoard,
    OrderCreate,
    OrderItemAdd,
    OrderRead,
    OrderStatusChange,
    OrderUpdate,
)
from app.services import hall as hall_service
from app.services import orders as order_service
from app.services.ws import publish_kitchen_order

router = APIRouter(prefix="/admin/orders", tags=["admin:orders"])


def _load(db, order_id: uuid.UUID) -> Order:
    order = order_service.load_order(db, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Заказ не найден")
    return order


@router.get("", response_model=list[OrderRead])
def list_orders(
    _: FloorReader,
    db: DbSession,
    status_filter: str | None = Query(default=None, alias="status"),
    table_id: uuid.UUID | None = None,
    source: str | None = None,
    only_open: bool = False,
    limit: int = Query(100, ge=1, le=500),
) -> list[OrderRead]:
    stmt = select(Order).options(
        selectinload(Order.items).selectinload(OrderItem.modifiers),
        selectinload(Order.table),
    )
    if status_filter:
        stmt = stmt.where(Order.status == status_filter)
    if source:
        stmt = stmt.where(Order.source == source)
    if table_id:
        stmt = stmt.where(Order.table_id == table_id)
    if only_open:
        stmt = stmt.where(Order.status.in_(order_service.ACTIVE_STATUSES))
    rows = db.execute(stmt.order_by(Order.created_at.desc()).limit(limit)).scalars().unique()
    return [order_service.order_read(o) for o in rows]


@router.get("/kitchen", response_model=KitchenBoard)
def kitchen_board(_: OrderEditor, db: DbSession) -> KitchenBoard:
    """Everything the kitchen has to cook right now."""
    stmt = (
        select(Order)
        .options(
            selectinload(Order.items).selectinload(OrderItem.modifiers),
            selectinload(Order.table),
        )
        .where(Order.status.in_([OrderStatus.new, OrderStatus.in_progress, OrderStatus.ready]))
        .order_by(Order.created_at)
    )
    rows = list(db.execute(stmt).scalars().unique())
    return KitchenBoard(
        orders=[order_service.order_read(o) for o in rows],
        max_wait_minutes=order_service.max_wait_minutes(rows),
    )


@router.get("/{order_id}", response_model=OrderRead)
def get_order(order_id: uuid.UUID, _: FloorReader, db: DbSession) -> OrderRead:
    return order_service.order_read(_load(db, order_id))


@router.post("", response_model=OrderRead, status_code=status.HTTP_201_CREATED)
def create_order(payload: OrderCreate, user: OrderEditor, db: DbSession) -> OrderRead:
    table = db.get(Table, payload.table_id) if payload.table_id else None
    session = hall_service.get_active_session(db, table.id) if table else None

    order = order_service.create_order(
        db,
        payload.items,
        table=table,
        table_session=session,
        source=payload.source,
        created_by_user_id=user.id,
        guest_comment=payload.guest_comment,
        guests_count=payload.guests_count,
        client_name=payload.client_name,
    )
    if order is None:
        raise HTTPException(status_code=400, detail="Все позиции недоступны")

    loaded = order_service.load_order(db, order.id)
    result = order_service.order_read(loaded)
    publish_kitchen_order({"order": result.model_dump(mode="json"), "table": table.name if table else ""})
    return result


@router.patch("/{order_id}", response_model=OrderRead)
def update_order(
    order_id: uuid.UUID, payload: OrderUpdate, _: OrderEditor, db: DbSession
) -> OrderRead:
    order = _load(db, order_id)
    data = payload.model_dump(exclude_unset=True)
    new_status = data.pop("status", None)
    for field, value in data.items():
        setattr(order, field, value)
    if new_status:
        order.status = new_status
        if new_status == OrderStatus.closed and order.closed_at is None:
            order.closed_at = datetime.now(UTC)
    db.commit()
    result = order_service.order_read(_load(db, order_id))
    publish_kitchen_order({"order": result.model_dump(mode="json"), "event": "order.updated"})
    return result


@router.post("/{order_id}/status", response_model=OrderRead)
def change_status(
    order_id: uuid.UUID, payload: OrderStatusChange, _: OrderEditor, db: DbSession
) -> OrderRead:
    order = _load(db, order_id)
    order.status = payload.status
    if payload.status == OrderStatus.closed:
        order.closed_at = datetime.now(UTC)
    for item in order.items:
        if payload.status in order_service.ACTIVE_STATUSES:
            item.status = payload.status
    db.commit()
    result = order_service.order_read(_load(db, order_id))
    publish_kitchen_order({"order": result.model_dump(mode="json"), "event": "order.status"})
    return result


@router.post("/{order_id}/next-status", response_model=OrderRead)
def next_status(order_id: uuid.UUID, _: OrderEditor, db: DbSession) -> OrderRead:
    """One tap in the kitchen: new -> cooking -> ready -> served."""
    order = _load(db, order_id)
    nxt = order_service.KITCHEN_FLOW.get(OrderStatus(order.status))
    if nxt is None:
        raise HTTPException(status_code=400, detail="Заказ в финальном статусе")
    order.status = nxt
    for item in order.items:
        item.status = nxt
    if nxt == OrderStatus.served:
        order.closed_at = order.closed_at or datetime.now(UTC)
    db.commit()
    result = order_service.order_read(_load(db, order_id))
    publish_kitchen_order({"order": result.model_dump(mode="json"), "event": "order.status"})
    return result


@router.post("/{order_id}/items", response_model=OrderRead)
def add_items(
    order_id: uuid.UUID, payload: OrderItemAdd, _: OrderEditor, db: DbSession
) -> OrderRead:
    order = _load(db, order_id)
    built = order_service.build_items(db, [payload])
    if not built:
        raise HTTPException(status_code=400, detail="Блюдо недоступно")

    for dish, qty, comment, mods, _line in built:
        item = OrderItem(
            order_id=order.id,
            dish_id=dish.id,
            dish_name=dish.name,
            price=Decimal(dish.price) / 100,
            quantity=qty,
            comment=comment,
            cooking_minutes=dish.cooking_minutes,
        )
        for mod, name, price_delta in mods:
            item.modifiers.append(
                OrderItemModifier(
                    modifier_id=mod.id,
                    name=name,
                    price_delta=Decimal(price_delta) / 100,
                )
            )
        db.add(item)

    db.flush()
    order_service.recalc_total(db, order)
    db.commit()
    result = order_service.order_read(_load(db, order_id))
    publish_kitchen_order({"order": result.model_dump(mode="json"), "event": "order.items"})
    return result


@router.delete("/{order_id}/items/{item_id}", response_model=OrderRead)
def remove_item(
    order_id: uuid.UUID, item_id: uuid.UUID, _: OrderEditor, db: DbSession
) -> OrderRead:
    order = _load(db, order_id)
    item = db.get(OrderItem, item_id)
    if item is None or item.order_id != order.id:
        raise HTTPException(status_code=404, detail="Позиция не найдена")
    db.delete(item)
    db.flush()
    order_service.recalc_total(db, order)
    db.commit()
    # expire_on_commit=False keeps the stale collection in the identity map,
    # so the deleted row would still show up in the response
    db.expire(order, ["items"])
    return order_service.order_read(_load(db, order_id))


@router.post("/{order_id}/cancel", response_model=OrderRead)
def cancel_order(order_id: uuid.UUID, _: OrderEditor, db: DbSession) -> OrderRead:
    order = _load(db, order_id)
    order.status = OrderStatus.cancelled
    order.closed_at = datetime.now(UTC)
    db.commit()
    result = order_service.order_read(_load(db, order_id))
    publish_kitchen_order({"order": result.model_dump(mode="json"), "event": "order.cancelled"})
    return result
